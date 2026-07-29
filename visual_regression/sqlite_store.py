from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Thread-local storage so each thread reuses its own SQLite connection
# instead of opening a new file handle on every _connect() call.
_thread_local = threading.local()


def _utc_epoch() -> int:
    return int(time.time())


# PBKDF2 iteration counts — OWASP 2023 recommends ≥ 600,000 for SHA-256.
_PBKDF2_ITERATIONS = 600_000         # Used for all newly created passwords
_PBKDF2_LEGACY_ITERATIONS = 210_000  # Retained for backward-compat verification


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
    # Try the current (stronger) iteration count first; fall back to the legacy
    # count for users whose passwords were hashed before the upgrade.
    actual = _pbkdf2_hash(password, salt, _PBKDF2_ITERATIONS)
    if hmac.compare_digest(actual, expected):
        return True
    legacy = _pbkdf2_hash(password, salt, _PBKDF2_LEGACY_ITERATIONS)
    return hmac.compare_digest(legacy, expected)


@dataclass(frozen=True)
class AuthUser:
    email: str
    role: str
    display_name: str = ""


class SqliteStore:
    def __init__(self, db_path: Path):
        import threading
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._session_cache = {}  # {token: (expiry_time, AuthUser)}
        self._session_cache_lock = threading.Lock()
        threading.Thread(target=self._cleanup_expired_loop, daemon=True).start()

    def _cleanup_expired_loop(self) -> None:
        import time
        while True:
            try:
                now = _utc_epoch()
                with self._connect() as conn:
                    conn.execute("DELETE FROM sessions WHERE expires_at < ?;", (now,))
            except Exception:
                logger.debug("Session cleanup pass failed; will retry next cycle", exc_info=True)
            time.sleep(3600)

    def _connect(self) -> sqlite3.Connection:
        """Return a per-thread cached SQLite connection.

        SQLite connections are not thread-safe to share, but reusing one
        connection per thread (thread-local storage) eliminates the cost of
        opening a new file handle on every single database call.
        """
        conn = getattr(_thread_local, "conn", None)
        db_path_str = str(self.db_path)
        # Re-create if the connection doesn't exist or points to a different DB
        if conn is None or getattr(_thread_local, "db_path", None) != db_path_str:
            conn = sqlite3.connect(db_path_str, timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            _thread_local.conn = conn
            _thread_local.db_path = db_path_str
            conn.execute("PRAGMA busy_timeout=30000;")
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
            except Exception:
                pass
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _execute_query(self, query: str, params: tuple | list | dict = (), commit: bool = False, fetch: bool = False) -> List[Dict[str, Any]]:
        max_retries = 5
        base_delay = 0.05
        for attempt in range(max_retries):
            try:
                with self._connect() as conn:
                    cursor = conn.execute(query, params)
                    if commit:
                        # sqlite3 automatically commits when using connection as context manager,
                        # but explicit commit is safe and matches PostgresStore signature.
                        try:
                            conn.commit()
                        except Exception:
                            pass
                    if fetch:
                        rows = cursor.fetchall()
                        return [dict(row) for row in rows]
                    return []
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    time.sleep(base_delay * (2 ** attempt))
                    continue
                raise



    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT NOT NULL UNIQUE,
                  role TEXT NOT NULL,
                  password_salt TEXT NOT NULL,
                  password_hash TEXT NOT NULL,
                  disabled INTEGER NOT NULL DEFAULT 0,
                  created_at INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  token TEXT PRIMARY KEY,
                  user_id INTEGER NOT NULL,
                  created_at INTEGER NOT NULL,
                  expires_at INTEGER NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);")
            try:
                conn.execute("ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT '';")
            except sqlite3.OperationalError as e:
                if 'duplicate column' not in str(e).lower():
                    raise
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp INTEGER NOT NULL,
                  actor_email TEXT,
                  actor_role TEXT,
                  action TEXT NOT NULL,
                  detail_json TEXT NOT NULL
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS baselines_index (
                  name TEXT PRIMARY KEY,
                  url TEXT,
                  browser TEXT,
                  device TEXT,
                  locale TEXT,
                  timezone_id TEXT,
                  viewport TEXT,
                  created_at TEXT,
                  updated_at TEXT,
                  version_count INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs_index (
                  run_id TEXT PRIMARY KEY,
                  case_name TEXT,
                  baseline_name TEXT,
                  suite_name TEXT,
                  status TEXT,
                  mismatch_pct REAL,
                  diff_regions INTEGER,
                  decision_status TEXT,
                  decided_at TEXT,
                  severity_label TEXT,
                  ai_label TEXT,
                  browser TEXT,
                  device TEXT,
                  locale TEXT,
                  url TEXT,
                  report_href TEXT,
                  decider TEXT,
                  decision_comment TEXT,
                  ai_score REAL,
                  build_id TEXT,
                  created_at INTEGER NOT NULL
                );
                """
            )
            try:
                conn.execute("ALTER TABLE runs_index ADD COLUMN decider TEXT;")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE runs_index ADD COLUMN decision_comment TEXT;")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE runs_index ADD COLUMN ai_score REAL;")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE runs_index ADD COLUMN build_id TEXT;")
            except sqlite3.OperationalError:
                pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_case ON runs_index(case_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_suite ON runs_index(suite_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs_index(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_build ON runs_index(build_id);")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS comments (
                  id TEXT PRIMARY KEY,
                  run_id TEXT NOT NULL,
                  x_pct REAL NOT NULL,
                  y_pct REAL NOT NULL,
                  author TEXT NOT NULL,
                  content TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  FOREIGN KEY(run_id) REFERENCES runs_index(run_id) ON DELETE CASCADE
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_comments_run ON comments(run_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor_email);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_baseline ON runs_index(baseline_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs_index(status);")
            # ── Performance indexes added for Storage & Database optimisation ──────
            # Supports ORDER BY created_at DESC in run history / dashboard queries.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs_index(created_at DESC);"
            )
            # Fast lookup of baselines by name (covers prefix/equality searches).
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_baselines_name ON baselines_index(name);"
            )
            # Composite covering index: baseline_name + created_at for
            # 'show all runs for baseline X sorted by date' queries.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_baseline_created "
                "ON runs_index(baseline_name, created_at DESC);"
            )

    def upsert_baseline_index(self, item: Dict[str, Any]) -> None:
        name = str(item.get("name") or "").strip()
        if not name:
            return
        viewport = item.get("viewport")
        viewport_text = ""
        if isinstance(viewport, (list, tuple)) and len(viewport) == 2:
            viewport_text = f"{viewport[0]}x{viewport[1]}"
        elif isinstance(viewport, str):
            viewport_text = viewport
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO baselines_index(
                  name, url, browser, device, locale, timezone_id, viewport, created_at, updated_at, version_count
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                  url=excluded.url,
                  browser=excluded.browser,
                  device=excluded.device,
                  locale=excluded.locale,
                  timezone_id=excluded.timezone_id,
                  viewport=excluded.viewport,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at,
                  version_count=excluded.version_count;
                """,
                (
                    name,
                    item.get("url"),
                    item.get("browser"),
                    item.get("device"),
                    item.get("locale"),
                    item.get("timezone_id"),
                    viewport_text,
                    item.get("created_at"),
                    item.get("updated_at"),
                    int(item.get("version_count") or 0),
                ),
            )

    def upsert_run_index(self, item: Dict[str, Any]) -> None:
        run_id = str(item.get("run") or item.get("run_id") or "").strip()
        if not run_id:
            return
        now = _utc_epoch()
        severity = item.get("severity") or {}
        severity_label = ""
        if isinstance(severity, dict):
            severity_label = str(severity.get("label") or "")
        
        decision = item.get("decision") or {}
        decider = decision.get("reviewer") or decision.get("decider") or item.get("decider") or ""
        decision_comment = decision.get("comment") or item.get("decision_comment") or ""
        decision_status = decision.get("status") or item.get("decision_status") or "pending"
        decided_at = decision.get("timestamp") or item.get("decided_at") or ""

        ai_assessment = item.get("ai_assessment") or {}
        ai_score = ai_assessment.get("score") if "score" in ai_assessment else item.get("ai_score")
        if ai_score is not None:
            ai_score = float(ai_score)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs_index(
                  run_id, case_name, baseline_name, suite_name, status, mismatch_pct, diff_regions,
                  decision_status, decided_at, severity_label, ai_label, browser, device, locale, url, report_href,
                  decider, decision_comment, ai_score, build_id, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET
                  case_name=excluded.case_name,
                  baseline_name=excluded.baseline_name,
                  suite_name=excluded.suite_name,
                  status=excluded.status,
                  mismatch_pct=excluded.mismatch_pct,
                  diff_regions=excluded.diff_regions,
                  decision_status=excluded.decision_status,
                  decided_at=excluded.decided_at,
                  severity_label=excluded.severity_label,
                  ai_label=excluded.ai_label,
                  browser=excluded.browser,
                  device=excluded.device,
                  locale=excluded.locale,
                  url=excluded.url,
                  report_href=excluded.report_href,
                  decider=excluded.decider,
                  decision_comment=excluded.decision_comment,
                  ai_score=excluded.ai_score,
                  build_id=excluded.build_id;
                """,
                (
                    run_id,
                    item.get("case_name") or item.get("name"),
                    item.get("baseline_name"),
                    item.get("suite_name"),
                    item.get("status"),
                    item.get("mismatch_pct") or item.get("mismatch"),
                    item.get("diff_regions") or 0,
                    decision_status,
                    decided_at,
                    severity_label,
                    item.get("ai_label"),
                    item.get("browser"),
                    item.get("device"),
                    item.get("locale"),
                    item.get("url"),
                    item.get("report_href"),
                    decider,
                    decision_comment,
                    ai_score,
                    item.get("build_id"),
                    now,
                ),
            )

    def ensure_bootstrap_users(self) -> None:
        """
        Ensure default admin and user accounts always exist on every startup.
        Uses INSERT OR IGNORE so existing accounts (and their passwords) are never overwritten.

        - LENS_ADMIN_EMAIL / LENS_ADMIN_PASSWORD   (default: admin / admin1234)
        - LENS_DEVELOPER_EMAIL / LENS_DEVELOPER_PASSWORD  (default: user / user1234)
        """
        import sys
        admin_email = os.environ.get("LENS_ADMIN_EMAIL", "admin")
        admin_password = os.environ.get("LENS_ADMIN_PASSWORD", "admin1234")
        dev_email = os.environ.get("LENS_DEVELOPER_EMAIL", "user")
        dev_password = os.environ.get("LENS_DEVELOPER_PASSWORD", "user1234")

        # Warn loudly when factory-default credentials are in use
        _WEAK_DEFAULTS = {"admin1234", "user1234", "password", "admin", "user"}
        if admin_password in _WEAK_DEFAULTS or dev_password in _WEAK_DEFAULTS:
            print(
                "\n⚠️  [SECURITY WARNING] Default/weak credentials are in use!\n"
                "   Set LENS_ADMIN_PASSWORD and LENS_DEVELOPER_PASSWORD env vars\n"
                "   before deploying to any network-accessible environment.\n",
                file=sys.stderr,
                flush=True,
            )

        now = _utc_epoch()
        for email, password, role in [
            (admin_email, admin_password, "admin"),
            (dev_email, dev_password, "developer"),
        ]:
            email = email.strip().lower()
            salt_hex, digest_hex = hash_password(password)
            with self._connect() as conn:
                # INSERT OR IGNORE handles duplicate emails natively — no prior SELECT needed.
                conn.execute(
                    "INSERT OR IGNORE INTO users(email, role, password_salt, password_hash, disabled, created_at) VALUES(?,?,?,?,0,?);",
                    (email, role, salt_hex, digest_hex, now),
                )
        self.audit(None, None, "bootstrap.users", {"admin": admin_email, "user": dev_email})

    def create_user(self, email: str, password: str, role: str, display_name: str = "") -> None:
        email = email.strip().lower()
        if role not in {"admin", "developer", "viewer"}:
            raise ValueError("Invalid role")
        salt_hex, digest_hex = hash_password(password)
        now = _utc_epoch()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users(email, role, password_salt, password_hash, disabled, created_at, display_name) VALUES(?,?,?,?,0,?,?);",
                (email, role, salt_hex, digest_hex, now, display_name.strip()),
            )

    def authenticate(self, email: str, password: str) -> Optional[AuthUser]:
        email = email.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT email, role, password_salt, password_hash, disabled, display_name FROM users WHERE email=?;",
                (email,),
            ).fetchone()
        if not row:
            return None
        if int(row["disabled"] or 0) == 1:
            return None
        if not verify_password(password, str(row["password_salt"]), str(row["password_hash"])):
            return None
        return AuthUser(email=str(row["email"]), role=str(row["role"]), display_name=str(row["display_name"] or ""))

    def create_session(self, email: str, ttl_seconds: int = 60 * 60 * 12) -> str:
        email = email.strip().lower()
        token = secrets.token_urlsafe(32)
        now = _utc_epoch()
        expires_at = now + int(ttl_seconds)
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM users WHERE email=?;", (email,)).fetchone()
            if not row:
                raise FileNotFoundError("user not found")
            user_id = int(row["id"])
            
            # SS-03: Limit to max 5 concurrent sessions per user (LRU eviction)
            sessions = conn.execute("SELECT token FROM sessions WHERE user_id=? ORDER BY created_at ASC;", (user_id,)).fetchall()
            if len(sessions) >= 5:
                oldest_token = sessions[0]["token"]
                conn.execute("DELETE FROM sessions WHERE token=?;", (oldest_token,))
                with self._session_cache_lock:
                    if oldest_token in self._session_cache:
                        del self._session_cache[oldest_token]

            conn.execute(
                "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES(?,?,?,?);",
                (token, user_id, now, expires_at),
            )
        return token

    def delete_session(self, token: str) -> None:
        token = (token or "").strip()
        if not token:
            return
        with self._session_cache_lock:
            if token in self._session_cache:
                del self._session_cache[token]
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token=?;", (token,))

    def user_for_session(self, token: str) -> Optional[AuthUser]:
        token = (token or "").strip()
        if not token:
            return None
        import time
        now_time = time.time()
        with self._session_cache_lock:
            if token in self._session_cache:
                expiry, user = self._session_cache[token]
                if now_time < expiry:
                    return user
                else:
                    del self._session_cache[token]

        now = _utc_epoch()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.email AS email, u.role AS role, u.display_name AS display_name, s.expires_at AS expires_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token = ?;
                """,
                (token,),
            ).fetchone()
            if not row:
                return None
            if int(row["expires_at"]) < now:
                conn.execute("DELETE FROM sessions WHERE token=?;", (token,))
                return None
            user = AuthUser(email=str(row["email"]), role=str(row["role"]), display_name=str(row["display_name"] or ""))
            with self._session_cache_lock:
                self._session_cache[token] = (now_time + 5.0, user)
            return user

    def list_users(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, email, role, disabled, created_at, display_name FROM users ORDER BY created_at ASC;"
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "email": str(row["email"]),
                "role": str(row["role"]),
                "disabled": bool(int(row["disabled"] or 0)),
                "created_at": int(row["created_at"]),
                "display_name": str(row["display_name"] or ""),
            }
            for row in rows
        ]

    def delete_user(self, email: str) -> None:
        email = email.strip().lower()
        with self._connect() as conn:
            conn.execute("DELETE FROM users WHERE email=?;", (email,))

    def update_user(
        self,
        email: str,
        *,
        role: Optional[str] = None,
        disabled: Optional[bool] = None,
        password: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> None:
        email = email.strip().lower()
        updates: list = []
        params: list = []
        if display_name is not None:
            updates.append("display_name=?")
            params.append(display_name.strip())
        if role is not None:
            if role not in {"admin", "developer", "viewer"}:
                raise ValueError("Invalid role")
            updates.append("role=?")
            params.append(role)
        if disabled is not None:
            updates.append("disabled=?")
            params.append(1 if disabled else 0)
        if password is not None:
            salt_hex, digest_hex = hash_password(password)
            updates.append("password_salt=?")
            params.append(salt_hex)
            updates.append("password_hash=?")
            params.append(digest_hex)
        if not updates:
            return
        params.append(email)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE email=?;",
                params,
            )

    def audit(self, actor_email: Optional[str], actor_role: Optional[str], action: str, detail: Dict[str, Any]) -> None:
        payload = json.dumps(detail or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_logs(timestamp, actor_email, actor_role, action, detail_json) VALUES(?,?,?,?,?);",
                (_utc_epoch(), actor_email, actor_role, action, payload),
            )

    def get_audit_logs(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, timestamp, actor_email, actor_role, action, detail_json FROM audit_logs ORDER BY timestamp DESC LIMIT ?;",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            detail = {}
            try:
                detail = json.loads(row["detail_json"] or "{}")
            except Exception:
                pass
            result.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "actor_email": row["actor_email"],
                "actor_role": row["actor_role"],
                "action": row["action"],
                "detail": detail,
            })
        return result

    def add_comment(self, comment_id: str, run_id: str, x_pct: float, y_pct: float, author: str, content: str) -> None:
        content = content[:5000]
        now = _utc_epoch()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO comments(id, run_id, x_pct, y_pct, author, content, created_at)
                VALUES(?,?,?,?,?,?,?);
                """,
                (comment_id, run_id, x_pct, y_pct, author.strip(), content.strip(), now),
            )

    def list_comments(self, run_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, run_id, x_pct, y_pct, author, content, created_at
                FROM comments
                WHERE run_id=?
                ORDER BY created_at ASC;
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "run_id": str(row["run_id"]),
                "x_pct": float(row["x_pct"]),
                "y_pct": float(row["y_pct"]),
                "author": str(row["author"]),
                "content": str(row["content"]),
                "created_at": int(row["created_at"]),
            }
            for row in rows
        ]

    def delete_comment(self, comment_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM comments WHERE id=?;", (comment_id,))

    # ── Bulk operations ───────────────────────────────────────────────────────

    def bulk_insert_runs(self, runs_list: list[dict]) -> int:
        """Insert or replace multiple run index records in a single transaction.

        Uses :meth:`sqlite3.Connection.executemany` for batch efficiency and wraps
        the entire operation in a single explicit transaction so that either all
        rows succeed or none do.

        Duplicate ``run_id`` values are handled with ``INSERT OR REPLACE`` (upsert),
        which is equivalent to DELETE + INSERT at the SQLite level.

        Args:
            runs_list: Sequence of dicts, each with the same keys accepted by
                       :meth:`upsert_run_index` (``run_id`` / ``run``, ``case_name``,
                       ``baseline_name``, ``suite_name``, ``status``, ``mismatch_pct``,
                       ``diff_regions``, ``decision_status``, ``decided_at``,
                       ``severity``, ``ai_label``, ``browser``, ``device``,
                       ``locale``, ``url``, ``report_href``).

        Returns:
            The number of rows written (inserted or replaced).

        Raises:
            sqlite3.Error: If the transaction fails; the error is propagated after
                           an automatic rollback.
        """
        if not runs_list:
            return 0

        now = _utc_epoch()

        def _row(item: dict) -> tuple:
            run_id = str(item.get("run") or item.get("run_id") or "").strip()
            severity = item.get("severity") or {}
            severity_label = ""
            if isinstance(severity, dict):
                severity_label = str(severity.get("label") or "")
            
            decision = item.get("decision") or {}
            decider = decision.get("reviewer") or decision.get("decider") or item.get("decider") or ""
            decision_comment = decision.get("comment") or item.get("decision_comment") or ""
            decision_status = decision.get("status") or item.get("decision_status") or "pending"
            decided_at = decision.get("timestamp") or item.get("decided_at") or ""

            ai_assessment = item.get("ai_assessment") or {}
            ai_score = ai_assessment.get("score") if "score" in ai_assessment else item.get("ai_score")
            if ai_score is not None:
                ai_score = float(ai_score)

            return (
                run_id,
                item.get("case_name") or item.get("name"),
                item.get("baseline_name"),
                item.get("suite_name"),
                item.get("status"),
                item.get("mismatch_pct") or item.get("mismatch") or 0.0,
                item.get("diff_regions") or 0,
                decision_status,
                decided_at,
                severity_label,
                item.get("ai_label"),
                item.get("browser"),
                item.get("device"),
                item.get("locale"),
                item.get("url"),
                item.get("report_href"),
                decider,
                decision_comment,
                ai_score,
                item.get("build_id"),
                now,
            )

        rows = [_row(item) for item in runs_list if str(item.get("run") or item.get("run_id") or "").strip()]
        if not rows:
            return 0

        sql = """
            INSERT OR REPLACE INTO runs_index(
              run_id, case_name, baseline_name, suite_name, status, mismatch_pct,
              diff_regions, decision_status, decided_at, severity_label, ai_label,
              browser, device, locale, url, report_href, decider, decision_comment, ai_score, build_id, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
        """

        conn = self._connect()
        try:
            conn.execute("BEGIN")
            conn.executemany(sql, rows)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return len(rows)

