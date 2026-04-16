import json
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

class IntegrationsManager:
    def __init__(self, config_dir: Path):
        self.config_path = config_dir / "integrations.json"
        self._ensure_exists()

    def _ensure_exists(self):
        if not self.config_path.exists():
            default_config = {
                "api_key": "lead-scientist-secure-key-2024",  # Keep legacy key initially
                "webhook_url": "",
                "webhook_threshold": 1.0,
                "activity": []
            }
            self._save(default_config)

    def _load(self) -> Dict[str, Any]:
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save(self, config: Dict[str, Any]):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    def get_config(self) -> Dict[str, Any]:
        return self._load()

    def update_webhook(self, url: str, threshold: float):
        config = self._load()
        config["webhook_url"] = url
        config["webhook_threshold"] = threshold
        self._save(config)

    def rotate_api_key(self) -> str:
        new_key = f"tl_live_{secrets.token_hex(16)}"
        config = self._load()
        config["api_key"] = new_key
        self._save(config)
        return new_key

    def log_activity(self, message: str, branch: str = "main", status: str = "success"):
        config = self._load()
        if "activity" not in config:
            config["activity"] = []
        
        entry = {
            "id": secrets.token_hex(4),
            "message": message,
            "branch": branch,
            "status": status,
            "timestamp": time.time(),
            "time_str": "Just now" # Frontend can handle specific relative time
        }
        
        config["activity"].insert(0, entry)
        config["activity"] = config["activity"][:50] # Keep last 50
        self._save(config)
