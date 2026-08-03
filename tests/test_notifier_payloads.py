"""Tests for webhook payload shaping and delivery.

test_webhook_ssrf.py and test_notifier.py already cover URL validation and the
private-address guard. This file covers what actually gets sent and how failures
are handled — the part a reviewer notices only when an alert never arrives.

Each provider expects a different envelope: Slack reads `text`, Discord reads
`embeds`, Teams reads an Adaptive Card inside `attachments`. Post the wrong
shape and the provider returns 200 while displaying nothing, so these assert on
structure rather than on the request succeeding.
"""

from __future__ import annotations

import urllib.error

import pytest

from visual_regression.notifier import (
    _is_discord_url,
    _is_slack_url,
    _is_teams_url,
    _to_discord_payload,
    _to_slack_payload,
    _to_teams_adaptive_card,
    format_regression_detected_payload,
    trigger_webhook,
    trigger_webhook_detailed,
)


def _regression(**overrides):
    base = {
        "event": "regression.detected",
        "case_name": "checkout-page",
        "mismatch_pct": 12.3456,
        "run_id": "20260803-120000_checkout",
        "dashboard_link": "https://lens.example.com/runs/1",
        "browser": "chromium",
        "device": "iPhone 13",
        "severity": "high",
        "ai_label": "layout-issue",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

class TestProviderDetection:
    def test_recognises_slack(self):
        assert _is_slack_url("https://hooks.slack.com/services/T/B/X") is True
        assert _is_discord_url("https://hooks.slack.com/services/T/B/X") is False

    def test_recognises_discord(self):
        assert _is_discord_url("https://discord.com/api/webhooks/1/abc") is True
        assert _is_slack_url("https://discord.com/api/webhooks/1/abc") is False

    def test_recognises_teams(self):
        assert _is_teams_url("https://acme.webhook.office.com/webhookb2/abc") is True
        assert _is_teams_url("https://prod.logic.azure.com/workflows/abc") is True

    def test_an_unknown_host_matches_nothing(self):
        url = "https://example.com/hook"
        assert not any((_is_slack_url(url), _is_discord_url(url), _is_teams_url(url)))


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

class TestSlackPayload:
    def test_uses_the_text_field_slack_renders(self):
        body = _to_slack_payload(_regression())
        assert "text" in body
        assert isinstance(body["text"], str)

    def test_includes_the_case_and_mismatch(self):
        text = _to_slack_payload(_regression())["text"]
        assert "checkout-page" in text
        assert "12.3456" in text

    def test_includes_browser_device_severity_and_label(self):
        text = _to_slack_payload(_regression())["text"]
        for expected in ("chromium", "iPhone 13", "HIGH", "layout-issue"):
            assert expected in text

    def test_uses_slack_link_syntax_for_the_dashboard(self):
        """Markdown links render as literal text in Slack."""
        text = _to_slack_payload(_regression())["text"]
        assert "<https://lens.example.com/runs/1|View in Dashboard>" in text

    def test_omits_the_link_when_there_is_none(self):
        text = _to_slack_payload(_regression(dashboard_link=""))["text"]
        assert "View in Dashboard" not in text

    def test_a_test_ping_is_short_and_not_an_alarm(self):
        body = _to_slack_payload({"event": "test_ping", "message": "hello"})
        assert "hello" in body["text"]
        assert "Regression Detected" not in body["text"]

    def test_missing_fields_fall_back_rather_than_raising(self):
        text = _to_slack_payload({"event": "regression.detected"})["text"]
        assert "Unknown" in text

    def test_a_null_severity_becomes_medium(self):
        assert "MEDIUM" in _to_slack_payload(_regression(severity=None))["text"]


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

class TestDiscordPayload:
    def test_uses_the_embeds_envelope(self):
        body = _to_discord_payload(_regression())
        assert isinstance(body["embeds"], list)
        assert len(body["embeds"]) == 1

    def test_carries_every_field_as_a_named_entry(self):
        fields = {f["name"]: f["value"] for f in _to_discord_payload(_regression())["embeds"][0]["fields"]}
        assert fields["Case"] == "checkout-page"
        assert fields["Browser"] == "chromium"
        assert fields["Severity"] == "HIGH"
        assert fields["AI Label"] == "layout-issue"

    def test_uses_red_for_a_regression(self):
        assert _to_discord_payload(_regression())["embeds"][0]["color"] == 16711680

    def test_a_test_ping_is_not_red(self):
        body = _to_discord_payload({"event": "test_ping", "message": "hi"})
        assert body["embeds"][0]["color"] != 16711680

    def test_attaches_the_dashboard_link_to_the_embed(self):
        assert _to_discord_payload(_regression())["embeds"][0]["url"] == "https://lens.example.com/runs/1"

    def test_omits_the_url_key_entirely_when_there_is_no_link(self):
        """Discord rejects an embed whose url is an empty string."""
        assert "url" not in _to_discord_payload(_regression(dashboard_link=""))["embeds"][0]


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

class TestTeamsPayload:
    def test_wraps_an_adaptive_card_in_an_attachment(self):
        body = _to_teams_adaptive_card(_regression())
        assert body["type"] == "message"
        attachment = body["attachments"][0]
        assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
        assert attachment["content"]["type"] == "AdaptiveCard"

    def test_declares_a_schema_and_version(self):
        """Teams silently drops a card with no $schema."""
        card = _to_teams_adaptive_card(_regression())["attachments"][0]["content"]
        assert card["$schema"]
        assert card["version"]

    def test_lists_the_details_as_facts(self):
        card = _to_teams_adaptive_card(_regression())["attachments"][0]["content"]
        factset = next(b for b in card["body"] if b["type"] == "FactSet")
        facts = {f["title"]: f["value"] for f in factset["facts"]}
        assert facts["Case"] == "checkout-page"
        assert facts["Severity"] == "HIGH"
        assert facts["Run ID"] == "20260803-120000_checkout"

    def test_adds_an_open_url_action_for_the_dashboard(self):
        card = _to_teams_adaptive_card(_regression())["attachments"][0]["content"]
        assert card["actions"][0]["type"] == "Action.OpenUrl"

    def test_omits_actions_when_there_is_no_link(self):
        card = _to_teams_adaptive_card(_regression(dashboard_link=""))["attachments"][0]["content"]
        assert "actions" not in card

    def test_omits_the_run_id_fact_when_absent(self):
        card = _to_teams_adaptive_card(_regression(run_id=""))["attachments"][0]["content"]
        factset = next(b for b in card["body"] if b["type"] == "FactSet")
        assert all(f["title"] != "Run ID" for f in factset["facts"])


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

class _Response:
    def __init__(self, status=200):
        self.status = status

    def getcode(self):
        return self.status

    def read(self):
        return b"ok"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestDelivery:
    def test_a_successful_post_reports_ok(self, monkeypatch):
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Response(200))
        assert trigger_webhook_detailed("https://example.com/hook", _regression())["ok"] is True

    def test_a_4xx_is_not_retried(self, monkeypatch):
        """A malformed request or revoked token will fail identically on retry;
        spending the full back-off budget on it only slows the run down."""
        attempts = []

        def always_400(req, *a, **k):
            attempts.append(1)
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", always_400)
        monkeypatch.setattr("time.sleep", lambda s: None)

        result = trigger_webhook_detailed("https://example.com/hook", _regression())

        assert result["ok"] is False
        assert len(attempts) == 1

    def test_a_5xx_is_retried(self, monkeypatch):
        attempts = []

        def always_503(req, *a, **k):
            attempts.append(1)
            raise urllib.error.HTTPError(req.full_url, 503, "Unavailable", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", always_503)
        monkeypatch.setattr("time.sleep", lambda s: None)

        result = trigger_webhook_detailed("https://example.com/hook", _regression())

        assert result["ok"] is False
        assert len(attempts) > 1

    def test_recovers_when_a_retry_succeeds(self, monkeypatch):
        calls = []

        def flaky(req, *a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {}, None)
            return _Response(200)

        monkeypatch.setattr("urllib.request.urlopen", flaky)
        monkeypatch.setattr("time.sleep", lambda s: None)

        assert trigger_webhook_detailed("https://example.com/hook", _regression())["ok"] is True

    def test_an_invalid_url_is_rejected_before_any_request(self, monkeypatch):
        """SSRF guard: the request must never leave for a private address."""
        sent = []
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: sent.append(1))

        result = trigger_webhook_detailed("http://127.0.0.1:8130/internal", _regression())

        assert result["ok"] is False
        assert sent == []

    def test_trigger_webhook_returns_a_bare_boolean(self, monkeypatch):
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Response(200))
        assert trigger_webhook("https://example.com/hook", _regression()) is True


class TestFormatRegressionPayload:
    def test_produces_a_payload_the_formatters_accept(self):
        payload = format_regression_detected_payload(
            run_id="r1", case_name="home", mismatch=3.5,
            dashboard_url="https://lens.example.com",
            severity="high", browser="chromium", ai_label="layout-issue",
        )
        assert payload["case_name"] == "home"
        # Must survive every provider shaping without raising.
        for shaper in (_to_slack_payload, _to_discord_payload, _to_teams_adaptive_card):
            assert shaper(payload)
