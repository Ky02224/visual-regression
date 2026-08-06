"""Rule features must reach the fusion layer on a comparable scale.

Measured on this project's captures, the raw feature columns span a standard
deviation ratio of 2.4e10 — max_delta varies by about 24, px_translate_x by
about 0.003. Concatenated onto an 8192-wide image embedding and fed to a single
Linear, the small columns cannot move the output enough for gradient descent to
find them. That is the mechanism behind two otherwise puzzling measurements:
zeroing all 53 DOM columns left the network's predictions unchanged, while a
gradient-boosted tree over the same features — scale-invariant by construction —
reached 66.7% where the network reached 36.0%.
"""
import numpy as np

from visual_regression.ai_features import rule_feature_stats, standardise_rule_vector


class TestStats:
    def test_a_constant_column_gets_unit_scale_rather_than_zero(self):
        """width_ratio is exactly 1.0 on every same-size comparison; dividing by
        its real deviation would be a division by nothing."""
        rows = np.array([[1.0, 5.0], [1.0, 9.0], [1.0, 1.0]], dtype=np.float32)

        mean, std = rule_feature_stats(rows)

        assert std[0] == 1.0
        assert std[1] > 0.0
        assert mean[0] == 1.0

    def test_standardising_gives_zero_mean_and_unit_deviation(self):
        rng = np.random.default_rng(0)
        rows = np.stack([rng.normal(50, 25, 400), rng.normal(0.001, 0.003, 400)], axis=1).astype(np.float32)

        mean, std = rule_feature_stats(rows)
        out = standardise_rule_vector(rows, mean, std)

        assert np.allclose(out.mean(axis=0), 0, atol=1e-4)
        assert np.allclose(out.std(axis=0), 1, atol=1e-4)

    def test_columns_of_wildly_different_scale_end_up_comparable(self):
        """The point of the exercise: after standardising, a column that varied
        by 0.003 carries the same weight as one that varied by 25."""
        rng = np.random.default_rng(1)
        big = rng.normal(50, 25, 500)
        tiny = rng.normal(0.001, 0.003, 500)
        rows = np.stack([big, tiny], axis=1).astype(np.float32)

        mean, std = rule_feature_stats(rows)
        out = standardise_rule_vector(rows, mean, std)

        ratio = out.std(axis=0).max() / out.std(axis=0).min()
        assert ratio < 1.05, f"columns still differ by {ratio:.1f}x after standardising"


class TestBackwardCompatibility:
    def test_a_model_without_statistics_is_left_alone(self):
        """Checkpoints predating this keep their original behaviour exactly."""
        vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)

        assert np.array_equal(standardise_rule_vector(vec, None, None), vec)

    def test_statistics_narrower_than_the_vector_standardise_what_they_cover(self):
        """A checkpoint fitted before a feature block was appended knows the
        earlier columns and nothing about the new ones; refusing outright would
        throw away the columns it does know."""
        vec = np.array([10.0, 20.0, 30.0, 40.0], dtype=np.float32)
        mean = np.array([10.0, 10.0], dtype=np.float32)
        std = np.array([2.0, 5.0], dtype=np.float32)

        out = standardise_rule_vector(vec, mean, std)

        assert out[0] == 0.0            # (10-10)/2
        assert out[1] == 2.0            # (20-10)/5
        assert out[2] == 30.0           # untouched
        assert out[3] == 40.0

    def test_a_batch_is_standardised_row_wise(self):
        batch = np.array([[10.0, 100.0], [20.0, 200.0]], dtype=np.float32)
        mean = np.array([10.0, 100.0], dtype=np.float32)
        std = np.array([10.0, 100.0], dtype=np.float32)

        out = standardise_rule_vector(batch, mean, std)

        assert np.allclose(out, [[0.0, 0.0], [1.0, 1.0]])
