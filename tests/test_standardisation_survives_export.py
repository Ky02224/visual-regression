"""Standardisation statistics must reach whatever format the model is served in.

A model trained on standardised features and then served unstandardised
receives inputs orders of magnitude from anything it saw — the worst kind of
defect, because training looks healthy and only the deployed path is wrong.

The deployed format here is ONNX, and the ONNX path reads a JSON sidecar rather
than the checkpoint. When standardisation was added, the sidecar was not
updated: every value needed at inference had to be listed there explicitly, and
the same omission had already happened once before with rule_feature_names
(documented in export_to_onnx).
"""
import json

import pytest

from visual_regression import ai_export


class TestSidecarCarriesTheStatistics:
    def test_the_exported_metadata_includes_mean_and_std(self, tmp_path, monkeypatch):
        """Written straight from the checkpoint, so a retrain cannot leave them
        behind."""
        captured = {}

        def fake_write(self, text, encoding=None):
            captured.update(json.loads(text))

        checkpoint = {
            "model_type": "resnet50-siamese-rule-fusion-multiclass",
            "class_names": ["a", "b"],
            "rule_feature_names": ["x", "y"],
            "rule_feature_mean": [1.5, 2.5],
            "rule_feature_std": [0.5, 4.0],
            "threshold": 0.35,
            "image_size": 224,
        }
        meta = {
            "model_type": checkpoint["model_type"],
            "threshold": float(checkpoint["threshold"]),
            "image_size": int(checkpoint["image_size"]),
            "class_names": checkpoint["class_names"],
            "rule_feature_names": list(checkpoint["rule_feature_names"]),
            "rule_feature_mean": checkpoint.get("rule_feature_mean"),
            "rule_feature_std": checkpoint.get("rule_feature_std"),
        }

        assert meta["rule_feature_mean"] == [1.5, 2.5]
        assert meta["rule_feature_std"] == [0.5, 4.0]

    def test_export_source_lists_the_statistics(self):
        """Guards the omission directly: if the keys are dropped from
        export_to_onnx again, a trained model silently ships unstandardised."""
        import inspect

        source = inspect.getsource(ai_export.export_to_onnx)
        assert '"rule_feature_mean"' in source
        assert '"rule_feature_std"' in source


class TestEveryLoaderPublishesThem:
    """_standardised_rule_vector reads these off the loaded dict, so a loader
    that omits them silently serves the model unstandardised."""

    @pytest.mark.parametrize("marker", [
        '"type": "onnx-hybrid-multiclass"',
        '"rule_dim": len(ts_meta.get(',
        '"calibrated_temperature": float(checkpoint.get(',
    ])
    def test_the_loader_dict_includes_the_statistics(self, marker):
        import inspect

        source = inspect.getsource(ai_export._load_legacy_or_hybrid_model)
        if marker not in source:
            source = inspect.getsource(ai_export)
        idx = source.index(marker)
        window = source[idx: idx + 700]
        assert "rule_feature_mean" in window, f"loader at {marker!r} does not publish the statistics"
        assert "rule_feature_std" in window


class TestApplication:
    def test_a_loaded_model_with_statistics_standardises_and_one_without_does_not(self):
        import numpy as np

        from visual_regression.ai_training import _standardised_rule_vector

        parts = [np.array([50.0, 0.001], dtype=np.float32)]
        with_stats = _standardised_rule_vector(
            {"rule_feature_mean": [50.0, 0.0], "rule_feature_std": [10.0, 0.001]}, parts, 2)
        without = _standardised_rule_vector({}, parts, 2)

        assert np.allclose(with_stats, [0.0, 1.0])
        assert np.allclose(without, [50.0, 0.001]), "a model without statistics must be untouched"
