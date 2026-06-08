import logging
import json
import urllib.error
import urllib.request
from typing import Any, Dict

logger = logging.getLogger(__name__)

def _is_teams_url(url: str) -> bool:
    return "powerplatform.com" in url or "webhook.office.com" in url or "logic.azure.com" in url

def _to_teams_adaptive_card(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convert regression payload to Teams Adaptive Card format."""
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

def trigger_webhook_detailed(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send a POST request to a webhook URL with the given run data."""
    if not url:
        return {"ok": False, "error": "Webhook URL is empty."}

    send_payload = _to_teams_adaptive_card(payload) if _is_teams_url(url) else payload

    try:
        data = json.dumps(send_payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "The-Lens-Notifier/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.getcode()
            return {
                "ok": 200 <= status < 300,
                "status_code": status,
                "message": f"Webhook returned HTTP {status}.",
            }
    except urllib.error.HTTPError as e:
        logger.error(f"Failed to trigger webhook {url}: {e}")
        return {
            "ok": False,
            "status_code": e.code,
            "error": f"Webhook returned HTTP {e.code}.",
        }
    except Exception as e:
        logger.error(f"Failed to trigger webhook {url}: {e}")
        return {"ok": False, "error": str(e)}


def trigger_webhook(url: str, payload: Dict[str, Any]) -> bool:
    return bool(trigger_webhook_detailed(url, payload).get("ok"))

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
        "timestamp": None,
    }
