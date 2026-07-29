import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ._file_lock import FileLock, atomic_replace


def _restrict_key_file_permissions(key_file: Path) -> None:
    """Best-effort lock-down of the on-disk secret key to owner read/write.

    ``os.chmod`` is largely a no-op on Windows (no POSIX mode bits), so this
    must never raise there — it's a defense-in-depth measure on POSIX where
    it actually restricts access.
    """
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass


def _get_encryption_key(key_dir: Path) -> bytes:
    key_file = key_dir / ".secret_key"
    if not key_file.exists():
        secret = secrets.token_hex(32)
        key_file.write_text(secret, encoding="utf-8")
        _restrict_key_file_permissions(key_file)
        return secret.encode("utf-8")
    return key_file.read_text(encoding="utf-8").strip().encode("utf-8")

def _encrypt_value(value: str, key: bytes) -> str:
    """Encrypt *value* with AES-256-GCM (authenticated encryption).

    Format: ``enc3:<base64(salt[16] + nonce[12] + ciphertext_with_tag)>``

    Uses the `cryptography` library's AESGCM primitive rather than a
    hand-rolled cipher; the AES key is still derived per-value via PBKDF2
    from the on-disk secret so the stored ``.secret_key`` format doesn't
    change across the enc2 -> enc3 migration.
    """
    if not value:
        return ""
    salt = os.urandom(16)
    nonce = os.urandom(12)
    enc_key = hashlib.pbkdf2_hmac("sha256", key, salt + b"enc3", 100_000, 32)
    ciphertext = AESGCM(enc_key).encrypt(nonce, value.encode("utf-8"), None)
    combined = salt + nonce + ciphertext
    return "enc3:" + base64.b64encode(combined).decode("ascii")


def _decrypt_value(encrypted_str: str, key: bytes) -> str:
    """Decrypt a value produced by *_encrypt_value*.

    Supports the current ``enc3:`` format (AES-256-GCM via the
    `cryptography` library) plus the older ``enc2:`` (hand-rolled CTR +
    HMAC-SHA256) and ``enc:`` (unauthenticated XOR) formats for backward
    compatibility with values encrypted by earlier versions of this file.
    """
    if not encrypted_str:
        return encrypted_str

    # ── Current AES-GCM format ────────────────────────────────────────────────
    if encrypted_str.startswith("enc3:"):
        try:
            combined = base64.b64decode(encrypted_str[5:])
            # salt(16) + nonce(12) + ciphertext_with_tag(≥16)
            if len(combined) < 44:
                return ""
            salt = combined[:16]
            nonce = combined[16:28]
            ciphertext = combined[28:]
            enc_key = hashlib.pbkdf2_hmac("sha256", key, salt + b"enc3", 100_000, 32)
            return AESGCM(enc_key).decrypt(nonce, ciphertext, None).decode("utf-8")
        except Exception:
            return ""

    # ── Legacy hand-rolled CTR + HMAC-SHA256 format (read-only backward compat) ─
    if encrypted_str.startswith("enc2:"):
        try:
            combined = base64.b64decode(encrypted_str[5:])
            # salt(16) + nonce(16) + ciphertext(≥1) + hmac(32)
            if len(combined) < 65:
                return ""
            salt = combined[:16]
            nonce = combined[16:32]
            tag = combined[-32:]
            ciphertext = combined[32:-32]

            enc_key = hashlib.pbkdf2_hmac("sha256", key, salt + b"enc", 100_000, 32)
            mac_key = hashlib.pbkdf2_hmac("sha256", key, salt + b"mac", 100_000, 32)

            # Verify HMAC before decrypting (authenticate-then-decrypt)
            expected_tag = hmac.new(mac_key, salt + nonce + ciphertext, "sha256").digest()
            if not hmac.compare_digest(tag, expected_tag):
                return ""

            keystream_blocks = []
            for block_idx in range((len(ciphertext) + 31) // 32):
                block = hashlib.pbkdf2_hmac(
                    "sha256", enc_key, nonce + block_idx.to_bytes(4, "big"), 1, 32
                )
                keystream_blocks.append(block)
            keystream = b"".join(keystream_blocks)[: len(ciphertext)]
            return bytes(a ^ b for a, b in zip(ciphertext, keystream)).decode("utf-8")
        except Exception:
            return ""

    # ── Legacy unauthenticated XOR format (read-only backward compat) ─────────
    if not encrypted_str.startswith("enc:"):
        return encrypted_str
    try:
        combined = base64.b64decode(encrypted_str[4:])
        if len(combined) < 16:
            return ""
        salt = combined[:16]
        encrypted = combined[16:]
        derived_key = hashlib.pbkdf2_hmac("sha256", key, salt, 100_000, 32)
        decrypted = bytes(b ^ derived_key[i % 32] for i, b in enumerate(encrypted))
        return decrypted.decode("utf-8")
    except Exception:
        return ""


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
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            github = data.get("github")
            if github and github.get("access_token"):
                key = _get_encryption_key(self.config_path.parent)
                github["access_token"] = _decrypt_value(github["access_token"], key)
            return data
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save(self, config: Dict[str, Any]):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        import copy
        config_to_save = copy.deepcopy(config)
        github = config_to_save.get("github")
        if github and github.get("access_token"):
            key = _get_encryption_key(self.config_path.parent)
            github["access_token"] = _encrypt_value(github["access_token"], key)

        lock_path = self.config_path.with_name(self.config_path.name + ".lock")
        with FileLock(lock_path, timeout=10.0):
            with tempfile.NamedTemporaryFile(
                "w",
                dir=self.config_path.parent,
                delete=False,
                suffix=".tmp",
                encoding="utf-8",
            ) as tmp:
                tmp.write(json.dumps(config_to_save, indent=2))
                tmp_path = Path(tmp.name)
            atomic_replace(tmp_path, self.config_path)

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
        if url and not url.startswith(("https://", "http://")):
            raise ValueError("Webhook URL must start with http:// or https://")
        if url:
            from .notifier import validate_webhook_url
            validate_webhook_url(url)
        config = self._load()
        config["webhook_url"] = url
        config["webhook_threshold"] = max(0.0, min(float(threshold), 100.0))  # clamp 0-100%
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

        # sha ultimately reaches an f-string-built API URL below, so an
        # unvalidated value containing "/" (or other URL-structural
        # characters) could redirect the request to a different GitHub
        # REST path — using this integration's own stored, privileged
        # access token — than the commit-status endpoint the caller is
        # meant to be limited to. A real commit SHA is always 7-40 hex
        # characters, so anything else is rejected outright rather than
        # merely URL-encoded, since encoding alone wouldn't stop a caller
        # from steering the request to a same-repo endpoint that already
        # accepts arbitrary path segments (there are none here, but hex-only
        # validation is simpler to reason about than encoding + trusting the
        # rest of the URL shape stays fixed as this function evolves).
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", sha or ""):
            return {"ok": False, "error": "Invalid commit sha"}

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

