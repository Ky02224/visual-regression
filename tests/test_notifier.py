from visual_regression.notifier import (
    format_regression_detected_payload,
    _to_slack_payload,
    _to_discord_payload,
    _is_slack_url,
    _is_discord_url,
)


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


def test_slack_and_discord_url_detection():
    assert _is_slack_url("https://hooks.slack.com/services/T000/B000/XXXX") is True
    assert _is_slack_url("https://slack.com/services/hook") is True
    assert _is_slack_url("https://webhook.office.com") is False

    assert _is_discord_url("https://discord.com/api/webhooks/123/abc") is True
    assert _is_discord_url("https://discordapp.com/api/webhooks/123/abc") is True
    assert _is_discord_url("https://hooks.slack.com") is False


def test_to_slack_payload_formatting():
    mock_payload = {
        "event": "regression.detected",
        "case_name": "landing-page",
        "mismatch_pct": 2.4567,
        "dashboard_link": "http://127.0.0.1:8130/report/run-123",
        "browser": "firefox",
        "device": "desktop",
        "severity": "high",
        "ai_label": "missing-element",
    }
    formatted = _to_slack_payload(mock_payload)
    assert "text" in formatted
    assert "landing-page" in formatted["text"]
    assert "2.4567%" in formatted["text"]
    assert "View in Dashboard" in formatted["text"]
    assert "missing-element" in formatted["text"]

    ping_payload = {"event": "test_ping", "message": "hello testing"}
    formatted_ping = _to_slack_payload(ping_payload)
    assert "hello testing" in formatted_ping["text"]


def test_to_discord_payload_formatting():
    mock_payload = {
        "event": "regression.detected",
        "case_name": "login-page",
        "mismatch_pct": 0.81234,
        "dashboard_link": "http://127.0.0.1:8130/report/run-456",
        "browser": "webkit",
        "device": "iPhone 13",
        "severity": "low",
        "ai_label": "layout-shift",
    }
    formatted = _to_discord_payload(mock_payload)
    assert "embeds" in formatted
    assert len(formatted["embeds"]) == 1
    embed = formatted["embeds"][0]
    assert embed["title"] == "🔴 Visual Regression Detected"
    assert embed["url"] == "http://127.0.0.1:8130/report/run-456"
    assert "0.8123%" in embed["description"]

    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert fields["Case"] == "login-page"
    assert fields["Mismatch"] == "0.8123%"
    assert fields["Browser"] == "webkit"
    assert fields["Device"] == "iPhone 13"
    assert fields["Severity"] == "LOW"
    assert fields["AI Label"] == "layout-shift"

    ping_payload = {"event": "test_ping", "message": "discord ping"}
    formatted_ping = _to_discord_payload(ping_payload)
    assert len(formatted_ping["embeds"]) == 1
    assert formatted_ping["embeds"][0]["description"] == "discord ping"
