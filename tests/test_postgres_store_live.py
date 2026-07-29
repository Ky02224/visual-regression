"""Exercises PostgresStore against a *real* PostgreSQL server (not the mocked
psycopg2 used by test_postgres_store.py) and cross-checks behavior parity
against SqliteStore for the same sequence of operations.

Requires a reachable Postgres instance. Configure via env vars:
  LENS_TEST_PG_DSN   full DSN, e.g. postgresql://postgres:pw@127.0.0.1:5432/lens_test
Falls back to postgresql://postgres:kiayen@127.0.0.1:5432/lens_test (this
dev machine's local install) if unset. Skips the whole module if psycopg2
isn't installed or the server isn't reachable — this is an opt-in local
integration test, not part of the default CI matrix (no Postgres service
is provisioned there).
"""
import os

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2-binary not installed")

from visual_regression.postgres_store import PostgresStore  # noqa: E402
from visual_regression.sqlite_store import SqliteStore  # noqa: E402

TEST_DSN = os.environ.get("LENS_TEST_PG_DSN", "postgresql://postgres:kiayen@127.0.0.1:5432/lens_test")


def _server_reachable(dsn: str) -> bool:
    try:
        conn = psycopg2.connect(dsn, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _server_reachable(TEST_DSN), reason=f"No reachable Postgres at {TEST_DSN!r}"
)


def _wipe(dsn: str) -> None:
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    for table in ("comments", "audit_logs", "sessions", "users", "runs_index", "baselines_index"):
        cur.execute(
            "SELECT to_regclass(%s);", (table,)
        )
        if cur.fetchone()[0] is not None:
            cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE;")
    cur.close()
    conn.close()


@pytest.fixture
def pg_store():
    # Instantiating first runs _init_db()'s CREATE TABLE IF NOT EXISTS, so the
    # schema is guaranteed to exist before we truncate it clean for the test.
    store = PostgresStore(TEST_DSN)
    _wipe(TEST_DSN)
    yield store
    _wipe(TEST_DSN)


@pytest.fixture
def sqlite_store(tmp_path):
    return SqliteStore(tmp_path / "parity.db")


def test_bootstrap_users_created_on_real_server(pg_store, monkeypatch):
    monkeypatch.setenv("LENS_ADMIN_PASSWORD", "Xk9#mQ2$vLp8@nR4")
    monkeypatch.setenv("LENS_DEVELOPER_PASSWORD", "Zt7&hW3!cYq6#fB1")
    pg_store.ensure_bootstrap_users()

    users = {u["email"]: u["role"] for u in pg_store.list_users()}
    assert users.get("admin") == "admin"
    assert users.get("user") == "developer"

    assert pg_store.authenticate("admin", "Xk9#mQ2$vLp8@nR4") is not None
    assert pg_store.authenticate("admin", "wrong-password") is None


def test_user_and_session_lifecycle_parity(pg_store, sqlite_store):
    for store in (pg_store, sqlite_store):
        store.create_user("kiayen@example.com", "S3cure!Pass123", "developer", display_name="Kia Yen")

        user = store.authenticate("kiayen@example.com", "S3cure!Pass123")
        assert user is not None
        assert user.role == "developer"
        assert user.display_name == "Kia Yen"

        assert store.authenticate("kiayen@example.com", "bad-password") is None

        token = store.create_session("kiayen@example.com", ttl_seconds=3600)
        assert len(token) > 20

        session_user = store.user_for_session(token)
        assert session_user is not None
        assert session_user.email == "kiayen@example.com"

        store.delete_session(token)
        assert store.user_for_session(token) is None

        emails = {u["email"] for u in store.list_users()}
        assert "kiayen@example.com" in emails

        store.update_user("kiayen@example.com", role="admin")
        assert store.authenticate("kiayen@example.com", "S3cure!Pass123").role == "admin"

        store.delete_user("kiayen@example.com")
        assert store.authenticate("kiayen@example.com", "S3cure!Pass123") is None


def test_create_user_rejects_invalid_role_parity(pg_store, sqlite_store):
    for store in (pg_store, sqlite_store):
        with pytest.raises(ValueError):
            store.create_user("bad@example.com", "password123", "superadmin")


def test_comments_lifecycle_parity(pg_store, sqlite_store):
    for store in (pg_store, sqlite_store):
        # comments.run_id has a real FK to runs_index(run_id), enforced by both
        # backends (SQLite via PRAGMA foreign_keys=ON) — seed the parent row first.
        store.upsert_run_index({"run": "run-001", "case_name": "demo-home", "status": "PASS"})
        store.add_comment("c1", "run-001", 12.5, 40.0, "kiayen@example.com", "Looks off here")
        store.add_comment("c2", "run-001", 60.0, 10.0, "kiayen@example.com", "Second note")

        comments = store.list_comments("run-001")
        assert len(comments) == 2
        assert {c["id"] for c in comments} == {"c1", "c2"}
        assert comments[0]["content"] in ("Looks off here", "Second note")

        store.delete_comment("c1")
        remaining = store.list_comments("run-001")
        assert len(remaining) == 1
        assert remaining[0]["id"] == "c2"


def test_audit_log_parity(pg_store, sqlite_store):
    for store in (pg_store, sqlite_store):
        store.audit("admin@example.com", "admin", "user.create", {"target": "kiayen@example.com"})
        store.audit("admin@example.com", "admin", "user.delete", {"target": "someone@example.com"})

        logs = store.get_audit_logs(limit=10)
        assert len(logs) == 2
        actions = {log["action"] for log in logs}
        assert actions == {"user.create", "user.delete"}


def test_bulk_insert_runs_and_upsert_indexes_on_real_server(pg_store):
    runs = [
        {"run": "run-100", "case_name": "demo-home", "status": "PASS", "mismatch_pct": 0.1},
        {"run": "run-101", "case_name": "demo-login", "status": "FAIL", "mismatch_pct": 4.2},
        {"case_name": "no-run-id-should-be-skipped"},
    ]
    inserted = pg_store.bulk_insert_runs(runs)
    assert inserted == 2

    pg_store.upsert_baseline_index({
        "name": "demo-home", "url": "http://example.com", "browser": "chromium",
        "device": "Desktop", "locale": "en-US", "viewport": (1280, 720),
        "created_at": 1000, "updated_at": 1000, "version_count": 1,
    })
    pg_store.upsert_run_index({
        "run": "run-100", "case_name": "demo-home", "status": "PASS",
        "mismatch_pct": 0.1, "decision": {"status": "approved"},
    })

    # Re-upsert with changed values to verify ON CONFLICT UPDATE path works
    # against the real server (this is exactly the path that's easy to get
    # wrong translating SQLite's `ON CONFLICT DO UPDATE` to Postgres syntax).
    pg_store.upsert_run_index({
        "run": "run-100", "case_name": "demo-home", "status": "FAIL",
        "mismatch_pct": 9.9, "decision": {"status": "rejected"},
    })
