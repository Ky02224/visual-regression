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
    # The new authenticated-encryption format uses the "enc2:" prefix
    # (CTR + HMAC-SHA256), replacing the old unauthenticated "enc:" XOR format.
    import json
    raw_config = json.loads((config_dir / "integrations.json").read_text(encoding="utf-8"))
    encrypted_token = raw_config["github"]["access_token"]
    assert encrypted_token.startswith("enc2:"), (
        f"Expected enc2: prefix (authenticated encryption), got: {encrypted_token[:10]}..."
    )
    assert encrypted_token != "super-secret-token"

    # Reload from a new manager instance to verify it decrypts successfully
    new_manager = IntegrationsManager(config_dir)
    config = new_manager.get_config()
    assert config["github"]["access_token"] == "super-secret-token"
