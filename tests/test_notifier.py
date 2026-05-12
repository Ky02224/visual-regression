from visual_regression.notifier import format_regression_detected_payload


def test_format_regression_detected_payload_contains_expected_fields():
    payload = format_regression_detected_payload(
        run_id="run-123",
        case_name="demo-home-mobile",
        mismatch=4.2,
        dashboard_url="http://127.0.0.1:8130",
        severity="high",
        browser="chromium",
        device="iPhone 13",
        locale="en-US",
        ai_label="missing-element",
    )

    assert payload["event"] == "regression.detected"
    assert payload["status"] == "FAIL"
    assert payload["run_id"] == "run-123"
    assert payload["case_name"] == "demo-home-mobile"
    assert payload["mismatch_pct"] == 4.2
    assert payload["severity"] == "high"
    assert payload["browser"] == "chromium"
    assert payload["device"] == "iPhone 13"
    assert payload["locale"] == "en-US"
    assert payload["ai_label"] == "missing-element"
    assert payload["dashboard_link"].endswith("/report/run-123")
