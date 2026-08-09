"""The rule features get their own pathway before meeting the image embedding.

Concatenated raw, the 74 rule columns sit beside 8192 image columns — 0.9% of
the input — and a single Linear has little reason to weight them. Standardising
them fixed their scale but not their share, and the measured effect matched
that: layout-issue went 17.5% -> 41.9% and text-issue 0% -> 33.3% while
missing-element fell 35.1% -> 0%, the signature of a narrow pathway where new
evidence displaces old rather than joining it.

Projecting the rule vector to 256 dimensions first gives it a comparable share
and its own non-linearity. The head still consumes one concatenated tensor —
image streams first, rule features last — so every call site, both exporters
and all three inference paths keep working unchanged.
"""
import pytest

torch = pytest.importorskip("torch")
import torch.nn as nn  # noqa: E402

from visual_regression.ai_models import RULE_PROJECTION_DIM, SiameseFusionHead  # noqa: E402

EMB, STREAMS, RULE, OUT = 64, 4, 12, 5
WIDTH = EMB * STREAMS + RULE


def build(widened=True, image_projection_dim=256):
    # image_projection_dim is explicit here: its default is None, since narrowing
    # the image pathway removed the overfitting without improving accuracy. The
    # tests below still cover the projected form, which stays available.
    return SiameseFusionHead(nn, embedding_dim=EMB, rule_dim=RULE, output_dim=OUT,
                             num_streams=STREAMS, widen_rule_features=widened,
                             image_projection_dim=image_projection_dim).model


class TestInterfaceIsUnchanged:
    def test_it_takes_the_same_single_concatenated_tensor(self):
        """Every caller does head(torch.cat([...])); changing that signature
        would mean touching the training loop, three inference paths and two
        exporters."""
        head = build(); head.train()

        out = head(torch.randn(4, WIDTH))

        assert out.shape == (4, OUT)

    def test_the_flat_head_is_still_available_for_old_checkpoints(self):
        flat = build(widened=False)

        assert flat[0].weight.shape[1] == WIDTH


class TestTheRulePathwayIsWide:
    def test_the_trunk_sees_the_projection_not_the_raw_columns(self):
        head = build(image_projection_dim=None)

        assert head.state_dict()["trunk.0.weight"].shape[1] == EMB * STREAMS + RULE_PROJECTION_DIM

    def test_the_rule_columns_reach_the_output(self):
        """A pathway that cannot change the answer is not a pathway."""
        head = build(); head.eval()
        zeros = torch.zeros(2, WIDTH)
        loaded = zeros.clone()
        loaded[:, -RULE:] = 5.0

        with torch.no_grad():
            delta = (head(zeros) - head(loaded)).abs().max().item()

        assert delta > 1e-6

    def test_only_the_trailing_columns_are_treated_as_rule_features(self):
        """The split is positional; getting it wrong would feed image data
        through the rule projection and silently corrupt every prediction."""
        head = build(); head.eval()
        base = torch.zeros(2, WIDTH)
        image_changed = base.clone()
        image_changed[:, : EMB * STREAMS] = 3.0

        with torch.no_grad():
            assert (head(base) - head(image_changed)).abs().max().item() > 1e-6


class TestCheckpointRoundTrip:
    def test_weights_reload_into_an_identically_built_head(self):
        source = build(); source.eval()
        target = build(); target.load_state_dict(source.state_dict()); target.eval()
        x = torch.randn(3, WIDTH)

        with torch.no_grad():
            assert torch.allclose(source(x), target(x), atol=1e-6)

    def test_the_architecture_is_identifiable_from_the_state_dict(self):
        """_load_legacy_or_hybrid_model rebuilds the head before loading, and
        picks which one from these key names."""
        widened = set(build().state_dict())
        flat = set(build(widened=False).state_dict())

        assert any(k.startswith("rule_proj.") for k in widened)
        assert not any(k.startswith("rule_proj.") for k in flat)
        assert "trunk.0.weight" in widened
        assert "0.weight" in flat


class TestImageProjection:
    """The image side is projected too, so neither pathway is 32x the other.

    Measured on v5: train loss 0.499 against val loss 1.788, while a small model
    over the same 24 pixel statistics reached 82.0% without DOM where this head
    reached 37.0%. 8192 image dimensions beside 77 rule dimensions is capacity to
    memorise with, and the trunk's first layer alone held 8.65M weights fed
    almost entirely by pixels.
    """

    def test_the_trunk_sees_both_pathways_at_the_same_width(self):
        head = build()

        assert head.state_dict()["trunk.0.weight"].shape[1] == 256 + RULE_PROJECTION_DIM

    def test_the_image_pathway_still_reaches_the_output(self):
        """Narrowing it must not amount to switching it off."""
        head = build(); head.eval()
        base = torch.zeros(2, WIDTH)
        changed = base.clone()
        changed[:, : EMB * STREAMS] = 3.0

        with torch.no_grad():
            assert (head(base) - head(changed)).abs().max().item() > 1e-6

    def test_it_is_far_smaller_at_the_size_actually_used(self):
        """At ResNet50's 2048 per stream — the size this is for. The toy
        dimensions the other tests use would show the opposite, since projecting
        256 columns to 256 adds parameters rather than removing them."""
        def params(image_projection_dim):
            return sum(p.numel() for p in SiameseFusionHead(
                nn, embedding_dim=2048, rule_dim=77, output_dim=7, num_streams=4,
                widen_rule_features=True,
                image_projection_dim=image_projection_dim).model.parameters())

        small, big = params(256), params(None)

        assert small < big / 2, f"{small:,} vs {big:,} — the memorisation capacity is still there"

    def test_the_previous_architecture_is_still_buildable(self):
        """Every checkpoint trained before this carries no image_proj weights,
        and building one for them fails the load."""
        old = SiameseFusionHead(nn, embedding_dim=EMB, rule_dim=RULE, output_dim=OUT,
                                num_streams=STREAMS, widen_rule_features=True,
                                image_projection_dim=None).model

        assert not any(k.startswith("image_proj.") for k in old.state_dict())
        assert old.state_dict()["trunk.0.weight"].shape[1] == EMB * STREAMS + RULE_PROJECTION_DIM

    def test_both_shapes_are_identifiable_from_the_state_dict(self):
        """_load_legacy_or_hybrid_model picks the architecture from these keys,
        and reads the true image width off image_proj — the trunk no longer
        states it."""
        new = build().state_dict()

        assert "image_proj.0.weight" in new
        assert new["image_proj.0.weight"].shape[1] == EMB * STREAMS

    def test_weights_reload_into_an_identically_built_head(self):
        source = build(); source.eval()
        target = build(); target.load_state_dict(source.state_dict()); target.eval()
        x = torch.randn(3, WIDTH)

        with torch.no_grad():
            assert torch.allclose(source(x), target(x), atol=1e-6)


class TestCompleteSiameseModelStreamDetection:
    """CompleteSiameseModel.forward decides at trace time whether the model
    takes a 4th "diff image" stream, by reading the width the head's first
    parameter expects. next(self.head.parameters()) picks whatever comes first
    in the ModuleDict — rule_proj for a widened head, shape (128, rule_dim) —
    so it read rule_dim as "the expected width" and concluded the head was
    small enough for 3 streams. The 4-stream branch never ran, ONNX export
    traced a model missing a whole input stream, and the head's own first
    matmul then saw 6400 columns where the trunk was built for 8448 (4 streams
    of 2048 plus the 256-wide rule projection) — every export of a widened-head
    model failed with a shape error, silently, since train_model wraps the
    export in a bare try/except and logs a warning nothing was watching.
    """

    class _FakeBackbone(torch.nn.Module):
        def forward(self, x):
            return torch.zeros(x.shape[0], EMB, 1, 1)

    def _run(self, head, rule_dim):
        from visual_regression.ai_models import CompleteSiameseModel
        wrapper = CompleteSiameseModel(self._FakeBackbone(), head)
        wrapper.eval()
        with torch.no_grad():
            return wrapper(torch.zeros(2, 3, 8, 8), torch.zeros(2, 3, 8, 8),
                           torch.zeros(2, rule_dim))

    def test_a_widened_head_gets_all_four_image_streams(self):
        """This is the exact failure: without the fix this raises a matmul
        shape error instead of returning."""
        head = build()

        out = self._run(head, RULE)

        assert out.shape == (2, OUT)

    def test_a_flat_head_still_gets_the_right_stream_count(self):
        """The flat/legacy head's first parameter genuinely is the layer that
        receives the concatenation, so the original heuristic was correct for
        it — the fix must not break that case."""
        head = build(widened=False)

        out = self._run(head, RULE)

        assert out.shape == (2, OUT)
