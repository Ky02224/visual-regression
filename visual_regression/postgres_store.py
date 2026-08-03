from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Any, Dict, List, Optional

# Import helper functions from sqlite_store to avoid duplication
from .sqlite_store import hash_password, verify_password, AuthUser, _utc_epoch

logger = logging.getLogger(__name__)

class PostgresStore:
    def __init__(self, db_url: str):
        self.db_url = db_url
        # Lazy load psycopg2 so SQLite users do not need it installed
        global psycopg2
        import psycopg2
        from psycopg2.extras import RealDictCursor
        self._RealDictCursor = RealDictCursor
        
        # ThreadedConnectionPool for safe multi-threaded connection sharing
        from psycopg2.pool import ThreadedConnectionPool
        
        # Parse connection URL to clean options if needed
        self.pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=40,
            dsn=db_url
        )
        import threading
        self._session_cache = {}  # {token: (expiry_time, AuthUser)}
        self._session_cache_lock = threading.Lock()
        threading.Thread(target=self._cleanup_expired_loop, daemon=True).start()
        self._init_db()

    def _cleanup_expired_loop(self) -> None:
        while True:
            try:
                now = _utc_epoch()
                self._execute_query("DELETE FROM sessions WHERE expires_at < %s;", (now,), commit=True)
            except Exception:
                logger.debug("Session cleanup pass failed; will retry next cycle", exc_info=True)
            time.sleep(3600)

    def _connect(self):
        """Get a connection from the pool."""
        return self.pool.getconn()

    def _release(self, conn) -> None:
        """Release a connection back to the pool."""
        self.pool.putconn(conn)

    def _execute_query(self, query: str, params: tuple | list | dict = (), commit: bool = False, fetch: bool = False) -> List[Dict[str, Any]]:
        conn = self._connect()
        # Use RealDictCursor to mirror sqlite3.Row dict-like behavior
        cursor = conn.cursor(cursor_factory=self._RealDictCursor)
        try:
            cursor.execute(query, params)
            if commit:
                conn.commit()
            if fetch:
                try:
                    return [dict(row) for row in cursor.fetchall()]
                except psycopg2.ProgrammingError:
                    return []
            return []
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            self._release(conn)

    def _init_db(self) -> None:
        # Create users table
        self._execute_query(
            """
            CREATE TABLE IF NOT EXISTS users (
              id SERIAL PRIMARY KEY,
              email VARCHAR(255) NOT NULL UNIQUE,
              role VARCHAR(50) NOT NULL,
              password_salt VARCHAR(255) NOT NULL,
              password_hash VARCHAR(255) NOT NULL,
              disabled INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              display_name VARCHAR(255) NOT NULL DEFAULT ''
            );
            """,
            commit=True
        )

        # Create sessions table
        self._execute_query(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              token VARCHAR(255) PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL
            );
            """,
            commit=True
        )
        self._execute_query("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);", commit=True)

        # Create audit logs
        self._execute_query(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
              id SERIAL PRIMARY KEY,
              timestamp INTEGER NOT NULL,
              actor_email VARCHAR(255),
              actor_role VARCHAR(50),
              action VARCHAR(100) NOT NULL,
              detail_json TEXT NOT NULL
            );
            """,
            commit=True
        )

        # Create baselines index
        self._execute_query(
            """
            CREATE TABLE IF NOT EXISTS baselines_index (
              name VARCHAR(255) PRIMARY KEY,
              url TEXT,
              browser VARCHAR(100),
              device VARCHAR(100),
              locale VARCHAR(100),
              timezone_id VARCHAR(100),
              viewport VARCHAR(100),
              created_at VARCHAR(100),
              updated_at VARCHAR(100),
              version_count INTEGER NOT NULL DEFAULT 0
            );
            """,
            commit=True
        )

        # Create runs index
        self._execute_query(
            """
            CREATE TABLE IF NOT EXISTS runs_index (
              run_id VARCHAR(255) PRIMARY KEY,
              case_name VARCHAR(255),
              baseline_name VARCHAR(255),
              suite_name VARCHAR(255),
              status VARCHAR(50),
              mismatch_pct REAL,
              diff_regions INTEGER,
              decision_status VARCHAR(50),
              decided_at VARCHAR(100),
              severity_label VARCHAR(100),
              ai_label VARCHAR(100),
              browser VARCHAR(100),
              device VARCHAR(100),
              locale VARCHAR(100),
              url TEXT,
              report_href TEXT,
              decider VARCHAR(255),
              decision_comment TEXT,
              ai_score REAL,
              build_id VARCHAR(255),
              created_at INTEGER NOT NULL
            );
            """,
            commit=True
        )
        # These four columns were added after the table shipped, so an existing
        # database needs them backfilled. This used to be four ALTER statements
        # each wrapped in `except Exception: pass` to absorb "column already
        # exists" — which also absorbed a dropped connection or a permissions
        # error, leaving the table silently missing columns that later queries
        # then reference. Postgres has supported IF NOT EXISTS here since 9.6,
        # so the intent is expressed directly and real failures now surface.
        for column_ddl in (
            "decider VARCHAR(255)",
            "decision_comment TEXT",
            "ai_score REAL",
            "build_id VARCHAR(255)",
        ):
            self._execute_query(
                f"ALTER TABLE runs_index ADD COLUMN IF NOT EXISTS {column_ddl};", commit=True
            )
        self._execute_query("CREATE INDEX IF NOT EXISTS idx_runs_case ON runs_index(case_name);", commit=True)
        self._execute_query("CREATE INDEX IF NOT EXISTS idx_runs_suite ON runs_index(suite_name);", commit=True)
        self._execute_query("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs_index(status);", commit=True)
        self._execute_query("CREATE INDEX IF NOT EXISTS idx_runs_build ON runs_index(build_id);", commit=True)

        # Create comments table
        self._execute_query(
            """
            CREATE TABLE IF NOT EXISTS comments (
              id VARCHAR(255) PRIMARY KEY,
              run_id VARCHAR(255) NOT NULL REFERENCES runs_index(run_id) ON DELETE CASCADE,
              x_pct REAL NOT NULL,
              y_pct REAL NOT NULL,
              author VARCHAR(255) NOT NULL,
              content TEXT NOT NULL,
              created_at INTEGER NOT NULL
            );
            """,
            commit=True
        )
        self._execute_query("CREATE INDEX IF NOT EXISTS idx_comments_run ON comments(run_id);", commit=True)

        # ── Performance indexes added for Storage & Database optimisation ──────
        # Supports ORDER BY created_at DESC in run history / dashboard queries.
        self._execute_query(
            "CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs_index(created_at DESC);",
            commit=True,
        )
        # Fast equality / prefix lookup of baselines by name.
        self._execute_query(
            "CREATE INDEX IF NOT EXISTS idx_baselines_name ON baselines_index(name);",
            commit=True,
        )
        # Composite covering index: baseline_name + created_at for
        # 'show all runs for baseline X sorted by date' queries.
        self._execute_query(
            "CREATE INDEX IF NOT EXISTS idx_runs_baseline_created "
            "ON runs_index(baseline_name, created_at DESC);",
            commit=True,
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

        self._execute_query(
            """
            INSERT INTO baselines_index(
              name, url, browser, device, locale, timezone_id, viewport, created_at, updated_at, version_count
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(name) DO UPDATE SET
              url=EXCLUDED.url,
              browser=EXCLUDED.browser,
              device=EXCLUDED.device,
              locale=EXCLUDED.locale,
              timezone_id=EXCLUDED.timezone_id,
              viewport=EXCLUDED.viewport,
              created_at=EXCLUDED.created_at,
              updated_at=EXCLUDED.updated_at,
              version_count=EXCLUDED.version_count;
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
            commit=True
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

        self._execute_query(
            """
            INSERT INTO runs_index(
              run_id, case_name, baseline_name, suite_name, status, mismatch_pct, diff_regions,
              decision_status, decided_at, severity_label, ai_label, browser, device, locale, url, report_href,
              decider, decision_comment, ai_score, build_id, created_at
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(run_id) DO UPDATE SET
              case_name=EXCLUDED.case_name,
              baseline_name=EXCLUDED.baseline_name,
              suite_name=EXCLUDED.suite_name,
              status=EXCLUDED.status,
              mismatch_pct=EXCLUDED.mismatch_pct,
              diff_regions=EXCLUDED.diff_regions,
              decision_status=EXCLUDED.decision_status,
              decided_at=EXCLUDED.decided_at,
              severity_label=EXCLUDED.severity_label,
              ai_label=EXCLUDED.ai_label,
              browser=EXCLUDED.browser,
              device=EXCLUDED.device,
              locale=EXCLUDED.locale,
              url=EXCLUDED.url,
              report_href=EXCLUDED.report_href,
              decider=EXCLUDED.decider,
              decision_comment=EXCLUDED.decision_comment,
              ai_score=EXCLUDED.ai_score,
              build_id=EXCLUDED.build_id;
            """,
            (
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
            ),
            commit=True
        )

    def bulk_insert_runs(self, runs_list: list[dict]) -> int:
        """Insert or replace multiple run index records in PostgreSQL in a batch."""
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
                now,
            )

        rows = [_row(item) for item in runs_list if str(item.get("run") or item.get("run_id") or "").strip()]
        if not rows:
            return 0

        sql = """
            INSERT INTO runs_index(
              run_id, case_name, baseline_name, suite_name, status, mismatch_pct, diff_regions,
              decision_status, decided_at, severity_label, ai_label, browser, device, locale, url, report_href,
              decider, decision_comment, ai_score, created_at
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(run_id) DO UPDATE SET
              case_name=EXCLUDED.case_name,
              baseline_name=EXCLUDED.baseline_name,
              suite_name=EXCLUDED.suite_name,
              status=EXCLUDED.status,
              mismatch_pct=EXCLUDED.mismatch_pct,
              diff_regions=EXCLUDED.diff_regions,
              decision_status=EXCLUDED.decision_status,
              decided_at=EXCLUDED.decided_at,
              severity_label=EXCLUDED.severity_label,
              ai_label=EXCLUDED.ai_label,
              browser=EXCLUDED.browser,
              device=EXCLUDED.device,
              locale=EXCLUDED.locale,
              url=EXCLUDED.url,
              report_href=EXCLUDED.report_href,
              decider=EXCLUDED.decider,
              decision_comment=EXCLUDED.decision_comment,
              ai_score=EXCLUDED.ai_score;
        """

        conn = self._connect()
        cursor = conn.cursor()
        try:
            import psycopg2.extras
            psycopg2.extras.execute_batch(cursor, sql, rows)
            conn.commit()
            return len(rows)
        except Exception as e:
            conn.rollback()
            print(f"[PostgresStore] bulk_insert_runs failed: {e}", flush=True)
            raise e
        finally:
            cursor.close()
            self._release(conn)

    def ensure_bootstrap_users(self) -> None:
        admin_email = os.environ.get("LENS_ADMIN_EMAIL", "admin")
        admin_password = os.environ.get("LENS_ADMIN_PASSWORD", "admin1234")
        dev_email = os.environ.get("LENS_DEVELOPER_EMAIL", "user")
        dev_password = os.environ.get("LENS_DEVELOPER_PASSWORD", "user1234")

        # Warn loudly when factory-default credentials are in use
        import sys
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
            self._execute_query(
                """
                INSERT INTO users(email, role, password_salt, password_hash, disabled, created_at)
                VALUES(%s,%s,%s,%s,0,%s)
                ON CONFLICT(email) DO NOTHING;
                """,
                (email, role, salt_hex, digest_hex, now),
                commit=True
            )
        self.audit(None, None, "bootstrap.users", {"admin": admin_email, "user": dev_email})

    def create_user(self, email: str, password: str, role: str, display_name: str = "") -> None:
        email = email.strip().lower()
        if role not in {"admin", "developer", "viewer"}:
            raise ValueError("Invalid role")
        salt_hex, digest_hex = hash_password(password)
        now = _utc_epoch()
        self._execute_query(
            "INSERT INTO users(email, role, password_salt, password_hash, disabled, created_at, display_name) VALUES(%s,%s,%s,%s,0,%s,%s);",
            (email, role, salt_hex, digest_hex, now, display_name.strip()),
            commit=True
        )

    def authenticate(self, email: str, password: str) -> Optional[AuthUser]:
        email = email.strip().lower()
        rows = self._execute_query(
            "SELECT email, role, password_salt, password_hash, disabled, display_name FROM users WHERE email=%s;",
            (email,),
            fetch=True
        )
        if not rows:
            return None
        row = rows[0]
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
        
        rows = self._execute_query("SELECT id FROM users WHERE email=%s;", (email,), fetch=True)
        if not rows:
            raise FileNotFoundError("user not found")
        user_id = int(rows[0]["id"])
        
        # Limit to max 5 concurrent sessions per user (LRU eviction)
        sessions = self._execute_query("SELECT token FROM sessions WHERE user_id=%s ORDER BY created_at ASC;", (user_id,), fetch=True)
        if len(sessions) >= 5:
            oldest_token = sessions[0]["token"]
            self._execute_query("DELETE FROM sessions WHERE token=%s;", (oldest_token,), commit=True)
            with self._session_cache_lock:
                if oldest_token in self._session_cache:
                    del self._session_cache[oldest_token]

        self._execute_query(
            "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES(%s,%s,%s,%s);",
            (token, user_id, now, expires_at),
            commit=True
        )
        return token

    def delete_session(self, token: str) -> None:
        token = (token or "").strip()
        if not token:
            return
        with self._session_cache_lock:
            if token in self._session_cache:
                del self._session_cache[token]
        self._execute_query("DELETE FROM sessions WHERE token=%s;", (token,), commit=True)

    def user_for_session(self, token: str) -> Optional[AuthUser]:
        token = (token or "").strip()
        if not token:
            return None
        now_time = time.time()
        with self._session_cache_lock:
            if token in self._session_cache:
                expiry, user = self._session_cache[token]
                if now_time < expiry:
                    return user
                else:
                    del self._session_cache[token]

        now = _utc_epoch()
        rows = self._execute_query(
            """
            SELECT u.email AS email, u.role AS role, u.display_name AS display_name, s.expires_at AS expires_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = %s;
            """,
            (token,),
            fetch=True
        )
        if not rows:
            return None
        row = rows[0]
        if int(row["expires_at"]) < now:
            self._execute_query("DELETE FROM sessions WHERE token=%s;", (token,), commit=True)
            return None
        user = AuthUser(email=str(row["email"]), role=str(row["role"]), display_name=str(row["display_name"] or ""))
        with self._session_cache_lock:
            self._session_cache[token] = (now_time + 5.0, user)
        return user

    def list_users(self) -> list:
        rows = self._execute_query(
            "SELECT id, email, role, disabled, created_at, display_name FROM users ORDER BY created_at ASC;",
            fetch=True
        )
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
        self._execute_query("DELETE FROM users WHERE email=%s;", (email,), commit=True)

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
            updates.append("display_name=%s")
            params.append(display_name.strip())
        if role is not None:
            if role not in {"admin", "developer", "viewer"}:
                raise ValueError("Invalid role")
            updates.append("role=%s")
            params.append(role)
        if disabled is not None:
            updates.append("disabled=%s")
            params.append(1 if disabled else 0)
        if password is not None:
            salt_hex, digest_hex = hash_password(password)
            updates.append("password_salt=%s")
            params.append(salt_hex)
            updates.append("password_hash=%s")
            params.append(digest_hex)
        if not updates:
            return
        params.append(email)
        self._execute_query(
            f"UPDATE users SET {', '.join(updates)} WHERE email=%s;",
            params,
            commit=True
        )

    def audit(self, actor_email: Optional[str], actor_role: Optional[str], action: str, detail: Dict[str, Any]) -> None:
        payload = json.dumps(detail or {}, ensure_ascii=False)
        self._execute_query(
            "INSERT INTO audit_logs(timestamp, actor_email, actor_role, action, detail_json) VALUES(%s,%s,%s,%s,%s);",
            (_utc_epoch(), actor_email, actor_role, action, payload),
            commit=True
        )

    def get_audit_logs(self, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self._execute_query(
            "SELECT id, timestamp, actor_email, actor_role, action, detail_json FROM audit_logs ORDER BY timestamp DESC LIMIT %s;",
            (limit,),
            fetch=True
        )
        result = []
        for row in rows:
            detail = {}
            try:
                detail = json.loads(row["detail_json"] or "{}")
            except Exception as exc:
                # See SqliteStore.get_audit_logs: an unparseable detail must not
                # be silently indistinguishable from an empty one.
                logger.warning(
                    "Audit log row %s has unparseable detail_json (%s: %s); reporting it as empty.",
                    row["id"], type(exc).__name__, exc,
                )
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
        self._execute_query(
            """
            INSERT INTO comments(id, run_id, x_pct, y_pct, author, content, created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s);
            """,
            (comment_id, run_id, x_pct, y_pct, author.strip(), content.strip(), now),
            commit=True
        )

    def list_comments(self, run_id: str) -> List[Dict[str, Any]]:
        rows = self._execute_query(
            """
            SELECT id, run_id, x_pct, y_pct, author, content, created_at
            FROM comments
            WHERE run_id=%s
            ORDER BY created_at ASC;
            """,
            (run_id,),
            fetch=True
        )
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

    def get_comment(self, comment_id: str) -> Optional[Dict[str, Any]]:
        """Return one comment, or None. Mirrors SqliteStore.get_comment."""
        rows = self._execute_query(
            """
            SELECT id, run_id, x_pct, y_pct, author, content, created_at
            FROM comments WHERE id=%s;
            """,
            (comment_id,),
            fetch=True,
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "id": str(row["id"]),
            "run_id": str(row["run_id"]),
            "x_pct": float(row["x_pct"]),
            "y_pct": float(row["y_pct"]),
            "author": str(row["author"]),
            "content": str(row["content"]),
            "created_at": int(row["created_at"]),
        }

    def delete_comment(self, comment_id: str) -> None:
        self._execute_query("DELETE FROM comments WHERE id=%s;", (comment_id,), commit=True)
