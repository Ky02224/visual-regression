from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

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
            conn = sqlite3.connect(db_path_str, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            _thread_local.conn = conn
            _thread_local.db_path = db_path_str
        return conn


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
            except Exception:
                pass
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
                  created_at INTEGER NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_case ON runs_index(case_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_suite ON runs_index(suite_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs_index(status);")

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
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs_index(
                  run_id, case_name, baseline_name, suite_name, status, mismatch_pct, diff_regions,
                  decision_status, decided_at, severity_label, ai_label, browser, device, locale, url, report_href,
                  created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                  report_href=excluded.report_href;
                """,
                (
                    run_id,
                    item.get("case_name"),
                    item.get("baseline_name"),
                    item.get("suite_name"),
                    item.get("status"),
                    item.get("mismatch_pct"),
                    item.get("diff_regions"),
                    item.get("decision_status"),
                    item.get("decided_at"),
                    severity_label,
                    item.get("ai_label"),
                    item.get("browser"),
                    item.get("device"),
                    item.get("locale"),
                    item.get("url"),
                    item.get("report_href"),
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
            conn.execute(
                "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES(?,?,?,?);",
                (token, user_id, now, expires_at),
            )
            conn.execute("DELETE FROM sessions WHERE expires_at < ?;", (now,))
        return token

    def delete_session(self, token: str) -> None:
        token = (token or "").strip()
        if not token:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token=?;", (token,))

    def user_for_session(self, token: str) -> Optional[AuthUser]:
        token = (token or "").strip()
        if not token:
            return None
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
            return AuthUser(email=str(row["email"]), role=str(row["role"]), display_name=str(row["display_name"] or ""))

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
                detail = json.loads(row[5] or "{}")
            except Exception:
                pass
            result.append({
                "id": row[0],
                "timestamp": row[1],
                "actor_email": row[2],
                "actor_role": row[3],
                "action": row[4],
                "detail": detail,
            })
        return result

