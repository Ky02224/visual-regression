"""Storage logic shared by the SQLite and PostgreSQL backends.

SqliteStore and PostgresStore held ~1400 lines between them implementing the
same 23 methods twice. Measured method-by-method, the two copies were 80-96%
identical — the differences were almost entirely the parameter placeholder
(``?`` vs ``%s``) and whether rows came back from a cursor or a helper.

Two copies of an auth check is not a style problem: a fix applied to one and not
the other means the same deployment behaves differently depending on which
database it was configured with, and nothing fails to tell you. The comment
delete route hit exactly that, with its own sqlite/postgres branches inline.

Subclasses provide two things:

* ``_PLACEHOLDER`` — the parameter marker their driver expects.
* ``_execute_query(query, params, commit, fetch)`` — both already had this with
  an identical signature, which is what makes the merge possible at all.

Queries here are written with ``{p}`` and rendered by ``_sql``. Schema creation
(``_init_db``) and the bulk index writers stay in the subclasses: those differ in
substance — AUTOINCREMENT vs SERIAL, ON CONFLICT syntax, executemany semantics —
not just in punctuation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _utc_epoch() -> int:
    return int(time.time())


# PBKDF2 iteration counts — OWASP 2023 recommends >= 600,000 for SHA-256.
_PBKDF2_ITERATIONS = 600_000         # Used for all newly created passwords
_PBKDF2_LEGACY_ITERATIONS = 210_000  # Retained for backward-compat verification


@dataclass(frozen=True)
class AuthUser:
    email: str
    role: str
    display_name: str = ""

# A user may hold at most this many concurrent sessions; the oldest is evicted.
# Without a cap, every login from a new browser leaves a session row that stays
# valid until its TTL, so a shared account accumulates live credentials.
MAX_SESSIONS_PER_USER = 5

# How long a resolved session is trusted from memory before the database is
# consulted again. Short enough that a deleted session stops working promptly,
# long enough that a burst of requests does not each pay for a join.
_SESSION_CACHE_TTL_SECONDS = 5.0


def _pbkdf2_hash(password: str, salt: bytes, iterations: int = _PBKDF2_ITERATIONS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def hash_password(password: str) -> Tuple[str, str]:
    salt = secrets.token_bytes(16)
    digest = _pbkdf2_hash(password, salt)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, digest_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except Exception:
        return False
    # compare_digest, not ==: a short-circuiting comparison leaks how much of the
    # hash matched through its timing.
    #
    # Try the current (stronger) iteration count first; fall back to the legacy
    # count for users whose passwords were hashed before the upgrade.
    actual = _pbkdf2_hash(password, salt, _PBKDF2_ITERATIONS)
    if hmac.compare_digest(actual, expected):
        return True
    legacy = _pbkdf2_hash(password, salt, _PBKDF2_LEGACY_ITERATIONS)
    return hmac.compare_digest(legacy, expected)


class BaseStore:
    """Backend-agnostic implementations of the auth, session, comment and audit APIs."""

    _PLACEHOLDER = "?"

    # Subclasses set these in their own __init__ before calling any method here.
    _session_cache: Dict[str, Tuple[float, AuthUser]]
    _session_cache_lock: threading.Lock

    # ------------------------------------------------------------------
    # To be provided by the backend
    # ------------------------------------------------------------------

    def _execute_query(
        self,
        query: str,
        params: tuple | list | dict = (),
        commit: bool = False,
        fetch: bool = False,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def _now(self) -> int:
        """Current epoch seconds.

        An indirection rather than a direct _utc_epoch() call so a subclass — and
        the tests that monkeypatch a store module's _utc_epoch to make ordering
        deterministic — still control the clock these methods see.
        """
        return _utc_epoch()

    def _sql(self, query: str) -> str:
        """Render a ``{p}``-templated query for this backend's placeholder."""
        return query.format(p=self._PLACEHOLDER)

    def _query(self, sql: str, params=(), commit: bool = False, fetch: bool = False):
        return self._execute_query(self._sql(sql), params, commit=commit, fetch=fetch)

    def _one(self, sql: str, params=()) -> Optional[Dict[str, Any]]:
        rows = self._query(sql, params, fetch=True)
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    VALID_ROLES = frozenset({"admin", "developer", "viewer"})

    def create_user(self, email: str, password: str, role: str, display_name: str = "") -> None:
        email = email.strip().lower()
        if role not in self.VALID_ROLES:
            raise ValueError("Invalid role")
        salt_hex, digest_hex = hash_password(password)
        self._query(
            "INSERT INTO users(email, role, password_salt, password_hash, disabled, created_at, display_name) "
            "VALUES({p},{p},{p},{p},0,{p},{p});",
            (email, role, salt_hex, digest_hex, self._now(), display_name.strip()),
            commit=True,
        )

    def authenticate(self, email: str, password: str) -> Optional[AuthUser]:
        email = (email or "").strip().lower()
        row = self._one(
            "SELECT email, role, display_name, password_salt, password_hash, disabled "
            "FROM users WHERE email={p};",
            (email,),
        )
        if not row or int(row["disabled"] or 0) == 1:
            return None
        if not verify_password(password, str(row["password_salt"]), str(row["password_hash"])):
            return None
        return AuthUser(
            email=str(row["email"]),
            role=str(row["role"]),
            display_name=str(row["display_name"] or ""),
        )

    def list_users(self) -> list:
        rows = self._query(
            "SELECT email, role, display_name, disabled, created_at FROM users ORDER BY email ASC;",
            fetch=True,
        )
        return [
            {
                "email": str(row["email"]),
                "role": str(row["role"]),
                "display_name": str(row["display_name"] or ""),
                "disabled": bool(row["disabled"]),
                "created_at": int(row["created_at"] or 0),
            }
            for row in rows
        ]

    def delete_user(self, email: str) -> None:
        self._query("DELETE FROM users WHERE email={p};", (email.strip().lower(),), commit=True)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def create_session(self, email: str, ttl_seconds: int = 60 * 60 * 12) -> str:
        email = email.strip().lower()
        token = secrets.token_urlsafe(32)
        now = self._now()

        row = self._one("SELECT id FROM users WHERE email={p};", (email,))
        if not row:
            raise FileNotFoundError("user not found")
        user_id = int(row["id"])

        sessions = self._query(
            "SELECT token FROM sessions WHERE user_id={p} ORDER BY created_at ASC;",
            (user_id,),
            fetch=True,
        )
        if len(sessions) >= MAX_SESSIONS_PER_USER:
            oldest_token = str(sessions[0]["token"])
            self._query("DELETE FROM sessions WHERE token={p};", (oldest_token,), commit=True)
            # Evict from the cache too, or the deleted session keeps
            # authenticating for up to the cache TTL.
            with self._session_cache_lock:
                self._session_cache.pop(oldest_token, None)

        self._query(
            "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES({p},{p},{p},{p});",
            (token, user_id, now, now + int(ttl_seconds)),
            commit=True,
        )
        return token

    def delete_session(self, token: str) -> None:
        token = (token or "").strip()
        if not token:
            return
        self._query("DELETE FROM sessions WHERE token={p};", (token,), commit=True)
        with self._session_cache_lock:
            self._session_cache.pop(token, None)

    def user_for_session(self, token: str) -> Optional[AuthUser]:
        token = (token or "").strip()
        if not token:
            return None

        now_time = time.time()
        with self._session_cache_lock:
            cached = self._session_cache.get(token)
            if cached:
                expiry, user = cached
                if now_time < expiry:
                    return user
                del self._session_cache[token]

        row = self._one(
            "SELECT u.email AS email, u.role AS role, u.display_name AS display_name, "
            "s.expires_at AS expires_at FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token = {p};",
            (token,),
        )
        if not row:
            return None
        if int(row["expires_at"]) < self._now():
            self._query("DELETE FROM sessions WHERE token={p};", (token,), commit=True)
            return None

        user = AuthUser(
            email=str(row["email"]),
            role=str(row["role"]),
            display_name=str(row["display_name"] or ""),
        )
        with self._session_cache_lock:
            self._session_cache[token] = (now_time + _SESSION_CACHE_TTL_SECONDS, user)
        return user

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def audit(
        self,
        actor_email: Optional[str],
        actor_role: Optional[str],
        action: str,
        detail: Dict[str, Any],
    ) -> None:
        # ensure_ascii=False so a non-Latin actor name or comment survives
        # readable in the audit trail rather than as \\uXXXX escapes.
        self._query(
            "INSERT INTO audit_logs(timestamp, actor_email, actor_role, action, detail_json) "
            "VALUES({p},{p},{p},{p},{p});",
            (self._now(), actor_email, actor_role, action, json.dumps(detail or {}, ensure_ascii=False)),
            commit=True,
        )

    def get_audit_logs(self, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self._query(
            "SELECT id, timestamp, actor_email, actor_role, action, detail_json "
            "FROM audit_logs ORDER BY timestamp DESC LIMIT {p};",
            (limit,),
            fetch=True,
        )
        result = []
        for row in rows:
            try:
                detail = json.loads(row["detail_json"] or "{}")
            except Exception as exc:
                # An unparseable detail must not be indistinguishable from an
                # action that genuinely recorded none — this is an audit trail.
                logger.warning(
                    "Audit log row %s has unparseable detail_json (%s: %s); reporting it as empty.",
                    row["id"], type(exc).__name__, exc,
                )
                detail = {}
            # Values are passed through as the driver returned them rather than
            # coerced: this is a dedup of two existing implementations, and
            # changing the payload's types here would be a behaviour change
            # smuggled in under a refactor.
            result.append(
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "actor_email": row["actor_email"],
                    "actor_role": row["actor_role"],
                    "action": row["action"],
                    "detail": detail,
                }
            )
        return result

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    @staticmethod
    def _comment_row(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(row["id"]),
            "run_id": str(row["run_id"]),
            "x_pct": float(row["x_pct"]),
            "y_pct": float(row["y_pct"]),
            "author": str(row["author"]),
            "content": str(row["content"]),
            "created_at": int(row["created_at"]),
        }

    # Comment bodies are user-supplied and rendered into the run report; cap
    # them so one caller cannot store an unbounded blob per run.
    MAX_COMMENT_LENGTH = 5000

    def add_comment(
        self,
        comment_id: str,
        run_id: str,
        x_pct: float,
        y_pct: float,
        author: str,
        content: str,
    ) -> None:
        content = content[: self.MAX_COMMENT_LENGTH]
        self._query(
            "INSERT INTO comments(id, run_id, x_pct, y_pct, author, content, created_at) "
            "VALUES({p},{p},{p},{p},{p},{p},{p});",
            (comment_id, run_id, x_pct, y_pct, author.strip(), content.strip(), self._now()),
            commit=True,
        )

    def list_comments(self, run_id: str) -> List[Dict[str, Any]]:
        rows = self._query(
            "SELECT id, run_id, x_pct, y_pct, author, content, created_at FROM comments "
            "WHERE run_id={p} ORDER BY created_at ASC;",
            (run_id,),
            fetch=True,
        )
        return [self._comment_row(row) for row in rows]

    def get_comment(self, comment_id: str) -> Optional[Dict[str, Any]]:
        """Return one comment, or None.

        Exists so the HTTP layer can check a comment's author before deleting it
        without writing SQL of its own.
        """
        row = self._one(
            "SELECT id, run_id, x_pct, y_pct, author, content, created_at "
            "FROM comments WHERE id={p};",
            (comment_id,),
        )
        return self._comment_row(row) if row else None

    def delete_comment(self, comment_id: str) -> None:
        self._query("DELETE FROM comments WHERE id={p};", (comment_id,), commit=True)
