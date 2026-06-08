from visual_regression.ai_training import _is_micro_rendering_noise, _should_suppress_ai_label
from visual_regression.models import CompareResult, DiffRegion


def _result(mismatch_pct: float, regions: list[DiffRegion]) -> CompareResult:
    return CompareResult(
        baseline_size=[1440, 900],
        current_size=[1440, 900],
        diff_pixels=100,
        total_pixels=1_296_000,
        mismatch_pct=mismatch_pct,
        ssim_score=0.99,
        regions=regions,
    )


def test_login_select_arrow_noise_is_micro():
    # Matches demo-login-* false positive: 19x13 px on APAC dropdown arrow
    regions = [DiffRegion(x=901, y=590, width=19, height=13, area=199, mean_delta=28.98)]
    result = _result(0.0174, regions)
    assert _is_micro_rendering_noise(result) is True
    assert _should_suppress_ai_label(result, "text-truncation", 0.67, 0.5) is True


def test_large_text_truncation_not_micro():
    regions = [DiffRegion(x=350, y=185, width=698, height=24, area=12105, mean_delta=21.8)]
    result = _result(0.933, regions)
    assert _is_micro_rendering_noise(result) is False


def test_layout_shift_with_many_regions_not_micro():
    regions = [
        DiffRegion(x=323, y=222, width=100, height=100, area=8000, mean_delta=14.0),
        DiffRegion(x=100, y=300, width=50, height=50, area=2000, mean_delta=12.0),
        DiffRegion(x=500, y=400, width=40, height=40, area=900, mean_delta=10.0),
    ]
    result = _result(8.9, regions)
    assert _is_micro_rendering_noise(result) is False
