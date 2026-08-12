from pathlib import Path

import pytest

from visual_regression.baseline_manager import BaselineManager
from visual_regression.config import WorkspacePaths


def test_baseline_versioning_and_details(tmp_path: Path):
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    manager = BaselineManager(paths)

    first_image = tmp_path / "first.png"
    second_image = tmp_path / "second.png"
    first_image.write_bytes(b"first")
    second_image.write_bytes(b"second")

    manager.save_from_image(
        "home",
        first_image,
        {"url": "http://example.test", "updated_by": "Alice", "source": "capture"},
    )
    manager.save_from_image(
        "home",
        second_image,
        {"url": "http://example.test/new", "updated_by": "Bob", "source": "refresh"},
    )

    listing = manager.list_baselines()
    assert listing[0]["version_count"] == 1
    assert listing[0]["thumbnail_href"].endswith("/baseline/home/baseline.webp")
    assert len(listing[0]["history"]) == 2

    details = manager.get_baseline_details("home")
    assert details["current_image_href"].endswith("/baseline/home/baseline.webp")
    assert len(details["versions"]) == 1
    assert details["versions"][0]["image_href"].endswith("/baseline/home/versions/" + details["versions"][0]["version"] + "/baseline.webp")
    assert details["history"][-1]["actor"] == "Bob"


class TestNameLengthLimit:
    """A baseline name becomes a path, so its length is a correctness concern.

    normalize_name neutralised dangerous characters but imposed no length
    limit. A 500-character name passed validation, became a directory name,
    and the capture then failed with OSError(22, 'Invalid argument') once the
    full path exceeded the Windows limit -- deep inside a subprocess, long
    after the point where the name could have been rejected clearly. The
    endpoint surfaced that as a 500.
    """

    def test_a_name_that_would_overflow_the_path_is_rejected(self):
        from visual_regression.baseline_manager import BaselineManager

        with pytest.raises(ValueError, match="too long"):
            BaselineManager.normalize_name("A" * 500)

    def test_the_limit_is_applied_after_normalisation(self):
        """Punctuation collapses to underscores, so the length that matters is
        the normalised one, not what the caller typed."""
        from visual_regression.baseline_manager import BaselineManager

        # 300 separators collapse to a single underscore, leaving a short name.
        assert BaselineManager.normalize_name("home" + ("!" * 300) + "page") == "home_page"

    def test_a_name_at_the_limit_is_accepted(self):
        from visual_regression.baseline_manager import BaselineManager

        name = "a" * BaselineManager.MAX_NAME_LENGTH
        assert BaselineManager.normalize_name(name) == name

    def test_traversal_is_still_neutralised(self):
        """The length check must not have displaced the character filtering."""
        from visual_regression.baseline_manager import BaselineManager

        assert BaselineManager.normalize_name("../../etc/passwd") == "etc_passwd"
