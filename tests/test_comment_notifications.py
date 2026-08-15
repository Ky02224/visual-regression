"""A pinned comment has to reach someone who is not looking at that report.

Two halves: the payload has to render as a comment rather than as a regression
(the chat converters default to the regression layout for any unknown event),
and the API has to send it — without letting an unreachable webhook fail the
comment the reviewer just wrote.
"""

from __future__ import annotations

import json

import pytest

from visual_regression.notifier import (
    _to_discord_payload,
    _to_slack_payload,
    _to_teams_adaptive_card,
    format_comment_added_payload,
)


@pytest.fixture
def payload():
    return format_comment_added_payload(
        run_id="run-7",
        case_name="checkout-page",
        author="tester@example.com",
        content="This banner shifted 4px left",
        dashboard_url="http://127.0.0.1:8200",
    )


class TestPayload:
    def test_carries_the_event_name_the_converters_switch_on(self, payload):
        assert payload["event"] == "comment.added"

    def test_links_to_the_run_it_belongs_to(self, payload):
        assert payload["dashboard_link"] == "http://127.0.0.1:8200/report/run-7"

    def test_carries_author_and_content(self, payload):
        assert payload["author"] == "tester@example.com"
        assert "shifted 4px" in payload["content"]


class TestChatRendering:
    """Without an explicit branch these fall through to the regression layout,
    which would announce a comment as a 0.0000% pixel failure."""

    def test_slack_renders_it_as_a_comment(self, payload):
        text = _to_slack_payload(payload)["text"]

        assert "comment" in text.lower()
        assert "tester@example.com" in text
        assert "shifted 4px" in text
        assert "Regression Detected" not in text

    def test_discord_renders_it_as_a_comment(self, payload):
        embed = _to_discord_payload(payload)["embeds"][0]

        assert "comment" in embed["title"].lower()
        assert "tester@example.com" in embed["description"]
        assert embed["url"] == payload["dashboard_link"]

    def test_teams_renders_it_as_a_comment(self, payload):
        card = _to_teams_adaptive_card(payload)["attachments"][0]["content"]
        rendered = json.dumps(card)

        assert "comment" in rendered.lower()
        assert "tester@example.com" in rendered
        assert "Regression Detected" not in rendered

    def test_a_long_comment_is_truncated(self):
        long_payload = format_comment_added_payload(
            run_id="r", case_name="c", author="a", content="x" * 900, dashboard_url="http://d"
        )

        assert len(_to_slack_payload(long_payload)["text"]) < 700

    def test_a_regression_payload_still_renders_as_a_regression(self):
        """The new branch must not swallow the event it was added beside."""
        from visual_regression.notifier import format_regression_detected_payload

        regression = format_regression_detected_payload(
            run_id="r", case_name="c", mismatch=1.5, dashboard_url="http://d"
        )

        assert "Regression Detected" in _to_slack_payload(regression)["text"]
