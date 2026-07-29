"""Tests for postgres_store.py using a fully mocked psycopg2, so they run
without a real PostgreSQL server or the psycopg2 package installed (it's an
optional dependency — see requirements.txt)."""
import sys
import types

import pytest


class _FakeCursor:
    def __init__(self):
        self.executed: list[tuple[str, object]] = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def executemany(self, query, seq_of_params):
        for params in seq_of_params:
            self.executed.append((query, params))

    def fetchall(self):
        return []

    def close(self):
        pass


class _FakeConnection:
    def __init__(self):
        self.cursor_obj = _FakeCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self, cursor_factory=None):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _FakePool:
    def __init__(self, minconn, maxconn, dsn):
        self.conn = _FakeConnection()

    def getconn(self):
        return self.conn

    def putconn(self, conn):
        pass


@pytest.fixture
def fake_psycopg2(monkeypatch):
    """Inject a minimal fake psycopg2 module tree into sys.modules."""
    fake_psycopg2_mod = types.ModuleType("psycopg2")
    fake_psycopg2_mod.ProgrammingError = Exception
    fake_psycopg2_mod.OperationalError = Exception

    fake_extras_mod = types.ModuleType("psycopg2.extras")
    fake_extras_mod.RealDictCursor = object()

    def _fake_execute_batch(cursor, sql, rows):
        for row in rows:
            cursor.execute(sql, row)

    fake_extras_mod.execute_batch = _fake_execute_batch

    fake_pool_mod = types.ModuleType("psycopg2.pool")
    fake_pool_mod.ThreadedConnectionPool = _FakePool

    # `import psycopg2.extras` / `.pool` need these bound as attributes on
    # the parent module too, not just registered in sys.modules — a bare
    # types.ModuleType() doesn't get that submodule binding automatically.
    fake_psycopg2_mod.extras = fake_extras_mod
    fake_psycopg2_mod.pool = fake_pool_mod

    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2_mod)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", fake_extras_mod)
    monkeypatch.setitem(sys.modules, "psycopg2.pool", fake_pool_mod)
    return fake_psycopg2_mod


@pytest.fixture
def postgres_store(fake_psycopg2):
    from visual_regression.postgres_store import PostgresStore

    store = PostgresStore("postgresql://fake-host/fake-db")
    # The fake connection pool always hands back the same connection/cursor,
    # so table-creation queries from __init__'s _init_db() are already
    # recorded — clear them so each test only sees its own queries.
    store.pool.conn.cursor_obj.executed.clear()
    return store


def test_ensure_bootstrap_users_warns_on_weak_defaults(postgres_store, monkeypatch, capsys):
    monkeypatch.delenv("LENS_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("LENS_DEVELOPER_PASSWORD", raising=False)

    postgres_store.ensure_bootstrap_users()

    captured = capsys.readouterr()
    assert "SECURITY WARNING" in captured.err
    assert "Default/weak credentials are in use" in captured.err


def test_ensure_bootstrap_users_no_warning_with_strong_passwords(postgres_store, monkeypatch, capsys):
    monkeypatch.setenv("LENS_ADMIN_PASSWORD", "Xk9#mQ2$vLp8@nR4")
    monkeypatch.setenv("LENS_DEVELOPER_PASSWORD", "Zt7&hW3!cYq6#fB1")

    postgres_store.ensure_bootstrap_users()

    captured = capsys.readouterr()
    assert "SECURITY WARNING" not in captured.err


def test_bulk_insert_runs_empty_list_returns_zero(postgres_store):
    result = postgres_store.bulk_insert_runs([])
    assert result == 0
    assert postgres_store.pool.conn.cursor_obj.executed == []


def test_bulk_insert_runs_with_data(postgres_store):
    runs = [
        {
            "run": "run-001",
            "case_name": "demo-home",
            "status": "PASS",
            "mismatch_pct": 0.5,
            "ai_assessment": {"score": 0.12},
        },
        {
            "run": "run-002",
            "case_name": "demo-login",
            "status": "FAIL",
            "mismatch_pct": 3.2,
        },
        # Missing both "run" and "run_id" — should be filtered out, not inserted.
        {"case_name": "no-run-id"},
    ]

    result = postgres_store.bulk_insert_runs(runs)

    assert result == 2
    executed = postgres_store.pool.conn.cursor_obj.executed
    assert len(executed) == 2
    run_ids = {params[0] for _, params in executed}
    assert run_ids == {"run-001", "run-002"}
    assert postgres_store.pool.conn.committed is True


def test_create_user_rejects_invalid_role(postgres_store):
    with pytest.raises(ValueError):
        postgres_store.create_user("someone@example.com", "password123", "superadmin")
