import ipaddress
import logging
import json
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_WEBHOOK_MAX_RETRIES = 3
_WEBHOOK_RETRY_BASE_DELAY = 1.0  # seconds; doubles each attempt


def validate_webhook_url(url: str) -> None:
    """Reject webhook URLs pointed at the cloud metadata endpoint or any
    other private/internal network address.

    Unlike a capture URL (the user's own site under test, often legitimately
    localhost during dev — see browser.py's validate_url_ssrf, which allows
    local addresses by default), a webhook is meant to notify an *external*
    service and this server makes the outbound request itself. An admin
    (accidentally or via a compromised session) pointing it at the cloud
    metadata IP, or at an internal-only service reachable from this host,
    would let the server act as an SSRF pivot — fetching IAM/instance
    credentials or probing internal infrastructure on their behalf and
    handing the response back verbatim in the webhook delivery-status API.
    This check is unconditional (unlike capture URLs, which allow local/
    internal addresses by default for local dev testing).
    """
    if not url:
        return
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Invalid URL scheme '{parsed.scheme}'. Only http and https are allowed.")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("Webhook URL must include a hostname.")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError(f"Access to local hostname '{hostname}' is blocked for security.")
    if hostname in {"169.254.169.254", "metadata.google.internal"} or hostname.startswith("169.254."):
        raise ValueError(f"Access to restricted metadata IP '{hostname}' is blocked for security.")
    _reject_if_private_address(hostname)


def _reject_if_private_address(hostname: str) -> None:
    """Block literal private/loopback/link-local IPs, and — best-effort — any
    hostname that resolves to one. DNS resolution failures are not treated
    as a rejection: this check only *adds* restrictions on top of the
    scheme/metadata checks above, so a transient/offline resolver must not
    turn into a hard failure for what may still be a legitimate public URL.
    """
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_unspecified:
            raise ValueError(f"Access to private/internal address '{hostname}' is blocked for security.")
        return
    except ValueError as exc:
        if "Access to private" in str(exc):
            raise
        # Not a literal IP — fall through to DNS resolution below.
    try:
        resolved = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except socket.gaierror:
        return
    for ip_str in resolved:
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_unspecified:
            raise ValueError(
                f"Webhook hostname '{hostname}' resolves to private/internal address '{ip_str}', which is blocked for security."
            )

def _is_teams_url(url: str) -> bool:
    return "powerplatform.com" in url or "webhook.office.com" in url or "logic.azure.com" in url


def _is_slack_url(url: str) -> bool:
    return "hooks.slack.com" in url or "slack.com/services" in url


def _is_discord_url(url: str) -> bool:
    return "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url


def _comment_summary(payload: Dict[str, Any]) -> tuple[str, str, str]:
    """(title, body, link) for a comment.added payload."""
    author = payload.get("author") or "someone"
    case_name = payload.get("case_name") or payload.get("run_id") or "a run"
    content = (payload.get("content") or "").strip()
    if len(content) > 300:
        content = content[:297] + "..."
    return (
        "💬 New review comment",
        f"**{author}** commented on **{case_name}**:\n> {content}",
        payload.get("dashboard_link", ""),
    )


def _to_teams_adaptive_card(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convert regression payload to Teams Adaptive Card format."""
    if payload.get("event") == "comment.added":
        title, text, link = _comment_summary(payload)
        card: Dict[str, Any] = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": title},
                {"type": "TextBlock", "text": text, "wrap": True},
            ],
        }
        if link:
            card["actions"] = [{"type": "Action.OpenUrl", "title": "View in Dashboard", "url": link}]
        return {
            "type": "message",
            "attachments": [
                {"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": card}
            ],
        }

    case_name = payload.get("case_name", "Unknown")
    mismatch = payload.get("mismatch_pct", 0)
    run_id = payload.get("run_id", "")
    dashboard_link = payload.get("dashboard_link", "")
    browser = payload.get("browser", "unknown")
    device = payload.get("device", "desktop")
    severity = payload.get("severity") or "medium"

    facts = [
        {"title": "Case", "value": case_name},
        {"title": "Mismatch", "value": f"{mismatch:.2f}%"},
        {"title": "Browser", "value": browser},
        {"title": "Device", "value": device},
        {"title": "Severity", "value": severity.upper()},
    ]
    if run_id:
        facts.append({"title": "Run ID", "value": run_id})

    body = [
        {
            "type": "TextBlock",
            "size": "Large",
            "weight": "Bolder",
            "text": "🔴 Visual Regression Detected",
            "color": "Attention",
        },
        {
            "type": "TextBlock",
            "text": f"Test case **{case_name}** failed with **{mismatch:.2f}%** pixel mismatch.",
            "wrap": True,
        },
        {
            "type": "FactSet",
            "facts": facts,
        },
    ]

    actions = []
    if dashboard_link:
        actions.append({
            "type": "Action.OpenUrl",
            "title": "View in Dashboard",
            "url": dashboard_link,
        })

    card: Dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
    }
    if actions:
        card["actions"] = actions

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }


def _to_slack_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convert regression payload to Slack message layout."""
    event = payload.get("event", "regression.detected")
    if event == "test_ping":
        return {"text": f"🔔 *Visual Regression Workbench Test Webhook*: {payload.get('message', 'Ping!')}"}
    if event == "comment.added":
        title, text, link = _comment_summary(payload)
        message = f"*{title}*\n{text}"
        if link:
            message += f"\n<{link}|View in Dashboard>"
        return {"text": message}

    case_name = payload.get("case_name", "Unknown")
    mismatch = payload.get("mismatch_pct", 0)
    dashboard_link = payload.get("dashboard_link", "")
    browser = payload.get("browser", "unknown")
    device = payload.get("device", "desktop")
    severity = payload.get("severity") or "medium"
    ai_label = payload.get("ai_label") or "unknown"

    text = (
        f"🔴 *Visual Regression Detected*\n"
        f"Test case *{case_name}* failed with *{mismatch:.4f}%* pixel mismatch.\n"
        f"*Browser:* `{browser}` | *Device:* `{device}` | *Severity:* `{severity.upper()}` | *AI Label:* `{ai_label}`\n"
    )
    if dashboard_link:
        text += f"<{dashboard_link}|View in Dashboard>"
    return {"text": text}


def _to_discord_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convert regression payload to Discord embed message format."""
    event = payload.get("event", "regression.detected")
    if event == "test_ping":
        return {
            "embeds": [
                {
                    "title": "🔔 Visual Regression Workbench Test Webhook",
                    "description": payload.get("message", "Ping!"),
                    "color": 3447003,  # Discord Blurple
                }
            ]
        }
    if event == "comment.added":
        title, text, link = _comment_summary(payload)
        embed: Dict[str, Any] = {"title": title, "description": text, "color": 3447003}
        if link:
            embed["url"] = link
        return {"embeds": [embed]}

    case_name = payload.get("case_name", "Unknown")
    mismatch = payload.get("mismatch_pct", 0)
    dashboard_link = payload.get("dashboard_link", "")
    browser = payload.get("browser", "unknown")
    device = payload.get("device", "desktop")
    severity = payload.get("severity") or "medium"
    ai_label = payload.get("ai_label") or "unknown"

    embed = {
        "title": "🔴 Visual Regression Detected",
        "description": f"Test case **{case_name}** failed with **{mismatch:.4f}%** pixel mismatch.",
        "color": 16711680,  # Red
        "fields": [
            {"name": "Case", "value": case_name, "inline": True},
            {"name": "Mismatch", "value": f"{mismatch:.4f}%", "inline": True},
            {"name": "Browser", "value": browser, "inline": True},
            {"name": "Device", "value": device, "inline": True},
            {"name": "Severity", "value": severity.upper(), "inline": True},
            {"name": "AI Label", "value": ai_label, "inline": True},
        ],
    }
    if dashboard_link:
        embed["url"] = dashboard_link
    return {"embeds": [embed]}


def trigger_webhook_detailed(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send a POST to a webhook URL with automatic retry on transient failures.

    Retries up to _WEBHOOK_MAX_RETRIES times with exponential back-off on:
    - Network/connection errors
    - HTTP 5xx (server-side) responses

    4xx errors are NOT retried (client mistake, retrying won't help).
    The returned dict always contains an 'attempts' field.
    """
    if not url:
        return {"ok": False, "error": "Webhook URL is empty.", "attempts": 0}

    try:
        validate_webhook_url(url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "attempts": 0}

    if _is_teams_url(url):
        send_payload = _to_teams_adaptive_card(payload)
    elif _is_slack_url(url):
        send_payload = _to_slack_payload(payload)
    elif _is_discord_url(url):
        send_payload = _to_discord_payload(payload)
    else:
        send_payload = payload

    data = json.dumps(send_payload).encode("utf-8")
    last_error: Dict[str, Any] = {}

    for attempt in range(1, _WEBHOOK_MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "The-Lens-Notifier/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                status = response.getcode()
                if 200 <= status < 300:
                    return {
                        "ok": True,
                        "status_code": status,
                        "message": f"Webhook returned HTTP {status}.",
                        "attempts": attempt,
                    }
                # Treat 5xx as retryable
                last_error = {"ok": False, "status_code": status, "error": f"Webhook returned HTTP {status}."}
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                # Client error — no point retrying
                logger.error("Webhook %s client error %s (not retrying)", url, e.code)
                return {"ok": False, "status_code": e.code, "error": f"Webhook returned HTTP {e.code}.", "attempts": attempt}
            logger.warning("Webhook %s server error %s (attempt %d/%d)", url, e.code, attempt, _WEBHOOK_MAX_RETRIES)
            last_error = {"ok": False, "status_code": e.code, "error": f"Webhook returned HTTP {e.code}."}
        except Exception as e:
            logger.warning("Webhook %s network error (attempt %d/%d): %s", url, attempt, _WEBHOOK_MAX_RETRIES, e)
            last_error = {"ok": False, "error": str(e)}

        if attempt < _WEBHOOK_MAX_RETRIES:
            delay = _WEBHOOK_RETRY_BASE_DELAY * (2 ** (attempt - 1))  # 1s, 2s, 4s
            logger.info("Retrying webhook in %.1fs...", delay)
            time.sleep(delay)

    logger.error("Webhook %s failed after %d attempts", url, _WEBHOOK_MAX_RETRIES)
    return {**last_error, "attempts": _WEBHOOK_MAX_RETRIES}


def trigger_webhook(url: str, payload: Dict[str, Any]) -> bool:
    return bool(trigger_webhook_detailed(url, payload).get("ok"))

def format_comment_added_payload(
    run_id: str,
    case_name: str,
    author: str,
    content: str,
    dashboard_url: str,
) -> Dict[str, Any]:
    """Payload for a reviewer leaving a comment on a run.

    A pinned comment is a question aimed at someone; before this it lived only
    inside the run's report page, where the person being asked had no reason to
    look.
    """
    return {
        "event": "comment.added",
        "run_id": run_id,
        "case_name": case_name,
        "author": author,
        "content": content,
        "dashboard_link": f"{dashboard_url}/report/{run_id}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def format_regression_detected_payload(
    run_id: str,
    case_name: str,
    mismatch: float,
    dashboard_url: str,
    *,
    severity: str | None = None,
    browser: str | None = None,
    device: str | None = None,
    locale: str | None = None,
    ai_label: str | None = None,
) -> Dict[str, Any]:
    return {
        "event": "regression.detected",
        "run_id": run_id,
        "case_name": case_name,
        "status": "FAIL",
        "mismatch_pct": mismatch,
        "severity": severity,
        "browser": browser,
        "device": device or "desktop",
        "locale": locale or "default",
        "ai_label": ai_label,
        "dashboard_link": f"{dashboard_url}/report/{run_id}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
