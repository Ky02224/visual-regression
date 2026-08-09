"""A model is not adopted for being good on average.

The gate compared one number: overall accuracy against 0.5. A model trained
2026-08-07 scored text-issue 0%, broken-image 0% and font-change 3.2% while
answering "no change" for over half a 450-trial exam — and its overall figure
would have walked through that gate onto the deployed path. A tool that never
reports broken images is worse than a uniformly mediocre one, because nobody can
tell which of its answers to trust.

So the gate now also refuses a model with any collapsed class, and reports which
ones, while ignoring classes too rarely seen to judge.
"""
from visual_regression.ai_training import _collapsed_classes


def evaluation(**recalls):
    """Shape returned by _compute_multiclass_metrics: a list, not a mapping."""
    return {"evaluation": {"per_class": [
        {"label": name, "recall": r, "support": s} for name, (r, s) in recalls.items()
    ]}}


class TestCollapsedClasses:
    def test_a_healthy_model_reports_nothing(self):
        got = _collapsed_classes(
            evaluation(text_issue=(0.93, 73), broken_image=(0.95, 44)), floor=0.40)

        assert got == []

    def test_it_names_the_classes_that_collapsed(self):
        """The v3 signature: strong on average, three classes at zero."""
        got = _collapsed_classes(
            evaluation(layout_issue=(0.40, 58), text_issue=(0.0, 73),
                       broken_image=(0.0, 44), font_change=(0.032, 62),
                       color_regression=(0.99, 97)),
            floor=0.40)

        assert [name for name, _, _ in got] == ["text_issue", "broken_image", "font_change"]

    def test_the_worst_class_comes_first(self):
        got = _collapsed_classes(
            evaluation(a=(0.30, 40), b=(0.05, 40), c=(0.20, 40)), floor=0.40)

        assert [r for _, r, _ in got] == [0.05, 0.20, 0.30]

    def test_a_class_seen_too_rarely_is_not_judged(self):
        """Which pairs land in the eval fifth is chance; blocking on three
        samples would make adoption depend on that draw."""
        got = _collapsed_classes(evaluation(rare=(0.0, 3)), floor=0.40)

        assert got == []

    def test_a_class_exactly_at_the_floor_passes(self):
        got = _collapsed_classes(evaluation(edge=(0.40, 50)), floor=0.40)

        assert got == []

    def test_a_mapping_shaped_report_is_accepted_too(self):
        got = _collapsed_classes(
            {"evaluation": {"per_class": {"text-issue": {"recall": 0.0, "support": 73}}}},
            floor=0.40)

        assert [name for name, _, _ in got] == ["text-issue"]

    def test_a_report_with_no_per_class_section_blocks_nothing(self):
        """Older evaluations carry no breakdown; the overall gate still applies
        and this check simply has nothing to say."""
        assert _collapsed_classes({"evaluation": {"accuracy": 0.9}}, floor=0.40) == []
        assert _collapsed_classes({}, floor=0.40) == []
        assert _collapsed_classes(None, floor=0.40) == []
