"""Tests for get_comment, and for the delete authorisation it now backs.

The delete route used to read the comments table itself — two raw queries, each
with a separate sqlite/postgres branch, inside the HTTP handler. That put SQL in
the API layer and made the author check dependent on which database was
configured. get_comment replaces it, so it has to behave identically for both
stores.
"""

from __future__ import annotations

import pytest

from visual_regression.sqlite_store import SqliteStore


@pytest.fixture
def store(tmp_path):
    store = SqliteStore(tmp_path / "storage.db")
    # comments carry a foreign key to runs_index, so a run has to exist first.
    store.upsert_run_index({
        "run_id": "run-1",
        "case_name": "home",
        "baseline_name": "home",
        "status": "FAIL",
        "created_at": 1,
    })
    return store


class TestGetComment:
    def test_returns_the_stored_comment(self, store):
        store.add_comment("c1", "run-1", 10.5, 20.25, "a@b.com", "looks wrong")

        comment = store.get_comment("c1")

        assert comment["id"] == "c1"
        assert comment["run_id"] == "run-1"
        assert comment["author"] == "a@b.com"
        assert comment["content"] == "looks wrong"
        assert comment["x_pct"] == pytest.approx(10.5)
        assert comment["y_pct"] == pytest.approx(20.25)

    def test_returns_none_for_an_unknown_id(self, store):
        """The delete route turns this into a 404 rather than a 500."""
        assert store.get_comment("does-not-exist") is None

    def test_returns_none_after_deletion(self, store):
        store.add_comment("c1", "run-1", 0.0, 0.0, "a@b.com", "x")
        store.delete_comment("c1")
        assert store.get_comment("c1") is None

    def test_carries_the_author_the_delete_check_depends_on(self, store):
        """Only an admin, the author, or an authorised automation client may
        delete — so the author has to come back exactly as written."""
        store.add_comment("c1", "run-1", 0.0, 0.0, "Author@Example.com", "x")
        assert store.get_comment("c1")["author"] == "Author@Example.com"

    def test_carries_the_run_id_used_for_the_broadcast(self, store):
        store.add_comment("c1", "run-1", 0.0, 0.0, "a@b.com", "x")
        assert store.get_comment("c1")["run_id"] == "run-1"

    def test_shape_matches_list_comments(self, store):
        """Both feed the same UI; a key present in one and not the other would
        break whichever path the frontend happened to take."""
        store.add_comment("c1", "run-1", 1.0, 2.0, "a@b.com", "x")
        assert set(store.get_comment("c1")) == set(store.list_comments("run-1")[0])

    def test_picks_the_right_comment_among_several(self, store):
        store.add_comment("c1", "run-1", 0.0, 0.0, "a@b.com", "first")
        store.add_comment("c2", "run-1", 0.0, 0.0, "c@d.com", "second")
        assert store.get_comment("c2")["content"] == "second"
        assert store.get_comment("c1")["content"] == "first"
