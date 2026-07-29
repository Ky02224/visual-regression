from pathlib import Path

from visual_regression.integrations_manager import IntegrationsManager


def test_github_oauth_lifecycle(tmp_path: Path):
    manager = IntegrationsManager(tmp_path / ".visual-regression")

    initial = manager.github_status()
    assert initial["connected"] is False
    assert initial["login"] == ""

    state = manager.begin_github_oauth()
    assert state
    assert manager.validate_github_state(state) is True

    manager.complete_github_oauth(
        access_token="token-123",
        user={
            "login": "kiayen",
            "avatar_url": "https://example.com/avatar.png",
            "html_url": "https://github.com/kiayen",
        },
        scopes=["read:user"],
    )
    connected = manager.github_status()
    assert connected["connected"] is True
    assert connected["login"] == "kiayen"
    assert connected["profile_url"] == "https://github.com/kiayen"
    assert connected["scopes"] == ["read:user"]

    manager.disconnect_github()
    disconnected = manager.github_status()
    assert disconnected["connected"] is False
    assert disconnected["login"] == ""


def test_post_github_commit_status_rejects_non_hex_sha(tmp_path: Path):
    # `sha` reaches an f-string-built GitHub API URL
    # (.../statuses/{sha}) using this integration's own privileged stored
    # access token — an unvalidated value containing "/" could redirect
    # the request to a different API path under the caller's control.
    manager = IntegrationsManager(tmp_path / ".visual-regression")
    manager.complete_github_oauth(
        access_token="token-123",
        user={"login": "kiayen", "avatar_url": "", "html_url": "https://github.com/kiayen"},
        scopes=["repo"],
    )
    result = manager.post_github_commit_status(
        repo_url="https://github.com/kiayen/some-repo",
        sha="deadbeef/../hooks",
        state="success",
        target_url="https://example.com",
        description="test",
    )
    assert result["ok"] is False
    assert "sha" in result["error"].lower()


def test_github_token_encryption(tmp_path: Path):
    config_dir = tmp_path / ".visual-regression"
    manager = IntegrationsManager(config_dir)

    manager.complete_github_oauth(
        access_token="super-secret-token",
        user={
            "login": "coder",
            "avatar_url": "https://example.com/avatar.png",
            "html_url": "https://github.com/coder",
        },
        scopes=["repo"],
    )

    # Read config file directly from disk to verify it's encrypted.
    # The current format uses the "enc3:" prefix (AES-256-GCM via the
    # `cryptography` library), replacing the older hand-rolled "enc2:"
    # (CTR + HMAC-SHA256) and "enc:" (unauthenticated XOR) formats.
    import json
    raw_config = json.loads((config_dir / "integrations.json").read_text(encoding="utf-8"))
    encrypted_token = raw_config["github"]["access_token"]
    assert encrypted_token.startswith("enc3:"), (
        f"Expected enc3: prefix (AES-256-GCM), got: {encrypted_token[:10]}..."
    )
    assert encrypted_token != "super-secret-token"

    # Reload from a new manager instance to verify it decrypts successfully
    new_manager = IntegrationsManager(config_dir)
    config = new_manager.get_config()
    assert config["github"]["access_token"] == "super-secret-token"


def test_legacy_enc2_token_still_decrypts(tmp_path: Path):
    """Values encrypted by the old hand-rolled CTR+HMAC scheme (enc2:) must
    still decrypt correctly after migrating _encrypt_value to AES-GCM
    (enc3:), so existing on-disk integrations.json files aren't broken."""
    from visual_regression.integrations_manager import _get_encryption_key, _decrypt_value
    import hashlib
    import hmac as hmac_mod
    import base64
    import os as os_mod

    config_dir = tmp_path / ".visual-regression"
    config_dir.mkdir(parents=True)
    key = _get_encryption_key(config_dir)

    # Re-implement the legacy enc2 encrypt path (mirrors the old _encrypt_value)
    value = "legacy-secret-token"
    salt = os_mod.urandom(16)
    nonce = os_mod.urandom(16)
    enc_key = hashlib.pbkdf2_hmac("sha256", key, salt + b"enc", 100_000, 32)
    mac_key = hashlib.pbkdf2_hmac("sha256", key, salt + b"mac", 100_000, 32)
    val_bytes = value.encode("utf-8")
    keystream_blocks = []
    for block_idx in range((len(val_bytes) + 31) // 32):
        block = hashlib.pbkdf2_hmac("sha256", enc_key, nonce + block_idx.to_bytes(4, "big"), 1, 32)
        keystream_blocks.append(block)
    keystream = b"".join(keystream_blocks)[: len(val_bytes)]
    ciphertext = bytes(a ^ b for a, b in zip(val_bytes, keystream))
    tag = hmac_mod.new(mac_key, salt + nonce + ciphertext, "sha256").digest()
    legacy_encrypted = "enc2:" + base64.b64encode(salt + nonce + ciphertext + tag).decode("ascii")

    assert _decrypt_value(legacy_encrypted, key) == value
