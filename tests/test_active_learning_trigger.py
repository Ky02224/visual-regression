"""The review-triggered retrain must not replace the deployed model unchecked.

Approving a run can start a background retrain. That retrain wrote its weights
straight onto models/visual_ai.pt: ten review clicks swapped the model serving
every comparison for one nothing had evaluated, with no backup to return to,
while the CLI's train-ai had staged and gated since it was written. The two
paths now share one gate so they cannot drift apart again.

The trigger itself had a second fault: a missing .last_trained_count read as 0,
so the whole existing backlog counted as new and the next single review fired a
full retrain.
"""
import json

import pytest

import visual_regression.dashboard_server as server
from visual_regression.config import WorkspacePaths


@pytest.fixture(autouse=True)
def reset_in_progress_flag():
    """The real _run_background_ai_training clears this in a finally; the fakes
    below replace that function, so the module global has to be reset here or a
    test that triggers a retrain silently blocks the next one."""
    server._ai_training_in_progress = False
    yield
    server._ai_training_in_progress = False


@pytest.fixture
def paths(tmp_path):
    p = WorkspacePaths(root=tmp_path / ".visual-regression")
    p.ensure()
    (p.root / "active_learning").mkdir(parents=True, exist_ok=True)
    return p


def add_reviews(paths, n, start=0):
    al = paths.root / "active_learning"
    for i in range(start, start + n):
        (al / f"run-{i}.json").write_text(json.dumps({"run_id": f"run-{i}"}), encoding="utf-8")


class TestTrigger:
    def test_a_missing_count_file_is_seeded_rather_than_treated_as_zero(self, paths, monkeypatch):
        """The regression: 9 existing reviews and no count file meant the next
        review saw a backlog of 10 and started a full retrain."""
        add_reviews(paths, 9)
        started = []
        monkeypatch.setattr(server, "_run_background_ai_training", lambda p: started.append(p))

        server.queue_ai_training_sample(paths)

        assert not started, "a retrain was triggered by the pre-existing backlog"
        counted = (paths.root / "active_learning" / ".last_trained_count").read_text(encoding="utf-8")
        assert counted.strip() == "9", "the count must be seeded at the current backlog"

    def test_it_fires_once_the_threshold_of_new_reviews_is_reached(self, paths, monkeypatch):
        add_reviews(paths, 9)
        server.queue_ai_training_sample(paths)          # seeds at 9
        started = []
        monkeypatch.setattr(server, "_run_background_ai_training", lambda p: started.append(p))
        monkeypatch.setattr(server.threading, "Thread",
                            lambda target, args, daemon: type("T", (), {"start": lambda s: target(*args)})())

        add_reviews(paths, 10, start=100)               # ten NEW reviews
        server.queue_ai_training_sample(paths)

        assert started, "ten new reviews should trigger a retrain"

    def test_the_threshold_is_configurable(self, paths, monkeypatch):
        monkeypatch.setenv("LENS_AUTOTRAIN_REVIEW_THRESHOLD", "2")
        add_reviews(paths, 5)
        server.queue_ai_training_sample(paths)          # seeds at 5
        started = []
        monkeypatch.setattr(server, "_run_background_ai_training", lambda p: started.append(p))
        monkeypatch.setattr(server.threading, "Thread",
                            lambda target, args, daemon: type("T", (), {"start": lambda s: target(*args)})())

        add_reviews(paths, 2, start=100)
        server.queue_ai_training_sample(paths)

        assert started

    def test_zero_disables_the_trigger_entirely(self, paths, monkeypatch):
        """A deployment usually wants retraining on a schedule someone chose."""
        monkeypatch.setenv("LENS_AUTOTRAIN_REVIEW_THRESHOLD", "0")
        add_reviews(paths, 500)
        started = []
        monkeypatch.setattr(server, "_run_background_ai_training", lambda p: started.append(p))

        server.queue_ai_training_sample(paths)

        assert not started


class TestAdoptionGate:
    """adopt_model_if_gate_passes is the single door to the deployed model."""

    def _staged(self, paths):
        models = paths.models_dir
        models.mkdir(parents=True, exist_ok=True)
        staging = models / "visual_ai.staging.pt"
        staging.write_bytes(b"new-weights")
        (models / "visual_ai.staging.json").write_text("{}", encoding="utf-8")
        return staging, models / "visual_ai.pt"

    def test_a_model_failing_the_gate_is_deleted_and_the_deployed_one_survives(self, paths, monkeypatch):
        from visual_regression import ai_training

        staging, target = self._staged(paths)
        target.write_bytes(b"deployed-weights")
        monkeypatch.setattr(ai_training, "evaluate_model_on_runs",
                            lambda paths, model_path: {"samples": 40, "evaluation": {"accuracy": 0.20}})

        gate = ai_training.adopt_model_if_gate_passes(paths, staging, target, min_real_accuracy=0.5)

        assert gate["adopted"] is False
        assert target.read_bytes() == b"deployed-weights", "the deployed model was replaced by a rejected one"
        assert not staging.exists(), "a rejected staging file must not be left to be mistaken for a model"

    def test_a_passing_model_is_adopted_and_the_old_one_backed_up(self, paths, monkeypatch):
        from visual_regression import ai_training

        staging, target = self._staged(paths)
        target.write_bytes(b"deployed-weights")
        monkeypatch.setattr(ai_training, "evaluate_model_on_runs",
                            lambda paths, model_path: {"samples": 40, "evaluation": {"accuracy": 0.90}})

        gate = ai_training.adopt_model_if_gate_passes(paths, staging, target, min_real_accuracy=0.5)

        assert gate["adopted"] is True
        assert target.read_bytes() == b"new-weights"
        backups = list(paths.models_dir.glob("visual_ai.pt.bak-*"))
        assert backups and backups[0].read_bytes() == b"deployed-weights", "no rollback point was kept"

    def test_with_no_reviewed_runs_it_adopts_and_says_so(self, paths, monkeypatch):
        from visual_regression import ai_training

        staging, target = self._staged(paths)
        monkeypatch.setattr(ai_training, "evaluate_model_on_runs",
                            lambda paths, model_path: {"samples": 0, "evaluation": {}})

        gate = ai_training.adopt_model_if_gate_passes(paths, staging, target)

        assert gate["adopted"] is True
        assert "without real-data validation" in gate["message"]
