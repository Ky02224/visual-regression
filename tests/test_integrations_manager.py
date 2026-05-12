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
