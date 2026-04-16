from pathlib import Path

from visual_regression.models import CompareResult, DiffRegion
from visual_regression.reporter import generate_html_report, render_html_report_from_payload


def _sample_result() -> CompareResult:
    return CompareResult(
        baseline_size=[1440, 900],
        current_size=[1440, 900],
        diff_pixels=1200,
        total_pixels=1296000,
        mismatch_pct=6.2,
        ssim_score=0.91,
        regions=[DiffRegion(x=20, y=30, width=200, height=80, area=16000, mean_delta=25.0)],
    )


def test_generate_html_report_includes_severity_and_ai_explanation(tmp_path):
    report_path = tmp_path / "report.html"
    generate_html_report(
        report_path=report_path,
        test_name="demo-home-en",
        baseline_image=Path("baseline.png"),
        current_image=Path("current.png"),
        diff_image=Path("diff_overlay.png"),
        binary_image=Path("binary_diff.png"),
        result=_sample_result(),
        threshold_pct=0.5,
        ignore_regions=[],
        capture={"url": "http://example.com", "browser": "chromium"},
        review={},
        decision_history=[],
        ai_assessment={"label": "layout-shift", "score": 0.52, "threshold": 0.35},
        ai_explanation="A large section moved between captures.",
        severity={"label": "high", "score": 7},
        status="FAIL",
    )

    content = report_path.read_text(encoding="utf-8")
    assert "Severity: high" in content
    assert "A large section moved between captures." in content
    assert "high (score=7)" in content


def test_render_html_report_escapes_user_supplied_text_and_separates_current_decision(tmp_path):
    report_path = tmp_path / "report.html"
    render_html_report_from_payload(
        report_path,
        {
            "case_name": '<b>demo</b>',
            "status": "FAIL",
            "threshold_pct": 0.5,
            "ignore_regions": [],
            "capture": {
                "url": 'http://example.com/?q=<script>',
                "browser": "chromium",
                "device": "",
                "locale": "",
            },
            "result": _sample_result().to_dict(),
            "decision": {
                "status": "approved",
                "decider": "<admin>",
                "comment": "<script>alert(1)</script>",
                "timestamp": "2026-04-02T01:00:00Z",
            },
            "decision_history": [
                {
                    "status": "approved",
                    "decider": "<admin>",
                    "comment": "<script>alert(1)</script>",
                    "timestamp": "2026-04-02T01:00:00Z",
                }
            ],
            "ai_assessment": {"label": "layout-shift", "score": 0.52, "threshold": 0.35},
            "ai_explanation": 'Reason with <b>markup</b>',
            "severity": {"label": "high", "score": 7},
            "artifacts": {
                "baseline": "baseline.png",
                "current": "current.png",
                "diff_overlay": "diff_overlay.png",
                "binary_diff": "binary_diff.png",
            },
        },
    )

    content = report_path.read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content
    assert "&lt;b&gt;demo&lt;/b&gt;" in content
    assert "Current Decision" in content
    assert "<script>alert(1)</script>" not in content
