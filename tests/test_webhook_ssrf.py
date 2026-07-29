"""Webhook URLs used to have zero host validation — only the http(s) scheme
was checked. Since the server itself makes the outbound POST when a webhook
fires, an admin (or a compromised session) pointing it at the cloud metadata
endpoint (169.254.169.254) would have the server fetch IAM/instance data on
their behalf. Neither the config-save path (update_webhook) nor the actual
fire path (trigger_webhook_detailed) rejected this.
"""
import pytest

from visual_regression.config import WorkspacePaths
from visual_regression.integrations_manager import IntegrationsManager
from visual_regression.notifier import trigger_webhook_detailed, validate_webhook_url


def test_validate_webhook_url_rejects_metadata_ip():
    with pytest.raises(ValueError):
        validate_webhook_url("http://169.254.169.254/latest/meta-data/iam/security-credentials/")


def test_validate_webhook_url_rejects_gcp_metadata_hostname():
    with pytest.raises(ValueError):
        validate_webhook_url("http://metadata.google.internal/computeMetadata/v1/")


def test_validate_webhook_url_allows_normal_https():
    validate_webhook_url("https://hooks.slack.com/services/T00/B00/xxx")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/notify",
        "http://127.0.0.1:8130/notify",
        "http://localhost/notify",
        "http://sub.localhost/notify",
        "http://10.0.0.5/notify",
        "http://172.16.0.5/notify",
        "http://192.168.1.5/notify",
        "http://[::1]/notify",
    ],
)
def test_validate_webhook_url_rejects_private_and_loopback_addresses(url):
    with pytest.raises(ValueError):
        validate_webhook_url(url)


def test_trigger_webhook_detailed_refuses_metadata_ip_without_network_call():
    result = trigger_webhook_detailed("http://169.254.169.254/latest/meta-data/", {"case_name": "demo"})
    assert result["ok"] is False
    assert result["attempts"] == 0


def test_update_webhook_rejects_metadata_ip(tmp_path):
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    manager = IntegrationsManager(paths.root)

    with pytest.raises(ValueError):
        manager.update_webhook("http://169.254.169.254/latest/meta-data/", threshold=5.0)


def test_update_webhook_accepts_normal_url(tmp_path):
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    manager = IntegrationsManager(paths.root)

    manager.update_webhook("https://hooks.slack.com/services/T00/B00/xxx", threshold=5.0)
    config = manager.get_config()
    assert config["webhook_url"] == "https://hooks.slack.com/services/T00/B00/xxx"
