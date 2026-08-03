"""Tests for secret storage and the GitHub OAuth state machine.

integrations.json holds a GitHub access token and the automation API key, so the
encryption around it is the thing standing between a readable config file and
someone else's repository. The OAuth `state` is the CSRF defence on the callback.

Neither had direct tests. These are all offline — no request reaches GitHub.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from visual_regression.integrations_manager import (
    IntegrationsManager,
    _decrypt_value,
    _encrypt_value,
    _get_encryption_key,
)


@pytest.fixture
def key(tmp_path):
    return _get_encryption_key(tmp_path)


@pytest.fixture
def manager(tmp_path):
    return IntegrationsManager(tmp_path)


# ---------------------------------------------------------------------------
# Key material
# ---------------------------------------------------------------------------

class TestEncryptionKey:
    def test_generates_and_persists_a_key(self, tmp_path):
        first = _get_encryption_key(tmp_path)
        assert (tmp_path / ".secret_key").exists()
        assert _get_encryption_key(tmp_path) == first

    def test_two_workspaces_get_different_keys(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert _get_encryption_key(a) != _get_encryption_key(b)

    def test_the_key_is_long_enough_to_be_a_key(self, tmp_path):
        assert len(_get_encryption_key(tmp_path)) >= 32


# ---------------------------------------------------------------------------
# Encryption round-trip
# ---------------------------------------------------------------------------

class TestEncryption:
    def test_round_trips_a_value(self, key):
        assert _decrypt_value(_encrypt_value("ghp_secret_token", key), key) == "ghp_secret_token"

    def test_the_ciphertext_does_not_contain_the_plaintext(self, key):
        """The whole point: someone reading integrations.json learns nothing."""
        blob = _encrypt_value("ghp_secret_token", key)
        assert "ghp_secret_token" not in blob
        assert "ghp_secret_token" not in base64.b64decode(blob[5:]).decode("latin-1")

    def test_uses_the_current_format_marker(self, key):
        assert _encrypt_value("x", key).startswith("enc3:")

    def test_encrypting_twice_gives_different_ciphertext(self, key):
        """A fresh salt and nonce per call — identical output would leak that
        two stored secrets are the same value."""
        assert _encrypt_value("same", key) != _encrypt_value("same", key)

    def test_both_still_decrypt_to_the_original(self, key):
        for blob in (_encrypt_value("same", key), _encrypt_value("same", key)):
            assert _decrypt_value(blob, key) == "same"

    def test_an_empty_value_stays_empty(self, key):
        assert _encrypt_value("", key) == ""
        assert _decrypt_value("", key) == ""

    def test_a_wrong_key_does_not_yield_the_plaintext(self, tmp_path):
        """AES-GCM is authenticated, so a wrong key fails rather than returning
        plausible-looking garbage."""
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        blob = _encrypt_value("secret", _get_encryption_key(a))
        assert _decrypt_value(blob, _get_encryption_key(b)) != "secret"

    def test_a_tampered_ciphertext_does_not_decrypt(self, key):
        """The GCM tag is what makes this detectable rather than silently
        returning a corrupted token."""
        blob = _encrypt_value("secret", key)
        raw = bytearray(base64.b64decode(blob[5:]))
        raw[-1] ^= 0xFF
        tampered = "enc3:" + base64.b64encode(bytes(raw)).decode("ascii")
        assert _decrypt_value(tampered, key) != "secret"

    def test_a_truncated_blob_is_handled(self, key):
        assert _decrypt_value("enc3:" + base64.b64encode(b"short").decode("ascii"), key) == ""

    def test_unicode_survives_the_round_trip(self, key):
        assert _decrypt_value(_encrypt_value("令牌-🔑", key), key) == "令牌-🔑"


# ---------------------------------------------------------------------------
# API key lifecycle
# ---------------------------------------------------------------------------

class TestApiKey:
    def test_a_key_is_generated_on_first_read(self, manager):
        key = manager.get_config()["api_key"]
        assert key.startswith("tl_live_")
        assert len(key) > len("tl_live_")

    def test_the_key_is_stable_across_reads(self, manager):
        assert manager.get_config()["api_key"] == manager.get_config()["api_key"]

    def test_the_hardcoded_placeholder_is_replaced(self, manager, tmp_path):
        """A shipped default key would be the same on every install."""
        config = manager.get_config()
        config["api_key"] = "lead-scientist-secure-key-2024"
        manager._save(config)

        assert manager.get_config()["api_key"] != "lead-scientist-secure-key-2024"

    def test_rotation_produces_a_new_key(self, manager):
        before = manager.get_config()["api_key"]
        after = manager.rotate_api_key()
        assert after != before
        assert after.startswith("tl_live_")

    def test_rotation_persists(self, manager, tmp_path):
        rotated = manager.rotate_api_key()
        assert IntegrationsManager(tmp_path).get_config()["api_key"] == rotated

    def test_reveal_returns_the_stored_key(self, manager):
        assert manager.reveal_api_key() == manager.get_config()["api_key"]


# ---------------------------------------------------------------------------
# Webhook configuration
# ---------------------------------------------------------------------------

class TestWebhookConfig:
    def test_stores_a_valid_url_and_threshold(self, manager):
        manager.update_webhook("https://hooks.slack.com/services/T/B/X", 5.0)
        config = manager.get_config()
        assert config["webhook_url"] == "https://hooks.slack.com/services/T/B/X"
        assert config["webhook_threshold"] == 5.0

    def test_rejects_a_url_without_a_scheme(self, manager):
        with pytest.raises(ValueError, match="must start with"):
            manager.update_webhook("hooks.slack.com/services/T/B/X", 1.0)

    def test_rejects_a_private_address(self, manager):
        """SSRF: a webhook pointed at loopback would make the server call
        itself, or reach anything else on the internal network."""
        with pytest.raises(ValueError):
            manager.update_webhook("http://127.0.0.1:8130/api/runs/upload", 1.0)

    def test_clamps_the_threshold_to_a_percentage(self, manager):
        manager.update_webhook("https://hooks.slack.com/services/T/B/X", 500.0)
        assert manager.get_config()["webhook_threshold"] == 100.0

        manager.update_webhook("https://hooks.slack.com/services/T/B/X", -20.0)
        assert manager.get_config()["webhook_threshold"] == 0.0

    def test_an_empty_url_clears_the_webhook(self, manager):
        manager.update_webhook("https://hooks.slack.com/services/T/B/X", 1.0)
        manager.update_webhook("", 1.0)
        assert manager.get_config()["webhook_url"] == ""


# ---------------------------------------------------------------------------
# GitHub OAuth state — the CSRF defence on the callback
# ---------------------------------------------------------------------------

class TestGithubOauthState:
    def test_a_fresh_state_validates(self, manager):
        assert manager.validate_github_state(manager.begin_github_oauth()) is True

    def test_a_wrong_state_is_rejected(self, manager):
        manager.begin_github_oauth()
        assert manager.validate_github_state("not-the-state") is False

    def test_an_empty_state_is_rejected(self, manager):
        manager.begin_github_oauth()
        assert manager.validate_github_state("") is False

    def test_validation_fails_before_any_flow_has_begun(self, manager):
        assert manager.validate_github_state("anything") is False

    def test_an_expired_state_is_rejected(self, manager):
        """Without the TTL an old state stays valid indefinitely, which is
        exactly the replay this check exists to stop."""
        state = manager.begin_github_oauth(ttl_seconds=-1)
        assert manager.validate_github_state(state) is False

    def test_states_are_unpredictable_and_unique(self, manager):
        assert len({manager.begin_github_oauth() for _ in range(20)}) == 20

    def test_starting_a_new_flow_invalidates_the_previous_state(self, manager):
        first = manager.begin_github_oauth()
        manager.begin_github_oauth()
        assert manager.validate_github_state(first) is False


class TestGithubConnection:
    def test_starts_disconnected(self, manager):
        assert manager.github_status()["connected"] is False

    def test_completing_the_flow_records_the_account(self, manager):
        manager.complete_github_oauth(
            "ghp_token", {"login": "kiayen", "avatar_url": "https://a", "html_url": "https://p"},
            ["repo:status"],
        )
        status = manager.github_status()
        assert status["connected"] is True
        assert status["login"] == "kiayen"
        assert status["scopes"] == ["repo:status"]

    def test_the_token_is_not_exposed_by_the_status_view(self, manager):
        """github_status feeds the Integrations page; the token must not ride
        along to the browser."""
        manager.complete_github_oauth("ghp_token", {"login": "x"}, [])
        assert "ghp_token" not in json.dumps(manager.github_status())

    def test_the_token_is_not_stored_in_cleartext(self, manager, tmp_path):
        manager.complete_github_oauth("ghp_supersecret", {"login": "x"}, [])
        raw = (tmp_path / "integrations.json").read_text(encoding="utf-8")
        assert "ghp_supersecret" not in raw

    def test_disconnecting_clears_the_account(self, manager):
        manager.complete_github_oauth("ghp_token", {"login": "x"}, [])
        manager.disconnect_github()
        status = manager.github_status()
        assert status["connected"] is False
        assert status["login"] == ""

    def test_disconnecting_removes_the_stored_token(self, manager, tmp_path):
        manager.complete_github_oauth("ghp_supersecret", {"login": "x"}, [])
        manager.disconnect_github()
        assert "ghp_supersecret" not in (tmp_path / "integrations.json").read_text(encoding="utf-8")


class TestActivityLog:
    def test_records_an_entry(self, manager):
        manager.log_activity("did a thing", branch="main", status="success")
        assert any("did a thing" in json.dumps(e) for e in manager.get_config().get("activity", []))

    def test_the_log_does_not_grow_without_bound(self, manager):
        for i in range(200):
            manager.log_activity(f"event {i}")
        assert len(manager.get_config().get("activity", [])) <= 100
