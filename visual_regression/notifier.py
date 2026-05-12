import logging
import json
import urllib.error
import urllib.request
from typing import Any, Dict

logger = logging.getLogger(__name__)

def trigger_webhook_detailed(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send a POST request to a webhook URL with the given run data."""
    if not url:
        return {"ok": False, "error": "Webhook URL is empty."}

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, 
            data=data, 
            headers={"Content-Type": "application/json", "User-Agent": "The-Lens-Notifier/1.0"}
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
