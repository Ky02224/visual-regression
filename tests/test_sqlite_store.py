"""Tests for sqlite_store.py — the default (and only always-available) database
backend. Unlike test_postgres_store.py (which mocks psycopg2), these tests run
against a *real* SQLite database in a temp file per test, exercising actual SQL
execution, schema creation, constraints (UNIQUE, FOREIGN KEY), and the
thread-local connection / WAL concurrency handling the module implements.

Never touches the repo's real storage.db — every test gets its own tmp_path
database file.
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

import visual_regression.sqlite_store as sqlite_store_module
from visual_regression.sqlite_store import (
    AuthUser,
    SqliteStore,
    hash_password,
    verify_password,
    _pbkdf2_hash,
    _PBKDF2_LEGACY_ITERATIONS,
)


@pytest.fixture
def store(tmp_path):
    return SqliteStore(tmp_path / "store.db")


# ── Password hashing helpers ────────────────────────────────────────────────


def test_hash_and_verify_password_roundtrip():
    salt_hex, digest_hex = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", salt_hex, digest_hex) is True


def test_verify_password_rejects_wrong_password():
    salt_hex, digest_hex = hash_password("right-password")
    assert verify_password("wrong-password", salt_hex, digest_hex) is False


def test_verify_password_accepts_legacy_iteration_count():
    # Passwords hashed before the PBKDF2 iteration upgrade should still verify.
    import secrets

    salt = secrets.token_bytes(16)
    legacy_digest = _pbkdf2_hash("old-password", salt, _PBKDF2_LEGACY_ITERATIONS)
    assert verify_password("old-password", salt.hex(), legacy_digest.hex()) is True


def test_verify_password_handles_malformed_hex_gracefully():
    assert verify_password("anything", "not-hex!!", "also-not-hex") is False


# ── Schema / initialization ─────────────────────────────────────────────────


def test_init_db_creates_expected_tables(store):
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        ).fetchall()
    table_names = {row["name"] for row in rows}
    assert {"users", "sessions", "audit_logs", "baselines_index", "runs_index", "comments"} <= table_names


def test_init_db_creates_expected_indexes(store):
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name;"
        ).fetchall()
    index_names = {row["name"] for row in rows}
    assert "idx_runs_case" in index_names
    assert "idx_runs_build" in index_names
    assert "idx_runs_baseline_created" in index_names
    assert "idx_comments_run" in index_names


def test_init_db_is_idempotent_on_reopen(tmp_path):
    db_path = tmp_path / "reopen.db"
    store1 = SqliteStore(db_path)
    store1.create_user("someone@example.com", "password123", "developer")

    # Re-opening the same file re-runs _init_db()'s CREATE TABLE IF NOT EXISTS /
    # ALTER TABLE-with-ignore-duplicate-column logic; it must not raise or wipe data.
    store2 = SqliteStore(db_path)
    users = store2.list_users()
    assert len(users) == 1
    assert users[0]["email"] == "someone@example.com"


def test_constructor_creates_missing_parent_directories(tmp_path):
    nested = tmp_path / "a" / "b" / "c" / "store.db"
    assert not nested.parent.exists()
    SqliteStore(nested)
    assert nested.exists()


# ── Users: CRUD ──────────────────────────────────────────────────────────────


def test_create_user_and_authenticate(store):
    store.create_user("kiayen@example.com", "S3cure!Pass123", "developer", display_name="Kia Yen")

    user = store.authenticate("kiayen@example.com", "S3cure!Pass123")
    assert user is not None
    assert isinstance(user, AuthUser)
    assert user.email == "kiayen@example.com"
    assert user.role == "developer"
    assert user.display_name == "Kia Yen"


def test_authenticate_wrong_password_returns_none(store):
    store.create_user("kiayen@example.com", "S3cure!Pass123", "developer")
    assert store.authenticate("kiayen@example.com", "wrong-password") is None


def test_authenticate_nonexistent_user_returns_none(store):
    assert store.authenticate("nobody@example.com", "whatever") is None


def test_authenticate_is_case_insensitive_and_trims_email(store):
    store.create_user("  Kiayen@Example.com  ", "S3cure!Pass123", "developer")
    user = store.authenticate("kiayen@example.com", "S3cure!Pass123")
    assert user is not None
    assert user.email == "kiayen@example.com"


def test_authenticate_disabled_user_returns_none(store):
    store.create_user("kiayen@example.com", "S3cure!Pass123", "developer")
    store.update_user("kiayen@example.com", disabled=True)
    assert store.authenticate("kiayen@example.com", "S3cure!Pass123") is None


def test_create_user_rejects_invalid_role(store):
    with pytest.raises(ValueError):
        store.create_user("bad@example.com", "password123", "superadmin")


def test_create_user_duplicate_email_raises(store):
    store.create_user("dup@example.com", "password123", "developer")
    with pytest.raises(sqlite3.IntegrityError):
        store.create_user("dup@example.com", "password456", "viewer")


def test_list_users_empty_database_returns_empty_list(store):
    assert store.list_users() == []


def test_list_users_returns_expected_fields_in_creation_order(store):
    store.create_user("a@example.com", "password123", "admin")
    store.create_user("b@example.com", "password123", "viewer")

    users = store.list_users()
    assert [u["email"] for u in users] == ["a@example.com", "b@example.com"]
    assert users[0]["role"] == "admin"
    assert users[0]["disabled"] is False
    assert isinstance(users[0]["created_at"], int)


def test_delete_user(store):
    store.create_user("kiayen@example.com", "S3cure!Pass123", "developer")
    store.delete_user("kiayen@example.com")
    assert store.authenticate("kiayen@example.com", "S3cure!Pass123") is None
    assert store.list_users() == []


def test_delete_nonexistent_user_does_not_raise(store):
    store.delete_user("ghost@example.com")


def test_update_user_role(store):
    store.create_user("kiayen@example.com", "S3cure!Pass123", "developer")
    store.update_user("kiayen@example.com", role="admin")
    assert store.authenticate("kiayen@example.com", "S3cure!Pass123").role == "admin"


def test_update_user_password(store):
    store.create_user("kiayen@example.com", "old-password123", "developer")
    store.update_user("kiayen@example.com", password="new-password456")
    assert store.authenticate("kiayen@example.com", "old-password123") is None
    assert store.authenticate("kiayen@example.com", "new-password456") is not None


def test_update_user_display_name(store):
    store.create_user("kiayen@example.com", "password123", "developer")
    store.update_user("kiayen@example.com", display_name="New Name")
    users = store.list_users()
    assert users[0]["display_name"] == "New Name"


def test_update_user_invalid_role_raises(store):
    store.create_user("kiayen@example.com", "password123", "developer")
    with pytest.raises(ValueError):
        store.update_user("kiayen@example.com", role="superadmin")


def test_update_user_with_no_fields_is_a_noop(store):
    store.create_user("kiayen@example.com", "password123", "developer")
    store.update_user("kiayen@example.com")  # no kwargs supplied
    user = store.authenticate("kiayen@example.com", "password123")
    assert user is not None
    assert user.role == "developer"


# ── Bootstrap users ──────────────────────────────────────────────────────────


def test_ensure_bootstrap_users_creates_admin_and_developer(store, monkeypatch):
    monkeypatch.setenv("LENS_ADMIN_PASSWORD", "Xk9#mQ2$vLp8@nR4")
    monkeypatch.setenv("LENS_DEVELOPER_PASSWORD", "Zt7&hW3!cYq6#fB1")
    store.ensure_bootstrap_users()

    users = {u["email"]: u["role"] for u in store.list_users()}
    assert users.get("admin") == "admin"
    assert users.get("user") == "developer"
    assert store.authenticate("admin", "Xk9#mQ2$vLp8@nR4") is not None


def test_ensure_bootstrap_users_is_idempotent_and_preserves_existing_password(store, monkeypatch):
    monkeypatch.setenv("LENS_ADMIN_PASSWORD", "Xk9#mQ2$vLp8@nR4")
    monkeypatch.setenv("LENS_DEVELOPER_PASSWORD", "Zt7&hW3!cYq6#fB1")
    store.ensure_bootstrap_users()

    # Change the admin's password manually, then re-run bootstrap: INSERT OR
    # IGNORE means the existing account/password must survive untouched.
    store.update_user("admin", password="manually-changed-pw-1")
    store.ensure_bootstrap_users()

    assert len(store.list_users()) == 2
    assert store.authenticate("admin", "manually-changed-pw-1") is not None
    assert store.authenticate("admin", "Xk9#mQ2$vLp8@nR4") is None


def test_ensure_bootstrap_users_warns_on_weak_defaults(store, monkeypatch, capsys):
    monkeypatch.delenv("LENS_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("LENS_DEVELOPER_PASSWORD", raising=False)

    store.ensure_bootstrap_users()

    captured = capsys.readouterr()
    assert "SECURITY WARNING" in captured.err


def test_ensure_bootstrap_users_no_warning_with_strong_passwords(store, monkeypatch, capsys):
    monkeypatch.setenv("LENS_ADMIN_PASSWORD", "Xk9#mQ2$vLp8@nR4")
    monkeypatch.setenv("LENS_DEVELOPER_PASSWORD", "Zt7&hW3!cYq6#fB1")

    store.ensure_bootstrap_users()

    captured = capsys.readouterr()
    assert "SECURITY WARNING" not in captured.err


# ── Sessions ─────────────────────────────────────────────────────────────────


def test_create_session_and_lookup(store):
    store.create_user("kiayen@example.com", "password123", "developer")
    token = store.create_session("kiayen@example.com", ttl_seconds=3600)
    assert len(token) > 20

    user = store.user_for_session(token)
    assert user is not None
    assert user.email == "kiayen@example.com"


def test_user_for_session_uses_cache_on_second_lookup(store):
    store.create_user("kiayen@example.com", "password123", "developer")
    token = store.create_session("kiayen@example.com", ttl_seconds=3600)

    first = store.user_for_session(token)
    # Delete the underlying row directly (bypassing delete_session, which also
    # clears the cache) to prove the second lookup is served from the
    # in-memory session cache rather than re-querying the DB.
    with store._connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token=?;", (token,))
    second = store.user_for_session(token)

    assert first is not None
    assert second is not None
    assert second.email == first.email


def test_user_for_session_unknown_token_returns_none(store):
    assert store.user_for_session("not-a-real-token") is None


def test_user_for_session_empty_token_returns_none(store):
    assert store.user_for_session("") is None


def test_delete_session_invalidates_immediately(store):
    store.create_user("kiayen@example.com", "password123", "developer")
    token = store.create_session("kiayen@example.com", ttl_seconds=3600)
    assert store.user_for_session(token) is not None

    store.delete_session(token)
    # delete_session evicts the cache entry too, so this must hit the DB and
    # find the row gone rather than returning a stale cached user.
    assert store.user_for_session(token) is None


def test_expired_session_is_rejected_and_purged(store):
    store.create_user("kiayen@example.com", "password123", "developer")
    token = store.create_session("kiayen@example.com", ttl_seconds=-10)  # already expired

    assert store.user_for_session(token) is None
    with store._connect() as conn:
        row = conn.execute("SELECT 1 FROM sessions WHERE token=?;", (token,)).fetchone()
    assert row is None  # user_for_session deletes expired rows as it finds them


def test_create_session_unknown_user_raises(store):
    with pytest.raises(FileNotFoundError):
        store.create_session("ghost@example.com")


def test_create_session_evicts_oldest_beyond_five_concurrent(store, monkeypatch):
    # created_at has 1-second granularity (int(time.time())); creating six
    # sessions in a tight loop could tie on the same second and make the
    # ASC-ordered "oldest" pick ambiguous. Monkeypatch the module's epoch
    # helper so each session gets a strictly increasing, deterministic
    # timestamp instead of relying on real wall-clock drift.
    fake_now = [1_700_000_000]

    def _next_epoch():
        fake_now[0] += 1
        return fake_now[0]

    monkeypatch.setattr(sqlite_store_module, "_utc_epoch", _next_epoch)

    store.create_user("kiayen@example.com", "password123", "developer")
    tokens = [store.create_session("kiayen@example.com", ttl_seconds=3600) for _ in range(6)]

    with store._connect() as conn:
        rows = conn.execute("SELECT token FROM sessions;").fetchall()
    remaining = {row["token"] for row in rows}

    assert len(remaining) == 5
    assert tokens[0] not in remaining  # oldest session was evicted
    assert tokens[-1] in remaining  # newest survives


# ── Audit logs ───────────────────────────────────────────────────────────────


def test_get_audit_logs_empty_database_returns_empty_list(store):
    assert store.get_audit_logs() == []


def test_audit_and_get_audit_logs(store):
    store.audit("admin@example.com", "admin", "user.create", {"target": "kiayen@example.com"})
    store.audit("admin@example.com", "admin", "user.delete", {"target": "someone@example.com"})

    logs = store.get_audit_logs(limit=10)
    assert len(logs) == 2
    actions = {log["action"] for log in logs}
    assert actions == {"user.create", "user.delete"}
    by_action = {log["action"]: log for log in logs}
    assert by_action["user.create"]["detail"] == {"target": "kiayen@example.com"}


def test_get_audit_logs_orders_newest_first(store, monkeypatch):
    # timestamp has 1-second (int(time.time())) granularity, so three inserts
    # in a tight loop can tie on the same second — force strictly increasing
    # timestamps so the DESC ordering assertion isn't a coin flip.
    fake_now = [1_700_000_000]

    def _next_epoch():
        fake_now[0] += 1
        return fake_now[0]

    monkeypatch.setattr(sqlite_store_module, "_utc_epoch", _next_epoch)

    for i in range(3):
        store.audit(None, None, f"action.{i}", {"i": i})
    logs = store.get_audit_logs()
    assert [log["action"] for log in logs] == ["action.2", "action.1", "action.0"]


def test_get_audit_logs_respects_limit(store):
    for i in range(5):
        store.audit(None, None, f"action.{i}", {})
    logs = store.get_audit_logs(limit=2)
    assert len(logs) == 2


# ── Comments (with FK to runs_index) ────────────────────────────────────────


def test_add_comment_without_parent_run_raises_foreign_key_error(store):
    with pytest.raises(sqlite3.IntegrityError):
        store.add_comment("c1", "no-such-run", 10.0, 20.0, "kiayen@example.com", "hello")


def test_add_and_list_comments(store):
    store.upsert_run_index({"run": "run-001", "case_name": "demo-home", "status": "PASS"})
    store.add_comment("c1", "run-001", 12.5, 40.0, "kiayen@example.com", "Looks off here")
    store.add_comment("c2", "run-001", 60.0, 10.0, "kiayen@example.com", "Second note")

    comments = store.list_comments("run-001")
    assert len(comments) == 2
    assert {c["id"] for c in comments} == {"c1", "c2"}
    assert comments[0]["created_at"] <= comments[1]["created_at"]  # ordered ASC by created_at


def test_list_comments_for_run_with_no_comments_returns_empty_list(store):
    store.upsert_run_index({"run": "run-001", "case_name": "demo-home", "status": "PASS"})
    assert store.list_comments("run-001") == []


def test_list_comments_for_nonexistent_run_returns_empty_list(store):
    assert store.list_comments("does-not-exist") == []


def test_delete_comment(store):
    store.upsert_run_index({"run": "run-001", "case_name": "demo-home", "status": "PASS"})
    store.add_comment("c1", "run-001", 12.5, 40.0, "kiayen@example.com", "note")
    store.delete_comment("c1")
    assert store.list_comments("run-001") == []


def test_comment_content_is_truncated_and_trimmed(store):
    store.upsert_run_index({"run": "run-001", "case_name": "demo-home", "status": "PASS"})
    long_content = "x" * 6000
    store.add_comment("c1", "run-001", 1.0, 1.0, "  kiayen@example.com  ", long_content)
    comments = store.list_comments("run-001")
    assert len(comments[0]["content"]) == 5000
    assert comments[0]["author"] == "kiayen@example.com"


# ── Baselines index (upsert) ────────────────────────────────────────────────


def test_upsert_baseline_index_insert_and_read_back(store):
    store.upsert_baseline_index({
        "name": "home",
        "url": "http://example.com",
        "browser": "chromium",
        "device": "Desktop",
        "locale": "en-US",
        "timezone_id": "UTC",
        "viewport": (1280, 720),
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "version_count": 1,
    })

    with store._connect() as conn:
        row = conn.execute("SELECT * FROM baselines_index WHERE name=?;", ("home",)).fetchone()
    assert row is not None
    assert row["viewport"] == "1280x720"
    assert row["version_count"] == 1


def test_upsert_baseline_index_updates_existing_row(store):
    store.upsert_baseline_index({"name": "home", "url": "http://old.example.com", "version_count": 1})
    store.upsert_baseline_index({"name": "home", "url": "http://new.example.com", "version_count": 2})

    with store._connect() as conn:
        rows = conn.execute("SELECT * FROM baselines_index WHERE name=?;", ("home",)).fetchall()
    assert len(rows) == 1
    assert rows[0]["url"] == "http://new.example.com"
    assert rows[0]["version_count"] == 2


def test_upsert_baseline_index_blank_name_is_noop(store):
    store.upsert_baseline_index({"name": "  ", "url": "http://example.com"})
    with store._connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM baselines_index;").fetchone()["c"]
    assert count == 0


def test_upsert_baseline_index_accepts_string_viewport(store):
    store.upsert_baseline_index({"name": "home", "viewport": "1920x1080"})
    with store._connect() as conn:
        row = conn.execute("SELECT viewport FROM baselines_index WHERE name=?;", ("home",)).fetchone()
    assert row["viewport"] == "1920x1080"


# ── Runs index (upsert) ──────────────────────────────────────────────────────


def test_upsert_run_index_insert_and_read_back(store):
    store.upsert_run_index({
        "run": "run-001",
        "case_name": "demo-home",
        "baseline_name": "home",
        "suite_name": "smoke",
        "status": "FAIL",
        "mismatch_pct": 3.2,
        "diff_regions": 2,
        "severity": {"label": "high"},
        "ai_label": "regression",
        "decision": {"status": "approved", "reviewer": "kiayen", "comment": "looks real", "timestamp": "2026-01-01"},
        "ai_assessment": {"score": 0.87},
        "build_id": "build-42",
    })

    with store._connect() as conn:
        row = conn.execute("SELECT * FROM runs_index WHERE run_id=?;", ("run-001",)).fetchone()
    assert row is not None
    assert row["case_name"] == "demo-home"
    assert row["status"] == "FAIL"
    assert row["mismatch_pct"] == 3.2
    assert row["severity_label"] == "high"
    assert row["decision_status"] == "approved"
    assert row["decider"] == "kiayen"
    assert row["decision_comment"] == "looks real"
    assert row["ai_score"] == 0.87
    assert row["build_id"] == "build-42"


def test_upsert_run_index_defaults_decision_status_to_pending(store):
    store.upsert_run_index({"run": "run-002", "case_name": "demo-login", "status": "PASS"})
    with store._connect() as conn:
        row = conn.execute("SELECT decision_status FROM runs_index WHERE run_id=?;", ("run-002",)).fetchone()
    assert row["decision_status"] == "pending"


def test_upsert_run_index_updates_existing_row_on_conflict(store):
    store.upsert_run_index({"run": "run-001", "case_name": "demo-home", "status": "PASS", "mismatch_pct": 0.1})
    store.upsert_run_index({"run": "run-001", "case_name": "demo-home", "status": "FAIL", "mismatch_pct": 9.9})

    with store._connect() as conn:
        rows = conn.execute("SELECT * FROM runs_index WHERE run_id=?;", ("run-001",)).fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "FAIL"
    assert rows[0]["mismatch_pct"] == 9.9


def test_upsert_run_index_blank_run_id_is_noop(store):
    store.upsert_run_index({"case_name": "no-id"})
    with store._connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM runs_index;").fetchone()["c"]
    assert count == 0


# ── Bulk insert ──────────────────────────────────────────────────────────────


def test_bulk_insert_runs_empty_list_returns_zero(store):
    assert store.bulk_insert_runs([]) == 0


def test_bulk_insert_runs_filters_rows_without_run_id(store):
    runs = [
        {"run": "run-100", "case_name": "demo-home", "status": "PASS", "mismatch_pct": 0.1},
        {"run": "run-101", "case_name": "demo-login", "status": "FAIL", "mismatch_pct": 4.2},
        {"case_name": "no-run-id-should-be-skipped"},
    ]
    inserted = store.bulk_insert_runs(runs)
    assert inserted == 2

    with store._connect() as conn:
        rows = conn.execute("SELECT run_id FROM runs_index ORDER BY run_id;").fetchall()
    assert [r["run_id"] for r in rows] == ["run-100", "run-101"]


def test_bulk_insert_runs_replaces_existing_row(store):
    store.upsert_run_index({"run": "run-100", "case_name": "demo-home", "status": "PASS"})
    store.bulk_insert_runs([{"run": "run-100", "case_name": "demo-home", "status": "FAIL", "mismatch_pct": 5.0}])

    with store._connect() as conn:
        rows = conn.execute("SELECT * FROM runs_index WHERE run_id=?;", ("run-100",)).fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "FAIL"


# ── _execute_query (used directly by dashboard_server.py / dashboard_data.py / ai_auto_ignore.py) ──


def test_execute_query_fetch_returns_list_of_dicts(store):
    store.create_user("kiayen@example.com", "password123", "developer")
    rows = store._execute_query("SELECT email, role FROM users WHERE email=?;", ("kiayen@example.com",), fetch=True)
    assert rows == [{"email": "kiayen@example.com", "role": "developer"}]


def test_execute_query_commit_persists_write(store):
    store._execute_query(
        "INSERT INTO audit_logs(timestamp, actor_email, actor_role, action, detail_json) VALUES(?,?,?,?,?);",
        (1000, "a@example.com", "admin", "manual.insert", "{}"),
        commit=True,
    )
    logs = store.get_audit_logs()
    assert len(logs) == 1
    assert logs[0]["action"] == "manual.insert"


def test_execute_query_no_fetch_returns_empty_list(store):
    result = store._execute_query("SELECT 1;")
    assert result == []


# ── Edge cases ───────────────────────────────────────────────────────────────


def test_queries_against_completely_empty_database(store):
    assert store.list_users() == []
    assert store.get_audit_logs() == []
    assert store.list_comments("anything") == []
    assert store.authenticate("nobody@example.com", "x") is None
    assert store.user_for_session("nope") is None


# ── Concurrency: thread-local connections + WAL/busy_timeout ───────────────


def test_connect_returns_distinct_connection_per_thread(store):
    main_conn = store._connect()
    other_conn_holder = {}

    def _grab():
        other_conn_holder["conn"] = store._connect()

    t = threading.Thread(target=_grab)
    t.start()
    t.join()

    assert other_conn_holder["conn"] is not main_conn


def test_concurrent_writes_from_multiple_threads_do_not_lock_or_lose_data(store):
    # The store sets PRAGMA busy_timeout=30000 and journal_mode=WAL per
    # thread-local connection specifically so concurrent writers retry instead
    # of raising "database is locked". Verify that actually holds under
    # real concurrent writers rather than assuming it from reading the code.
    errors = []

    def _write(n):
        try:
            store.create_user(f"user{n}@example.com", "password123", "viewer")
        except Exception as exc:  # pragma: no cover - failure path under test
            errors.append(exc)

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(store.list_users()) == 10


class TestGetRunIndex:
    """Names a run without touching the filesystem.

    The comment webhook needs the case name to write a readable message, and a
    run whose directory has been pruned still has an index row.
    """

    def test_returns_the_indexed_row(self, store):
        store.upsert_run_index({
            "run_id": "run-x", "case_name": "checkout", "baseline_name": "checkout",
            "status": "FAIL", "created_at": 1,
        })

        row = store.get_run_index("run-x")

        assert row["run_id"] == "run-x"
        assert row["case_name"] == "checkout"

    def test_returns_none_for_an_unknown_run(self, store):
        assert store.get_run_index("nope") is None
