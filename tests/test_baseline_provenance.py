"""Guard the committed baseline set against dev-machine captures.

Chromium renders text differently across platforms and font sets, so a baseline
captured on Windows fails against a Linux CI runner for reasons that have
nothing to do with the page under test. `.gitignore` excludes the generated
workspace but re-includes `.visual-regression/baselines/`, and only `bmk-*` is
carved back out — so every other baseline on a developer's disk is eligible to
be swept in by `git add .`. On this machine that was 111 files.

Baselines now record the platform they were captured on, which turns that from
an invisible mistake into a failing test.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASELINES = ROOT / ".visual-regression" / "baselines"


def _tracked_metadata_files() -> list[Path]:
    """Baseline metadata.json files git actually has under version control."""
    try:
        out = subprocess.run(
            ["git", "ls-files", ".visual-regression/baselines"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git not available")
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return [ROOT / line for line in out.stdout.split() if line.endswith("metadata.json")]


def test_committed_baselines_were_not_captured_on_a_developer_machine():
    tracked = _tracked_metadata_files()
    if not tracked:
        pytest.skip("no committed baselines")

    offenders = []
    for meta_file in tracked:
        if not meta_file.is_file():
            continue
        try:
            payload = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        system = payload.get("system") or {}
        recorded = str(system.get("platform") or "")
        # Baselines committed before provenance was recorded carry no platform.
        # Failing on those would only punish history, so absence is tolerated
        # and it is a wrong, present value that fails.
        if recorded and recorded.lower() != "linux":
            offenders.append(f"{meta_file.relative_to(ROOT)}: captured on {recorded}")

    assert not offenders, (
        "Committed baselines must be captured on Linux, to match the CI runner "
        "that compares against them. Use scripts/generate_linux_baselines.sh.\n  "
        + "\n  ".join(offenders)
    )


def test_new_baselines_record_where_they_were_captured(tmp_path):
    from visual_regression.baseline_manager import BaselineManager
    from visual_regression.config import WorkspacePaths

    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    source = tmp_path / "shot.png"
    # A 1x1 PNG is enough: this asserts on metadata, not on image handling.
    source.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
    ))

    manager = BaselineManager(paths)
    manager.save_from_image(name="provenance-check", source_image_path=source,
                            capture_meta={"url": "http://example.test", "source": "test"})

    meta = json.loads((paths.baselines_dir / "provenance-check" / "metadata.json")
                      .read_text(encoding="utf-8"))
    assert meta["system"]["platform"], "baseline metadata must record its capture platform"
