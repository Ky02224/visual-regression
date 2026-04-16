import json
import logging
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

def trigger_webhook(url: str, payload: Dict[str, Any]) -> bool:
    """Send a POST request to a webhook URL with the given run data."""
    if not url:
        return False

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, 
            data=data, 
            headers={"Content-Type": "application/json", "User-Agent": "The-Lens-Notifier/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.getcode()
            return 200 <= status < 300
    except Exception as e:
        logger.error(f"Failed to trigger webhook {url}: {e}")
        return False

def format_run_notification(run_id: str, case_name: str, status: str, mismatch: float, dashboard_url: str) -> Dict[str, Any]:
    return {
        "event": "visual_regression_completed",
        "run_id": run_id,
        "name": case_name,
        "status": "PASS" if status == "PASS" else "FAIL",
        "mismatch_percentage": mismatch,
        "dashboard_link": f"{dashboard_url}/report/{run_id}",
        "timestamp": json.dumps(None) # just placeholder
    }
