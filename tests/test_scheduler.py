"""Tests for the cron-like suite scheduler.

183 statements at 0% coverage before this file. The scheduler runs unattended in
a background thread, so a break here produces no error anyone would notice —
jobs simply stop firing, or fire at the wrong time.

The scheduler thread itself is never started here; the loop sleeps 10s per tick
and would make the suite slow and flaky. What is tested is everything the loop
calls: the cron matcher, next-run computation, job CRUD and its persistence.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime

import pytest

from visual_regression.config import WorkspacePaths
from visual_regression.scheduler import ScheduledJob, Scheduler


@pytest.fixture
def scheduler(tmp_path):
    paths = WorkspacePaths(tmp_path / ".visual-regression")
    paths.ensure()
    return Scheduler(db_store=None, paths=paths)


# ---------------------------------------------------------------------------
# Cron field matching
# ---------------------------------------------------------------------------

class TestMatchField:
    def test_star_matches_everything(self, scheduler):
        assert all(scheduler._match_field("*", v) for v in (0, 7, 31, 59))

    @pytest.mark.parametrize("value,expected", [(0, True), (5, True), (10, True), (3, False), (7, False)])
    def test_step_syntax(self, scheduler, value, expected):
        assert scheduler._match_field("*/5", value) is expected

    @pytest.mark.parametrize("value,expected", [(9, True), (12, True), (17, True), (8, False), (18, False)])
    def test_range_syntax(self, scheduler, value, expected):
        assert scheduler._match_field("9-17", value) is expected

    @pytest.mark.parametrize("value,expected", [(1, True), (15, True), (30, True), (2, False)])
    def test_list_syntax(self, scheduler, value, expected):
        assert scheduler._match_field("1,15,30", value) is expected

    @pytest.mark.parametrize("value,expected", [(4, True), (0, False), (5, False)])
    def test_exact_value(self, scheduler, value, expected):
        assert scheduler._match_field("4", value) is expected

    @pytest.mark.parametrize("value,expected", [(10, True), (12, True), (14, True), (11, False), (16, False)])
    def test_range_with_step(self, scheduler, value, expected):
        assert scheduler._match_field("10-14/2", value) is expected

    def test_list_of_ranges(self, scheduler):
        assert scheduler._match_field("1-3,20-22", 2) is True
        assert scheduler._match_field("1-3,20-22", 21) is True
        assert scheduler._match_field("1-3,20-22", 10) is False


# ---------------------------------------------------------------------------
# Next-run computation
# ---------------------------------------------------------------------------

class TestCalculateNextRun:
    def test_returns_a_future_timestamp(self, scheduler):
        now = time.time()
        assert scheduler._calculate_next_run("*/5 * * * *", now) > now

    def test_every_minute_lands_within_two_minutes(self, scheduler):
        now = time.time()
        assert scheduler._calculate_next_run("* * * * *", now) - now <= 120

    def test_daily_job_lands_at_the_requested_hour_and_minute(self, scheduler):
        nxt = scheduler._calculate_next_run("30 3 * * *", time.time())
        assert nxt is not None
        moment = datetime.fromtimestamp(nxt)
        assert (moment.hour, moment.minute) == (3, 30)

    def test_wrong_field_count_returns_none(self, scheduler):
        assert scheduler._calculate_next_run("* * *", time.time()) is None

    def test_unparseable_expression_returns_none(self, scheduler):
        assert scheduler._calculate_next_run("not a cron", time.time()) is None

    def test_impossible_date_returns_none_rather_than_looping_forever(self, scheduler):
        """February 30th never occurs; the search must give up at its 1-year cap."""
        assert scheduler._calculate_next_run("0 0 30 2 *", time.time()) is None

    def test_fallback_path_is_the_one_in_use(self, scheduler):
        """croniter is not in requirements.txt, so the local-time fallback is what
        actually schedules jobs. Note the two paths disagree on timezone: the
        croniter branch builds its base in UTC, while this fallback uses
        time.localtime/time.mktime. Installing croniter would therefore shift
        every existing schedule by the machine's UTC offset."""
        with pytest.raises(ImportError):
            __import__("croniter")
        assert scheduler._calculate_next_run("*/5 * * * *", time.time()) is not None


# ---------------------------------------------------------------------------
# Job CRUD and persistence
# ---------------------------------------------------------------------------

class TestJobManagement:
    def test_add_job_returns_an_id_and_schedules_it(self, scheduler):
        job_id = scheduler.add_job("nightly", "0 2 * * *", "suite.demo.yaml")
        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].job_id == job_id
        assert jobs[0].enabled is True
        assert jobs[0].next_run is not None

    def test_added_job_is_persisted_to_disk(self, scheduler):
        job_id = scheduler.add_job("nightly", "0 2 * * *", "suite.demo.yaml")
        saved = json.loads(scheduler.jobs_file.read_text(encoding="utf-8"))
        assert saved[job_id]["name"] == "nightly"
        assert saved[job_id]["cron_expression"] == "0 2 * * *"

    def test_remove_job(self, scheduler):
        job_id = scheduler.add_job("temp", "* * * * *", "s.yaml")
        assert scheduler.remove_job(job_id) is True
        assert scheduler.list_jobs() == []

    def test_removing_an_unknown_job_reports_false(self, scheduler):
        assert scheduler.remove_job("job_does_not_exist") is False

    def test_disabling_clears_the_next_run(self, scheduler):
        """A disabled job with a next_run left set would fire on the next tick."""
        job_id = scheduler.add_job("j", "* * * * *", "s.yaml")
        assert scheduler.enable_job(job_id, False) is True
        job = scheduler.list_jobs()[0]
        assert job.enabled is False
        assert job.next_run is None

    def test_reenabling_recomputes_the_next_run(self, scheduler):
        job_id = scheduler.add_job("j", "* * * * *", "s.yaml")
        scheduler.enable_job(job_id, False)
        scheduler.enable_job(job_id, True)
        job = scheduler.list_jobs()[0]
        assert job.enabled is True
        assert job.next_run is not None

    def test_enabling_an_unknown_job_reports_false(self, scheduler):
        assert scheduler.enable_job("nope", True) is False

    def test_enable_job_does_not_deadlock(self, scheduler):
        """enable_job used to call save_jobs() while already holding _lock, and
        threading.Lock is not reentrant — the call never returned. Since
        /api/scheduler/jobs/toggle calls straight into it, toggling a job from
        the dashboard hung that request thread permanently.
        """
        job_id = scheduler.add_job("j", "* * * * *", "s.yaml")
        finished = threading.Event()

        def toggle():
            scheduler.enable_job(job_id, False)
            scheduler.enable_job(job_id, True)
            finished.set()

        worker = threading.Thread(target=toggle, daemon=True)
        worker.start()

        assert finished.wait(timeout=10), "enable_job deadlocked"

    def test_job_ids_are_unique_within_a_scheduler(self, scheduler):
        ids = {scheduler.add_job(f"j{i}", "* * * * *", "s.yaml") for i in range(5)}
        assert len(ids) == 5


class TestPersistence:
    def test_jobs_survive_a_restart(self, tmp_path):
        paths = WorkspacePaths(tmp_path / ".visual-regression")
        paths.ensure()
        first = Scheduler(db_store=None, paths=paths)
        job_id = first.add_job("nightly", "0 2 * * *", "suite.demo.yaml")

        second = Scheduler(db_store=None, paths=paths)

        assert [j.job_id for j in second.list_jobs()] == [job_id]
        assert second.list_jobs()[0].name == "nightly"

    def test_missing_file_starts_empty(self, scheduler):
        assert scheduler.list_jobs() == []

    def test_corrupt_file_starts_empty_instead_of_crashing(self, tmp_path, caplog):
        """A truncated schedules.json must not stop the server from booting."""
        paths = WorkspacePaths(tmp_path / ".visual-regression")
        paths.ensure()
        (paths.root / "schedules.json").write_text("{not json", encoding="utf-8")

        scheduler = Scheduler(db_store=None, paths=paths)

        assert scheduler.list_jobs() == []

    def test_unknown_fields_do_not_crash_the_load(self, tmp_path):
        paths = WorkspacePaths(tmp_path / ".visual-regression")
        paths.ensure()
        (paths.root / "schedules.json").write_text(
            json.dumps({"j1": {"job_id": "j1", "name": "n", "cron_expression": "* * * * *",
                               "suite_path": "s.yaml", "removed_field": 1}}),
            encoding="utf-8",
        )
        scheduler = Scheduler(db_store=None, paths=paths)
        assert scheduler.list_jobs() == []


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------

class TestRunJobAction:
    def test_invokes_run_suite_with_the_configured_suite(self, scheduler, monkeypatch):
        captured = {}

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["timeout"] = kwargs.get("timeout")
            return _Result()

        monkeypatch.setattr("subprocess.run", fake_run)
        job = ScheduledJob("j1", "nightly", "0 2 * * *", "suites/suite.demo.yaml")

        scheduler._run_job_action(job)

        assert "run-suite" in captured["cmd"]
        assert "suites/suite.demo.yaml" in captured["cmd"]

    def test_bounds_the_run_with_a_timeout(self, scheduler, monkeypatch):
        """Without a timeout a wedged capture would pin the worker thread forever."""
        captured = {}

        class _Result:
            returncode = 0
            stdout = stderr = ""

        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: (captured.update(kw), _Result())[1],
        )
        scheduler._run_job_action(ScheduledJob("j1", "n", "* * * * *", "s.yaml"))

        assert captured["timeout"] == 600.0

    def test_a_failing_suite_is_logged_not_raised(self, scheduler, monkeypatch):
        class _Result:
            returncode = 4
            stdout = ""
            stderr = "boom"

        monkeypatch.setattr("subprocess.run", lambda cmd, **kw: _Result())
        scheduler._run_job_action(ScheduledJob("j1", "n", "* * * * *", "s.yaml"))

    def test_a_raising_subprocess_is_swallowed(self, scheduler, monkeypatch):
        """The scheduler thread must survive a job that cannot even start."""
        def explode(cmd, **kw):
            raise OSError("no such executable")

        monkeypatch.setattr("subprocess.run", explode)
        scheduler._run_job_action(ScheduledJob("j1", "n", "* * * * *", "s.yaml"))


class TestStartStop:
    def test_start_is_idempotent_and_stop_joins(self, scheduler):
        scheduler.start()
        first_thread = scheduler._thread
        scheduler.start()
        assert scheduler._thread is first_thread
        scheduler.stop()
        assert scheduler._running is False

    def test_stop_without_start_is_safe(self, scheduler):
        scheduler.stop()
        assert scheduler._running is False
