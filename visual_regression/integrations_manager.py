import json
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional

class IntegrationsManager:
    def __init__(self, config_dir: Path):
        self.config_path = config_dir / "integrations.json"
        self._ensure_exists()

    def _ensure_exists(self):
        if not self.config_path.exists():
            default_config = {
                "api_key": f"tl_live_{secrets.token_hex(16)}",
                "webhook_url": "",
                "webhook_threshold": 1.0,
                "activity": [],
                "github": {
                    "connected": False,
                    "access_token": "",
                    "login": "",
                    "avatar_url": "",
                    "profile_url": "",
                    "scopes": [],
                    "connected_at": None,
                    "pending_state": None,
                    "state_expires_at": None,
                },
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
        config = self._load()
        changed = False
        if "github" not in config:
            config["github"] = {
                "connected": False,
                "access_token": "",
                "login": "",
                "avatar_url": "",
                "profile_url": "",
                "scopes": [],
                "connected_at": None,
                "pending_state": None,
                "state_expires_at": None,
            }
            changed = True
        if not config.get("api_key") or config.get("api_key") == "lead-scientist-secure-key-2024":
            config["api_key"] = f"tl_live_{secrets.token_hex(16)}"
            changed = True
        if changed:
            self._save(config)
        return config

    def reveal_api_key(self) -> str:
        config = self._load()
        return str(config.get("api_key", ""))

    def update_webhook(self, url: str, threshold: float):
        config = self._load()
        config["webhook_url"] = url
        config["webhook_threshold"] = threshold
        self._save(config)
        message = "Webhook configuration cleared" if not url else f"Webhook configured ({url})"
        self.log_activity(message=message, branch="integrations", status="success")

    def rotate_api_key(self) -> str:
        new_key = f"tl_live_{secrets.token_hex(16)}"
        config = self.get_config()
        config["api_key"] = new_key
        self._save(config)
        self.log_activity(message="API key rotated", branch="integrations", status="success")
        return new_key

    def github_status(self) -> Dict[str, Any]:
        github = self.get_config().get("github", {})
        return {
            "connected": bool(github.get("connected")),
            "login": github.get("login", ""),
            "avatar_url": github.get("avatar_url", ""),
            "profile_url": github.get("profile_url", ""),
            "scopes": github.get("scopes", []),
            "connected_at": github.get("connected_at"),
        }

    def begin_github_oauth(self, ttl_seconds: int = 600) -> str:
        config = self.get_config()
        state = secrets.token_urlsafe(24)
        config["github"]["pending_state"] = state
        config["github"]["state_expires_at"] = time.time() + ttl_seconds
        self._save(config)
        return state

    def validate_github_state(self, state: str) -> bool:
        github = self.get_config().get("github", {})
        expected = github.get("pending_state")
        expires_at = github.get("state_expires_at") or 0
        return bool(expected and expected == state and time.time() <= float(expires_at))

    def complete_github_oauth(self, access_token: str, user: Dict[str, Any], scopes: list[str]) -> None:
        config = self.get_config()
        config["github"].update(
            {
                "connected": True,
                "access_token": access_token,
                "login": user.get("login", ""),
                "avatar_url": user.get("avatar_url", ""),
                "profile_url": user.get("html_url", ""),
                "scopes": scopes,
                "connected_at": time.time(),
                "pending_state": None,
                "state_expires_at": None,
            }
        )
        self._save(config)
        self.log_activity(
            message=f"GitHub connected as {user.get('login', 'unknown')}",
            branch="integrations",
            status="success",
        )

    def disconnect_github(self) -> None:
        config = self.get_config()
        config["github"] = {
            "connected": False,
            "access_token": "",
            "login": "",
            "avatar_url": "",
            "profile_url": "",
            "scopes": [],
            "connected_at": None,
            "pending_state": None,
            "state_expires_at": None,
        }
        self._save(config)
        self.log_activity(message="GitHub disconnected", branch="integrations", status="success")

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

    def post_github_commit_status(self, repo_url: str, sha: str, state: str, target_url: str, description: str) -> Dict[str, Any]:
        github = self.get_config().get("github", {})
        if not github.get("connected") or not github.get("access_token"):
            return {"ok": False, "error": "GitHub not connected"}
        
        import re
        import urllib.request
        import urllib.error
        
        match = re.search(r"github\.com[:/]([^/]+/[^/.]+)(?:\.git)?", repo_url)
        if not match:
            return {"ok": False, "error": f"Invalid GitHub repo URL: {repo_url}"}
        
        repo_path = match.group(1)
        api_url = f"https://api.github.com/repos/{repo_path}/statuses/{sha}"
        
        headers = {
            "Authorization": f"token {github['access_token']}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Visual-Regression-Platform",
            "Content-Type": "application/json"
        }
        
        payload = {
            "state": state,
            "target_url": target_url,
            "description": description[:140],
            "context": "Visual Regression Workbench"
        }
        
        try:
            req = urllib.request.Request(
                api_url, 
                data=json.dumps(payload).encode("utf-8"), 
                headers=headers, 
                method="POST"
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.log_activity(
                    message=f"GitHub status updated for {sha[:7]}: {state}",
                    branch="integrations",
                    status="success"
                )
                return {"ok": True, "data": data}
        except urllib.error.HTTPError as e:
            try:
                err_msg = e.read().decode("utf-8")
            except Exception:
                err_msg = "Unknown error"
            self.log_activity(
                message=f"GitHub status update failed for {sha[:7]}: {e.code}",
                branch="integrations",
                status="failed"
            )
            return {"ok": False, "error": f"HTTP {e.code}: {err_msg}"}
        except Exception as e:
            self.log_activity(
                message=f"GitHub status update error: {str(e)}",
                branch="integrations",
                status="failed"
            )
            return {"ok": False, "error": str(e)}

