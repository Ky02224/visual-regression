from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Sequence

from .baseline_manager import BaselineManager
from .config import CaptureConfig, WorkspacePaths
from .integrations_manager import IntegrationsManager
from .notifier import format_regression_detected_payload, trigger_webhook_detailed

# On Windows, stdout/stderr default to the legacy console codepage (e.g. cp1252),
# which raises UnicodeEncodeError and crashes the whole process the moment any
# emoji or non-Latin text gets printed (weak-credential warnings, CJK log lines,
# etc). Force UTF-8 with a non-fatal fallback so a stray character never takes
# the CLI down.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass



def parse_viewport(raw: str) -> tuple[int, int]:
    parts = raw.lower().split("x")
    if len(parts) != 2:
        raise ValueError("viewport must be formatted as WIDTHxHEIGHT (example: 1440x900)")
    width, height = int(parts[0]), int(parts[1])
    if width <= 0 or height <= 0:
        raise ValueError("viewport width/height must be > 0")
    return width, height


def parse_headers(values: Sequence[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for item in values:
        if ":" not in item:
            raise ValueError(f"Invalid header '{item}'. Use Header:Value")
        key, value = item.split(":", 1)
        headers[key.strip()] = value.strip()
    return headers


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def now_stamp_precise() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def build_capture_metadata(cfg: CaptureConfig) -> Dict[str, Any]:
    return asdict(cfg)


def summarize_severity(
    mismatch_pct: float,
    diff_regions: int,
    ai_score: float | None,
    ai_label: str | None = None,
) -> Dict[str, Any]:
    score = 0
    if mismatch_pct >= 8.0:
        score += 3
    elif mismatch_pct >= 2.0:
        score += 2
    elif mismatch_pct >= 0.5:
        score += 1

    if diff_regions >= 8:
        score += 2
    elif diff_regions >= 3:
        score += 1

    if ai_score is not None:
        if ai_score >= 0.85:
            score += 2
        elif ai_score >= 0.6:
            score += 1

    if ai_label in {"missing-element", "layout-shift", "text-truncation", "broken-image", "misaligned-fields", "layout-issue", "text-issue"}:
        score += 2
    elif ai_label in {"color-regression", "overlay-obstruction", "unreadable-text", "font-change"}:
        score += 1

    if score >= 5:
        label = "high"
    elif score >= 3:
        label = "medium"
    else:
        label = "low"
    return {"label": label, "score": score}


def build_ai_explanation(result, ai_assessment: Dict[str, Any]) -> str:
    ollama_explanation = ai_assessment.get("ai_explanation")
    if ollama_explanation:
        return ollama_explanation

    ai_label = ai_assessment.get("label")
    score = ai_assessment.get("score")
    threshold = ai_assessment.get("threshold")

    region_count = len(result.regions)
    largest_area = max((region.area for region in result.regions), default=0)

    if not ai_label:
        label_sentence = "The model did not assign a specific defect type."
    else:
        label_sentence = {
            "missing-element": "The model believes an expected UI element is missing.",
            "layout-shift": "The model sees a structural layout movement rather than a small cosmetic change.",
            "color-regression": "The model detected a noticeable color shift compared with the baseline.",
            "text-truncation": "The model detected text that looks clipped or shortened.",
            "overlay-obstruction": "The model detected a dark overlay or obstruction over the original content.",
            "broken-image": "The model detected one or more images that failed to load and appear as broken placeholders.",
            "misaligned-fields": "The model detected form fields or UI elements that are visually misaligned from their expected positions.",
            "unreadable-text": "The model detected text that is unreadable due to low contrast or being obscured by overlapping content.",
            "layout-issue": "The model detected a layout shift or element alignment issue.",
            "text-issue": "The model detected a text truncation or readability issue.",
            "font-change": "The model detected a font family or style change.",
        }.get(ai_label, "The model returned a visual change assessment.")

    evidence: list[str] = []
    if result.mismatch_pct >= 5.0:
        evidence.append(f"Mismatch is elevated at {result.mismatch_pct:.4f}%.")
    elif result.mismatch_pct >= 1.0:
        evidence.append(f"Mismatch is measurable at {result.mismatch_pct:.4f}%.")
    if region_count >= 5:
        evidence.append(f"{region_count} changed regions were found across the page.")
    elif region_count:
        evidence.append(f"{region_count} focused changed regions were found.")
    if largest_area >= 10000:
        evidence.append(f"The largest changed area covers {largest_area} pixels.")
    if score is not None and threshold is not None and float(score) < float(threshold) and ai_label:
        evidence.append("Rule fusion promoted this label because the visual pattern still looked significant.")
    if score is not None:
        evidence.append(f"AI confidence score is {score}.")

    sentence = " ".join([label_sentence, *evidence]).strip()
    return sentence or "No strong defect indicators were detected in this run."


def ai_model_is_available(model_path: Path | None) -> bool:
    """True when a usable model exists at `model_path` in ANY supported format.

    `model_path` is a BASE path — conventionally visual_ai.pt — from which
    _load_legacy_or_hybrid_model derives the sidecars it actually loads:
    .torchscript.pt, then .quant.onnx / .onnx paired with .json, and only then
    the checkpoint itself.

    Testing `model_path.exists()` therefore asked the wrong question. A
    deployment carrying only the ONNX export plus its metadata — which is
    exactly what a CI runner restores, since the 124MB checkpoint is too large
    to version — was reported as having no model at all, and every comparison
    silently degraded to pixel-only with decision_source
    "pixel-fallback-no-model".
    """
    if not model_path:
        return False
    model_path = Path(model_path)
    if model_path.exists():
        return True
    if model_path.with_suffix(".torchscript.pt").exists():
        return True
    # An ONNX export is only usable with its metadata sidecar: class_names,
    # threshold and image_size all come from there.
    if not model_path.with_suffix(".json").exists():
        return False
    return model_path.with_suffix(".quant.onnx").exists() or model_path.with_suffix(".onnx").exists()


def resolve_ai_model_path(paths: WorkspacePaths, explicit: str | None, no_ai: bool) -> Path | None:
    if no_ai:
        return None
    if explicit:
        return Path(explicit)
    default_path = paths.models_dir / "visual_ai.pt"
    # Availability rather than existence: a workspace holding only the ONNX
    # export still has a usable model.
    if ai_model_is_available(default_path):
        return default_path
    return None


def make_capture_config(name: str, args, url: str) -> CaptureConfig:
    return CaptureConfig(
        name=name,
        url=url,
        browser=args.browser,
        device=args.device,
        viewport=parse_viewport(args.viewport),
        wait_ms=args.wait_ms,
        wait_until=args.wait_until,
        navigation_timeout_ms=args.timeout_ms,
        full_page=not args.no_full_page,
        disable_animations=not args.allow_animations,
        locale=args.locale,
        timezone_id=args.timezone_id,
        color_scheme=args.color_scheme,
        extra_headers=parse_headers(args.header),
        hide_selectors=list(args.hide_selector),
        wait_for_selector=args.wait_for_selector,
        login_url=getattr(args, "login_url", None),
        login_username=getattr(args, "login_username", None),
        login_password=getattr(args, "login_password", None),
        username_selector=getattr(args, "username_selector", None),
        password_selector=getattr(args, "password_selector", None),
        submit_selector=getattr(args, "submit_selector", None),
    )


def _copy_baseline_into_run(baseline_path: Path, run_dir: Path) -> Path:
    # Preserve the source's actual format — copying raw bytes from a legacy
    # .png baseline under a .webp name would mislabel them.
    target = run_dir / f"baseline{baseline_path.suffix}"
    shutil.copy2(baseline_path, target)

    # Without this, any re-assessment that reads baseline DOM from the run
    # directory (e.g. handle_ignore_regions_update, which resolves images via
    # resolve_image_path(run_dir, "baseline") rather than the canonical
    # baselines/<name>/ path) silently gets an empty baseline_dom_elements
    # list and falls back to pixel-only classification -- producing a
    # different label from the one recorded at capture time for the exact
    # same pixel diff.
    dom_sidecar = baseline_path.with_suffix(".dom.json")
    if dom_sidecar.exists():
        shutil.copy2(dom_sidecar, target.with_suffix(".dom.json"))

    return target


def capture_website_remotely(agent_url: str, cfg: CaptureConfig, output_path: Path) -> None:
    import urllib.request
    import json
    data = {
        "name": cfg.name,
        "url": cfg.url,
        "browser": cfg.browser,
        "device": cfg.device,
        "viewport": list(cfg.viewport),
        "wait_ms": cfg.wait_ms,
        "wait_until": cfg.wait_until,
        "navigation_timeout_ms": cfg.navigation_timeout_ms,
        "full_page": cfg.full_page,
        "disable_animations": cfg.disable_animations,
        "locale": cfg.locale,
        "timezone_id": cfg.timezone_id,
        "color_scheme": cfg.color_scheme,
        "extra_headers": cfg.extra_headers,
        "hide_selectors": cfg.hide_selectors,
        "wait_for_selector": cfg.wait_for_selector,
        "mock_routes": cfg.mock_routes,
    }
    url = agent_url.rstrip("/") + "/capture"
    headers = {"Content-Type": "application/json"}
    agent_token = os.environ.get("VRT_AGENT_TOKEN")
    if agent_token:
        headers["X-Agent-Token"] = agent_token
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    print(f"[Agent Capture] Delegating capture of '{cfg.name}' to remote agent: {agent_url}", flush=True)
    with urllib.request.urlopen(req, timeout=60) as response:
        if response.status == 200:
            output_path.write_bytes(response.read())
        else:
            raise Exception(f"Agent returned status code {response.status}")


def _capture_and_save_baseline(
    manager: BaselineManager,
    paths: WorkspacePaths,
    name: str,
    capture_cfg: CaptureConfig,
    capture_meta: Dict[str, Any],
    playwright_instance: Any = None,
    browser_instance: Any = None,
    agent_node: str | None = None,
) -> None:
    from .browser import capture_website

    temp_path = paths.root / "tmp" / f"{manager.normalize_name(name)}-{now_stamp()}.png"
    if agent_node:
        capture_website_remotely(agent_node, capture_cfg, temp_path)
        regions = None
    else:
        regions = capture_website(capture_cfg, temp_path, playwright_instance=playwright_instance, browser_instance=browser_instance)
    manager.save_from_image(name=name, source_image_path=temp_path, capture_meta=capture_meta, ignore_regions=regions)
    temp_path.unlink(missing_ok=True)
    temp_path.with_suffix(".dom.json").unlink(missing_ok=True)


def _slug_part(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        text = fallback
    return BaselineManager.normalize_name(text).replace(".", "-")


def _baseline_name_from_capture(url: str, browser: str | None, device: str | None, locale: str | None) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.netloc or "site").replace(":", "_")
    path = parsed.path.strip("/")
    path_part = path.replace("/", "_") if path else "home"
    browser_part = _slug_part(browser, "chromium")
    device_part = _slug_part(device, "desktop")
    locale_part = _slug_part(locale, "default")
    return BaselineManager.normalize_name(f"{host}_{path_part}_{browser_part}_{device_part}_{locale_part}")


def _run_name_for_capture(case_name: str, capture_cfg: CaptureConfig) -> str:
    browser_part = _slug_part(capture_cfg.browser, "chromium")
    device_part = _slug_part(capture_cfg.device, "desktop")
    locale_part = _slug_part(capture_cfg.locale, "default")
    return f"{now_stamp_precise()}_{BaselineManager.normalize_name(case_name)}_{browser_part}_{device_part}_{locale_part}"


def _initial_decision_status(passed: bool) -> Dict[str, Any]:
    if passed:
        return {"status": "auto-pass", "timestamp": datetime.now().isoformat()}
    return {"status": "pending"}


def _run_compare(
    manager: BaselineManager,
    paths: WorkspacePaths,
    case_name: str,
    capture_cfg: CaptureConfig,
    threshold_pct: float,
    pixel_threshold: int,
    min_region_area: int,
    ignore_regions: Sequence[tuple[int, int, int, int]],
    ai_model_path: Path | None,
    suite_name: str | None = None,
    comparison_mode: str = "hybrid",
    playwright_instance: Any = None,
    browser_instance: Any = None,
    build_id: str | None = None,
    agent_node: str | None = None,
) -> tuple[bool, Path, Dict[str, Any]]:
    from .browser import capture_website
    from .decision import decide_pass_fail
    from .image_compare import compare_images
    from .reporter import generate_html_report, save_image, write_json

    if not manager.exists(case_name):
        raise FileNotFoundError(f"Baseline '{case_name}' not found. Create one first.")

    active_ignore_regions = list(ignore_regions)
    if manager.exists(case_name):
        try:
            meta = manager.load_metadata(case_name)
            if "custom_threshold_pct" in meta:
                threshold_pct = float(meta["custom_threshold_pct"])
            if not active_ignore_regions:
                saved_regions = meta.get("ignore_regions", [])
                for r in saved_regions:
                    if isinstance(r, dict):
                        active_ignore_regions.append((int(r["x"]), int(r["y"]), int(r["width"]), int(r["height"])))
                    elif isinstance(r, (list, tuple)) and len(r) == 4:
                        active_ignore_regions.append((int(r[0]), int(r[1]), int(r[2]), int(r[3])))
        except Exception:
            pass

    run_dir = paths.runs_dir / _run_name_for_capture(case_name, capture_cfg)
    run_dir.mkdir(parents=True, exist_ok=True)

    current_path = run_dir / "current.webp"
    if agent_node:
        capture_website_remotely(agent_node, capture_cfg, current_path)
    else:
        capture_website(capture_cfg, current_path, playwright_instance=playwright_instance, browser_instance=browser_instance)

    baseline_image_path = manager.resolve_baseline_image_path(case_name)
    result, diff_overlay, binary_diff = compare_images(
        baseline_path=baseline_image_path,
        current_path=current_path,
        pixel_threshold=pixel_threshold,
        min_region_area=min_region_area,
        ignore_regions=active_ignore_regions,
    )

    baseline_for_report = _copy_baseline_into_run(baseline_image_path, run_dir)
    diff_overlay_path = run_dir / "diff_overlay.webp"
    binary_diff_path = run_dir / "binary_diff.webp"
    report_path = run_dir / "report.html"
    json_path = run_dir / "result.json"

    save_image(diff_overlay_path, diff_overlay)
    save_image(binary_diff_path, binary_diff)

    ai_assessment: Dict[str, Any] = {}
    ai_error = False
    ai_model_available = ai_model_is_available(ai_model_path)
    if ai_model_available:
        from .ai_training import assess_result
        try:
            ai_assessment = assess_result(
                result=result,
                model_path=ai_model_path,
                baseline_image_path=baseline_image_path,
                current_image_path=current_path,
            ).to_dict()
        except Exception as exc:
            ai_error = True
            print(f"[WARN] AI assessment failed ({exc}); falling back to pixel-only decision")

    passed, comparison_decision = decide_pass_fail(
        comparison_mode=comparison_mode,
        mismatch_pct=result.mismatch_pct,
        threshold_pct=threshold_pct,
        ai_assessment=ai_assessment,
        ai_model_available=ai_model_available,
        ai_error=ai_error,
    )
    decision = _initial_decision_status(passed)
    severity = summarize_severity(
        result.mismatch_pct,
        len(result.regions),
        ai_assessment.get("score"),
        ai_assessment.get("label"),
    )
    ai_explanation = build_ai_explanation(result, ai_assessment)

    output_payload = {
        "case_name": case_name,
        "baseline_name": case_name,
        "suite_name": suite_name,
        "build_id": build_id,
        "status": "PASS" if passed else "FAIL",
        "threshold_pct": threshold_pct,
        "comparison_decision": comparison_decision,
        "ignore_regions": [list(item) for item in active_ignore_regions],
        "capture": build_capture_metadata(capture_cfg),
        "result": result.to_dict(),
        "decision": decision,
        "ai_assessment": ai_assessment,
        "ai_explanation": ai_explanation,
        "severity": severity,
        "artifacts": {
            "baseline": str(baseline_for_report),
            "current": str(current_path),
            "diff_overlay": str(diff_overlay_path),
            "binary_diff": str(binary_diff_path),
            "report": str(report_path),
        },
    }
    write_json(json_path, output_payload)

    _upsert_run_to_database(
        paths=paths, run_dir=run_dir, case_name=case_name, suite_name=suite_name,
        passed=passed, result=result, decision=decision, severity=severity,
        ai_assessment=ai_assessment, capture_cfg=capture_cfg, build_id=build_id,
    )

    generate_html_report(
        report_path=report_path,
        test_name=case_name,
        baseline_image=Path("baseline.webp"),
        current_image=Path("current.webp"),
        diff_image=Path("diff_overlay.webp"),
        binary_image=Path("binary_diff.webp"),
        result=result,
        threshold_pct=threshold_pct,
        ignore_regions=ignore_regions,
        capture=build_capture_metadata(capture_cfg),
        review=decision,
        decision_history=[decision],
        ai_assessment=ai_assessment,
        ai_explanation=ai_explanation,
        severity=severity,
        status=output_payload["status"],
    )

    print(f"[{'PASS' if passed else 'FAIL'}] {case_name}")
    print(f"Decision: {comparison_decision.get('decision_source')} ({comparison_decision.get('comparison_mode')})")
    print(f"Mismatch: {result.mismatch_pct:.4f}% (pixel threshold {threshold_pct:.4f}%, pixel_pass={comparison_decision.get('pixel_would_pass')})")
    print(f"Diff regions: {len(result.regions)}")
    if ai_assessment:
        print(f"AI assessment: {ai_assessment.get('label') or 'no meaningful change'}")
    print(f"Severity: {severity['label']}")
    print(f"Report: {report_path}")
    if result.regions:
        print("Changed regions:")
        for idx, region in enumerate(result.regions, start=1):
            print(
                f"  {idx}. x={region.x}, y={region.y}, w={region.width}, h={region.height}, "
                f"area={region.area}, mean_delta={region.mean_delta}"
            )
    print("")
    details: Dict[str, Any] = {
        "mismatch_pct": result.mismatch_pct,
        "threshold_pct": threshold_pct,
        "comparison_mode": comparison_decision.get("comparison_mode"),
        "decision_source": comparison_decision.get("decision_source"),
        "pixel_would_pass": comparison_decision.get("pixel_would_pass"),
        "meaningful_change": comparison_decision.get("meaningful_change"),
        "diff_regions": len(result.regions),
        "report": str(report_path),
        "decision_status": decision["status"],
        "ai_label": ai_assessment.get("label"),
        "ai_score": ai_assessment.get("score"),
        "severity": severity.get("label"),
        "ai_explanation": ai_explanation,
    }

    _trigger_integration_hooks(
        paths=paths, case_name=case_name, run_dir=run_dir, passed=passed,
        result=result, severity=severity, ai_assessment=ai_assessment, capture_cfg=capture_cfg,
    )

    return passed, report_path, details


def _upsert_run_to_database(
    *, paths: WorkspacePaths, run_dir: Path, case_name: str, suite_name: str | None,
    passed: bool, result: Any, decision: Dict[str, Any], severity: Dict[str, Any],
    ai_assessment: Dict[str, Any], capture_cfg: CaptureConfig, build_id: str | None = None,
) -> None:
    """Best-effort upsert of a completed run into the SQLite/Postgres index so it shows up in the dashboard."""
    try:
        from .database import get_store
        store = get_store(paths.db_path)
        run_payload = {
            "run_id": run_dir.name,
            "case_name": case_name,
            "baseline_name": case_name,
            "suite_name": suite_name,
            "build_id": build_id,
            "status": "PASS" if passed else "FAIL",
            "mismatch_pct": result.mismatch_pct,
            "diff_regions": len(result.regions),
            "decision_status": decision["status"],
            "decided_at": decision.get("timestamp") or "",
            "severity_label": severity.get("label") or "",
            "ai_label": ai_assessment.get("label"),
            "browser": capture_cfg.browser,
            "device": capture_cfg.device,
            "locale": capture_cfg.locale,
            "url": capture_cfg.url,
            "report_href": f"/artifacts/{run_dir.name}/report.html",
            "decider": decision.get("reviewer") or decision.get("decider") or "",
            "decision_comment": decision.get("comment") or "",
            "ai_score": ai_assessment.get("score"),
        }
        store.upsert_run_index(run_payload)
    except Exception as db_err:
        print(f"[DB Warning] Failed to upsert run index in database: {db_err}", flush=True)


def _trigger_integration_hooks(
    *, paths: WorkspacePaths, case_name: str, run_dir: Path, passed: bool,
    result: Any, severity: Dict[str, Any], ai_assessment: Dict[str, Any], capture_cfg: CaptureConfig,
) -> None:
    """Best-effort activity log + regression webhook + GitHub commit status for a completed run."""
    try:
        int_manager = IntegrationsManager(paths.root)
        config = int_manager.get_config()

        # Log Activity
        int_manager.log_activity(
            message=f"Visual check: {case_name}",
            status="success" if passed else "failed"
        )

        # Trigger webhook only when a regression is detected.
        webhook_url = config.get("webhook_url")
        if webhook_url and not passed:
            dashboard_url = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8130")
            payload = format_regression_detected_payload(
                run_id=run_dir.name,
                case_name=case_name,
                mismatch=result.mismatch_pct,
                dashboard_url=dashboard_url,
                severity=severity.get("label"),
                browser=capture_cfg.browser,
                device=capture_cfg.device,
                locale=capture_cfg.locale,
                ai_label=ai_assessment.get("label"),
            )
            webhook_result = trigger_webhook_detailed(webhook_url, payload)
            int_manager.log_activity(
                message="Regression webhook sent" if webhook_result.get("ok") else "Regression webhook failed",
                branch="integrations",
                status="success" if webhook_result.get("ok") else "failed",
            )

        # Trigger GitHub commit status if connected
        github_config = config.get("github", {})
        if github_config.get("connected"):
            import subprocess
            git_url_proc = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=str(paths.root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            git_sha_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(paths.root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if git_url_proc.returncode == 0 and git_sha_proc.returncode == 0:
                repo_url = git_url_proc.stdout.strip()
                sha = git_sha_proc.stdout.strip()
                state_map = "success" if passed else "failure"
                desc_msg = f"Visual check: {'PASS' if passed else 'FAIL'}. Mismatch: {result.mismatch_pct:.2f}%"
                target_url = "http://127.0.0.1:8130/runs"
                int_manager.post_github_commit_status(
                    repo_url=repo_url,
                    sha=sha,
                    state=state_map,
                    target_url=target_url,
                    description=desc_msg
                )
    except Exception as e:
        print(f"Integration hook failed: {e}")


def cmd_create_baseline(args, manager: BaselineManager, paths: WorkspacePaths) -> int:
    name = args.name
    if args.image:
        image_path = Path(args.image)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        manager.save_from_image(
            name=name,
            source_image_path=image_path,
            capture_meta={"source": "local-image", "image_path": str(image_path.resolve()), "updated_by": args.updated_by},
        )
        print(f"Baseline '{name}' created from local image.")
        return 0

    if not args.url:
        raise ValueError("create-baseline requires --url unless --image is provided")

    capture_cfg = make_capture_config(name=name, args=args, url=args.url)
    _capture_and_save_baseline(
        manager=manager,
        paths=paths,
        name=name,
        capture_cfg=capture_cfg,
        capture_meta={**build_capture_metadata(capture_cfg), "updated_by": args.updated_by, "source": "website-capture"},
    )
    print(f"Baseline '{name}' created at {manager.baseline_image_path(name)}")
    return 0


def cmd_update_baseline(args, manager: BaselineManager, paths: WorkspacePaths) -> int:
    name = args.name
    if args.image:
        image_path = Path(args.image)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        manager.save_from_image(
            name=name,
            source_image_path=image_path,
            capture_meta={"source": "local-image", "image_path": str(image_path.resolve()), "updated_by": args.updated_by},
        )
        print(f"Baseline '{name}' updated from local image.")
        return 0

    url = args.url
    if not url and manager.exists(name):
        url = manager.load_metadata(name).get("capture", {}).get("url")
    if not url:
        raise ValueError("update-baseline requires --url (or existing baseline metadata with URL)")

    # Load baseline login settings fallback
    baseline_capture = manager.load_metadata(name).get("capture", {}) if manager.exists(name) else {}
    for key in ["login_url", "login_username", "login_password", "username_selector", "password_selector", "submit_selector"]:
        if not getattr(args, key, None):
            setattr(args, key, baseline_capture.get(key))

    capture_cfg = make_capture_config(name=name, args=args, url=url)
    _capture_and_save_baseline(
        manager=manager,
        paths=paths,
        name=name,
        capture_cfg=capture_cfg,
        capture_meta={**build_capture_metadata(capture_cfg), "updated_by": args.updated_by, "source": "website-capture"},
    )
    print(f"Baseline '{name}' updated.")
    return 0


def cmd_create_multiple_baselines(args, manager: BaselineManager, paths: WorkspacePaths) -> int:
    from .browser import discover_same_domain_urls, capture_websites_parallel

    capture_cfg = make_capture_config(name="crawl-root", args=args, url=args.url)
    urls = discover_same_domain_urls(capture_cfg, page_limit=args.page_limit, preserve_query=args.preserve_query)
    created = 0
    skipped = 0
    failed = 0

    # 1. Filter out already existing baselines if not overwriting
    tasks_to_run = [] # List of (url, baseline_name, temp_path, item_cfg)
    for url in urls:
        baseline_name = _baseline_name_from_capture(url, args.browser, args.device, args.locale)
        if manager.exists(baseline_name) and not args.overwrite:
            print(f"[SKIP] {baseline_name}: baseline exists")
            skipped += 1
            continue
        temp_path = paths.root / "tmp" / f"{manager.normalize_name(baseline_name)}-{now_stamp()}.png"
        item_cfg = make_capture_config(name=baseline_name, args=args, url=url)
        tasks_to_run.append((url, baseline_name, temp_path, item_cfg))

    if not tasks_to_run:
        print(
            f"Create multiple baselines: discovered={len(urls)}, created={created}, skipped={skipped}, failed={failed}, page_limit={args.page_limit}"
        )
        return 0

    # 2. Execute captures in parallel
    configs_and_paths = [(task[3], task[2]) for task in tasks_to_run]
    concurrency = getattr(args, "concurrency", 4)
    parallel_results = capture_websites_parallel(configs_and_paths, max_concurrency=concurrency)

    # 3. Save baselines
    for (url, baseline_name, temp_path, item_cfg), (_out_path, regions, error) in zip(tasks_to_run, parallel_results):
        if error is not None:
            failed += 1
            print(f"[ERROR] {baseline_name}: {error}")
            temp_path.unlink(missing_ok=True)
            if args.fail_fast:
                print("Stopped early because --fail-fast was enabled.")
                break
        else:
            try:
                capture_meta = {
                    **build_capture_metadata(item_cfg),
                    "updated_by": args.updated_by,
                    "source": "auto-crawl",
                    "start_url": args.url,
                }
                manager.save_from_image(name=baseline_name, source_image_path=temp_path, capture_meta=capture_meta, ignore_regions=regions)
                created += 1
                print(f"[CREATED] {baseline_name} <- {url}")
            except Exception as exc:
                failed += 1
                print(f"[ERROR] {baseline_name} (Save failed): {exc}")
                if args.fail_fast:
                    print("Stopped early because --fail-fast was enabled.")
                    break
            finally:
                temp_path.unlink(missing_ok=True)

    print(
        f"Create multiple baselines: discovered={len(urls)}, created={created}, skipped={skipped}, failed={failed}, page_limit={args.page_limit}"
    )
    return 0


def cmd_compare(args, manager: BaselineManager, paths: WorkspacePaths) -> int:
    from .image_compare import parse_ignore_regions

    name = args.name
    if not manager.exists(name):
        raise FileNotFoundError(f"Baseline '{name}' does not exist")

    url = args.url
    if not url:
        url = manager.load_metadata(name).get("capture", {}).get("url")
    if not url:
        raise ValueError("compare requires --url or a baseline created from website URL")

    # Load baseline login settings fallback
    baseline_capture = manager.load_metadata(name).get("capture", {})
    for key in ["login_url", "login_username", "login_password", "username_selector", "password_selector", "submit_selector"]:
        if not getattr(args, key, None):
            setattr(args, key, baseline_capture.get(key))

    capture_cfg = make_capture_config(name=name, args=args, url=url)
    ignore_regions = parse_ignore_regions(args.ignore_region)
    ai_model_path = resolve_ai_model_path(paths, args.ai_model, args.no_ai)
    passed, _, _ = _run_compare(
        manager=manager,
        paths=paths,
        case_name=name,
        capture_cfg=capture_cfg,
        threshold_pct=args.threshold_pct,
        pixel_threshold=args.pixel_threshold,
        min_region_area=args.min_region_area,
        ignore_regions=ignore_regions,
        ai_model_path=ai_model_path,
        suite_name=None,
        comparison_mode=args.comparison_mode,
    )
    return 0 if passed else 2


def cmd_compare_matrix(args, manager: BaselineManager, paths: WorkspacePaths) -> int:
    from .image_compare import parse_ignore_regions

    name = args.name
    if not manager.exists(name):
        raise FileNotFoundError(f"Baseline '{name}' does not exist")

    url = args.url
    if not url:
        url = manager.load_metadata(name).get("capture", {}).get("url")
    if not url:
        raise ValueError("compare-matrix requires --url or a baseline created from website URL")

    baseline_capture = manager.load_metadata(name).get("capture", {})
    for key in ["login_url", "login_username", "login_password", "username_selector", "password_selector", "submit_selector"]:
        if not getattr(args, key, None):
            setattr(args, key, baseline_capture.get(key))

    browsers = args.browser or [baseline_capture.get("browser") or "chromium"]
    devices = args.device if args.device else [baseline_capture.get("device")]
    locales = args.locale if args.locale else [baseline_capture.get("locale")]

    normalized_devices = [item if item not in {None, "", "desktop"} else None for item in devices] or [None]
    normalized_locales = [item if item not in {None, ""} else None for item in locales] or [None]
    ignore_regions = parse_ignore_regions(args.ignore_region)
    ai_model_path = resolve_ai_model_path(paths, args.ai_model, args.no_ai)

    total = len(browsers) * len(normalized_devices) * len(normalized_locales)
    print(f"Running {total} comparisons for baseline '{name}'")

    pass_count = 0
    fail_count = 0
    error_count = 0
    for browser in browsers:
        for device in normalized_devices:
            for locale in normalized_locales:
                try:
                    capture_cfg = CaptureConfig(
                        name=name,
                        url=url,
                        browser=browser,
                        device=device,
                        viewport=parse_viewport(args.viewport),
                        wait_ms=args.wait_ms,
                        wait_until=args.wait_until,
                        navigation_timeout_ms=args.timeout_ms,
                        full_page=not args.no_full_page,
                        disable_animations=not args.allow_animations,
                        locale=locale,
                        timezone_id=args.timezone_id,
                        color_scheme=args.color_scheme,
                        extra_headers=parse_headers(args.header),
                        hide_selectors=list(args.hide_selector),
                        wait_for_selector=args.wait_for_selector,
                        login_url=getattr(args, "login_url", None),
                        login_username=getattr(args, "login_username", None),
                        login_password=getattr(args, "login_password", None),
                        username_selector=getattr(args, "username_selector", None),
                        password_selector=getattr(args, "password_selector", None),
                        submit_selector=getattr(args, "submit_selector", None),
                    )
                    passed, _, _ = _run_compare(
                        manager=manager,
                        paths=paths,
                        case_name=name,
                        capture_cfg=capture_cfg,
                        threshold_pct=args.threshold_pct,
                        pixel_threshold=args.pixel_threshold,
                        min_region_area=args.min_region_area,
                        ignore_regions=ignore_regions,
                        ai_model_path=ai_model_path,
                        suite_name=None,
                        comparison_mode=args.comparison_mode,
                    )
                    if passed:
                        pass_count += 1
                    else:
                        fail_count += 1
                except Exception as exc:
                    error_count += 1
                    fail_count += 1
                    print(
                        f"[ERROR] {name} | browser={browser} | device={device or 'desktop'} | locale={locale or 'default'}: {exc}"
                    )
                    if args.fail_fast:
                        print("Stopped early because --fail-fast was enabled.")
                        print(f"Summary: pass={pass_count}, fail={fail_count}, error={error_count}, total={total}")
                        return 4

    print(f"Summary: pass={pass_count}, fail={fail_count}, error={error_count}, total={total}")
    return 0 if fail_count == 0 and error_count == 0 else 2


def _capture_config_from_case(case: Any, args, for_baseline: bool = False) -> CaptureConfig:
    # A case may declare a separate `baseline_url` so the baseline comes from the
    # clean page while the run compares the defective one. Everything else about
    # the capture (viewport, locale, timezone, waits) stays identical, so the only
    # difference between the two images is the injected defect.
    url = case.url
    if for_baseline and getattr(case, "baseline_url", None):
        url = case.baseline_url
    return CaptureConfig(
        name=case.name,
        url=url,
        browser=case.browser,
        device=case.device,
        viewport=case.viewport,
        wait_ms=case.wait_ms,
        wait_until="networkidle",
        navigation_timeout_ms=args.timeout_ms,
        full_page=not args.no_full_page,
        disable_animations=not args.allow_animations,
        locale=case.locale,
        timezone_id=case.timezone_id,
        color_scheme=case.color_scheme,
        extra_headers=case.extra_headers,
        hide_selectors=case.hide_selectors,
        wait_for_selector=case.wait_for_selector,
        login_url=getattr(args, "login_url", None),
        login_username=getattr(args, "login_username", None),
        login_password=getattr(args, "login_password", None),
        username_selector=getattr(args, "username_selector", None),
        password_selector=getattr(args, "password_selector", None),
        submit_selector=getattr(args, "submit_selector", None),
    )


def _run_suite_case(
    case: Any,
    args,
    manager: BaselineManager,
    paths: WorkspacePaths,
    ai_model_path: Path | None,
    playwright_instance: Any = None,
    browser_instance: Any = None,
    build_id: str | None = None,
    agent_node: str | None = None,
) -> tuple[bool, Dict[str, Any]]:
    capture_cfg = _capture_config_from_case(case, args)
    passed, _, details = _run_compare(
        manager=manager,
        paths=paths,
        case_name=case.name,
        capture_cfg=capture_cfg,
        threshold_pct=case.threshold_pct,
        pixel_threshold=case.pixel_threshold,
        min_region_area=case.min_region_area,
        ignore_regions=case.ignore_regions,
        ai_model_path=ai_model_path,
        suite_name=getattr(args, "suite", None),
        comparison_mode=case.comparison_mode,
        playwright_instance=playwright_instance,
        browser_instance=browser_instance,
        build_id=build_id,
        agent_node=agent_node,
    )
    return passed, details


def cmd_create_suite_baselines(args, manager: BaselineManager, paths: WorkspacePaths) -> int:
    from .suite_runner import load_suite

    cases = load_suite(Path(args.suite))
    created = 0
    skipped = 0
    failed = 0

    for case in cases:
        try:
            if manager.exists(case.name) and not args.overwrite:
                print(f"[SKIP] {case.name}: baseline exists (use --overwrite to replace)")
                skipped += 1
                continue

            capture_cfg = _capture_config_from_case(case, args, for_baseline=True)
            _capture_and_save_baseline(
                manager=manager,
                paths=paths,
                name=case.name,
                capture_cfg=capture_cfg,
                capture_meta={**build_capture_metadata(capture_cfg), "updated_by": getattr(args, "updated_by", "system"), "source": "suite-bootstrap"},
            )
            created += 1
            print(f"[CREATED] {case.name}")
        except Exception as exc:
            failed += 1
            print(f"[ERROR] {case.name}: {exc}")
            if args.fail_fast:
                break

    print(f"Suite baseline bootstrap: created={created}, skipped={skipped}, failed={failed}, total={len(cases)}")
    return 0 if failed == 0 else 4


def get_git_info(project_root: Path) -> Dict[str, str]:
    import subprocess
    info = {
        "branch": "main",
        "sha": "unknown",
        "message": "Local comparison run",
        "author": "Local User"
    }
    try:
        # branch
        res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(project_root), capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            info["branch"] = res.stdout.strip()
        # sha
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(project_root), capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            info["sha"] = res.stdout.strip()
        # message
        res = subprocess.run(["git", "log", "-1", "--pretty=%B"], cwd=str(project_root), capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            info["message"] = res.stdout.strip().split('\n')[0]
        # author
        res = subprocess.run(["git", "log", "-1", "--pretty=%an"], cwd=str(project_root), capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            info["author"] = res.stdout.strip()
    except Exception:
        pass
    return info


def _create_suite_build_record(args, paths: WorkspacePaths, write_json) -> str:
    """Create a new build_id, capture git metadata, and write the initial build.json record."""
    import uuid
    build_id = f"build_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    git_info = get_git_info(paths.root.parent)
    build_meta_dir = paths.builds_dir / build_id
    build_meta_dir.mkdir(parents=True, exist_ok=True)
    build_payload = {
        "build_id": build_id,
        "suite_name": Path(args.suite).name,
        "branch": git_info["branch"],
        "commit_sha": git_info["sha"],
        "commit_message": git_info["message"],
        "author": git_info["author"],
        "status": "pending",
        "created_at": int(time.time()),
    }
    write_json(build_meta_dir / "build.json", build_payload)
    return build_id


def cmd_run_suite(args, manager: BaselineManager, paths: WorkspacePaths) -> int:
    from .ci_reporter import write_junit_xml
    from .reporter import write_json
    from .suite_runner import load_suite
    from concurrent.futures import ThreadPoolExecutor

    cases = load_suite(Path(args.suite))
    pass_count = 0
    fail_count = 0
    skip_count = 0
    error_count = 0
    ai_model_path = resolve_ai_model_path(paths, args.ai_model, args.no_ai)

    started_at = datetime.now().isoformat()
    started_perf = time.perf_counter()
    case_rows: list[Dict[str, Any]] = []
    failed_any = False

    build_id = _create_suite_build_record(args, paths, write_json)
    build_meta_dir = paths.builds_dir / build_id

    agent_nodes = getattr(args, "agent_node", []) or []
    case_agents = {}
    if agent_nodes:
        for idx, case in enumerate(cases):
            case_agents[case.name] = agent_nodes[idx % len(agent_nodes)]

    def process_case(case) -> Dict[str, Any]:
        nonlocal failed_any
        if failed_any and getattr(args, "fail_fast", False):
            return {
                "name": case.name,
                "status": "SKIP",
                "message": "Skipped due to fail-fast",
                "mismatch_pct": None,
                "threshold_pct": case.threshold_pct,
                "report": "",
                "duration_seconds": 0.0,
                "decision_status": None,
                "ai_label": None,
                "ai_score": None,
                "severity": None,
                "ai_explanation": None,
            }

        case_started = time.perf_counter()
        row: Dict[str, Any] = {
            "name": case.name,
            "status": "ERROR",
            "message": "",
            "mismatch_pct": None,
            "threshold_pct": case.threshold_pct,
            "report": "",
            "duration_seconds": 0.0,
            "decision_status": None,
            "ai_label": None,
            "ai_score": None,
            "severity": None,
            "ai_explanation": None,
        }

        agent_url = case_agents.get(case.name) if agent_nodes else None

        try:
            if agent_url:
                if not manager.exists(case.name):
                    if not getattr(args, "create_missing_baseline", False):
                        row["status"] = "SKIP"
                        row["message"] = "Missing baseline. Use --create-missing-baseline."
                        print(f"[SKIP] Baseline '{case.name}' missing. Use --create-missing-baseline.")
                        failed_any = True
                        return row

                    capture_cfg = _capture_config_from_case(case, args)
                    _capture_and_save_baseline(
                        manager=manager,
                        paths=paths,
                        name=case.name,
                        capture_cfg=capture_cfg,
                        capture_meta={**build_capture_metadata(capture_cfg), "updated_by": getattr(args, "updated_by", "system"), "source": "suite-auto-create"},
                        agent_node=agent_url,
                    )
                    print(f"[BASELINE CREATED] {case.name} via Agent {agent_url}")

                passed, details = _run_suite_case(
                    case, args, manager, paths, ai_model_path,
                    build_id=build_id,
                    agent_node=agent_url,
                )
                row["status"] = "PASS" if passed else "FAIL"
                row["mismatch_pct"] = details.get("mismatch_pct")
                row["threshold_pct"] = details.get("threshold_pct")
                row["report"] = details.get("report", "")
                row["decision_status"] = details.get("decision_status")
                row["ai_label"] = details.get("ai_label")
                row["ai_score"] = details.get("ai_score")
                row["severity"] = details.get("severity")
                row["ai_explanation"] = details.get("ai_explanation")
                if not passed:
                    failed_any = True
            else:
                try:
                    from .dashboard_server import get_shared_browser
                    playwright, browser = get_shared_browser(getattr(case, "browser", "chromium"))

                    if not manager.exists(case.name):
                        if not getattr(args, "create_missing_baseline", False):
                            row["status"] = "SKIP"
                            row["message"] = "Missing baseline. Use --create-missing-baseline."
                            print(f"[SKIP] Baseline '{case.name}' missing. Use --create-missing-baseline.")
                            failed_any = True
                            return row

                        capture_cfg = _capture_config_from_case(case, args)
                        _capture_and_save_baseline(
                            manager=manager,
                            paths=paths,
                            name=case.name,
                            capture_cfg=capture_cfg,
                            capture_meta={**build_capture_metadata(capture_cfg), "updated_by": getattr(args, "updated_by", "system"), "source": "suite-auto-create"},
                            playwright_instance=playwright,
                            browser_instance=browser,
                        )
                        print(f"[BASELINE CREATED] {case.name}")

                    passed, details = _run_suite_case(
                        case, args, manager, paths, ai_model_path,
                        playwright_instance=playwright,
                        browser_instance=browser,
                        build_id=build_id,
                    )
                    row["status"] = "PASS" if passed else "FAIL"
                    row["mismatch_pct"] = details.get("mismatch_pct")
                    row["threshold_pct"] = details.get("threshold_pct")
                    row["report"] = details.get("report", "")
                    row["decision_status"] = details.get("decision_status")
                    row["ai_label"] = details.get("ai_label")
                    row["ai_score"] = details.get("ai_score")
                    row["severity"] = details.get("severity")
                    row["ai_explanation"] = details.get("ai_explanation")
                    if not passed:
                        failed_any = True
                except Exception as exc:
                    row["status"] = "ERROR"
                    row["message"] = str(exc)
                    failed_any = True
                    print(f"[ERROR] {case.name}: {exc}")
        except Exception as exc:
            row["status"] = "ERROR"
            row["message"] = str(exc)
            failed_any = True
            print(f"[ERROR] {case.name}: {exc}")
        finally:
            row["duration_seconds"] = round(time.perf_counter() - case_started, 4)
        return row

    if agent_nodes:
        max_workers = 4
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            case_rows = list(executor.map(process_case, cases))
    else:
        # --- Parallel async capture for non-agent cases ---
        from .browser import capture_websites_parallel

        # Separate cases that need baseline creation (must be done first, sequentially)
        # from cases that just need capture+compare.
        # For simplicity: collect all (cfg, current_path) pairs for compare, run in parallel,
        # then feed results into the compare pipeline.

        # First pass: handle missing baselines / skip logic sequentially
        pre_rows: dict[str, Dict[str, Any]] = {}  # case.name -> pre-filled row (SKIP/ERROR)
        pending_cases = []  # cases that still need capture+compare
        pending_paths: list[Path] = []
        pending_cfgs: list[CaptureConfig] = []

        for case in cases:
            if failed_any and getattr(args, "fail_fast", False):
                pre_rows[case.name] = {
                    "name": case.name,
                    "status": "SKIP",
                    "message": "Skipped due to fail-fast",
                    "mismatch_pct": None,
                    "threshold_pct": case.threshold_pct,
                    "report": "",
                    "duration_seconds": 0.0,
                    "decision_status": None,
                    "ai_label": None,
                    "ai_score": None,
                    "severity": None,
                    "ai_explanation": None,
                }
                continue

            try:
                from .dashboard_server import get_shared_browser
                playwright_inst, browser_inst = get_shared_browser(getattr(case, "browser", "chromium"))

                if not manager.exists(case.name):
                    if not getattr(args, "create_missing_baseline", False):
                        pre_rows[case.name] = {
                            "name": case.name,
                            "status": "SKIP",
                            "message": "Missing baseline. Use --create-missing-baseline.",
                            "mismatch_pct": None,
                            "threshold_pct": case.threshold_pct,
                            "report": "",
                            "duration_seconds": 0.0,
                            "decision_status": None,
                            "ai_label": None,
                            "ai_score": None,
                            "severity": None,
                            "ai_explanation": None,
                        }
                        failed_any = True
                        print(f"[SKIP] Baseline '{case.name}' missing. Use --create-missing-baseline.")
                        continue

                    cap_cfg = _capture_config_from_case(case, args)
                    try:
                        _capture_and_save_baseline(
                            manager=manager,
                            paths=paths,
                            name=case.name,
                            capture_cfg=cap_cfg,
                            capture_meta={**build_capture_metadata(cap_cfg), "updated_by": getattr(args, "updated_by", "system"), "source": "suite-auto-create"},
                            playwright_instance=playwright_inst,
                            browser_instance=browser_inst,
                        )
                        print(f"[BASELINE CREATED] {case.name}")
                    except Exception as exc:
                        pre_rows[case.name] = {
                            "name": case.name,
                            "status": "ERROR",
                            "message": str(exc),
                            "mismatch_pct": None,
                            "threshold_pct": case.threshold_pct,
                            "report": "",
                            "duration_seconds": 0.0,
                            "decision_status": None,
                            "ai_label": None,
                            "ai_score": None,
                            "severity": None,
                            "ai_explanation": None,
                        }
                        failed_any = True
                        print(f"[ERROR] {case.name}: {exc}")
                        continue

                cap_cfg = _capture_config_from_case(case, args)
                run_dir = paths.runs_dir / _run_name_for_capture(case.name, cap_cfg)
                run_dir.mkdir(parents=True, exist_ok=True)
                current_path = run_dir / "current.webp"
                pending_cases.append(case)
                pending_paths.append(current_path)
                pending_cfgs.append(cap_cfg)
            except Exception as exc:
                pre_rows[case.name] = {
                    "name": case.name,
                    "status": "ERROR",
                    "message": str(exc),
                    "mismatch_pct": None,
                    "threshold_pct": case.threshold_pct,
                    "report": "",
                    "duration_seconds": 0.0,
                    "decision_status": None,
                    "ai_label": None,
                    "ai_score": None,
                    "severity": None,
                    "ai_explanation": None,
                }
                failed_any = True
                print(f"[ERROR] {case.name}: {exc}")

        # Parallel async capture for all pending cases
        if pending_cases:
            parallel_results = capture_websites_parallel(
                list(zip(pending_cfgs, pending_paths)),
                max_concurrency=getattr(args, "workers", 4),
            )
            # parallel_results[i] = (output_path, dynamic_regions, error_or_None)
            for i, (case, cap_cfg, current_path) in enumerate(zip(pending_cases, pending_cfgs, pending_paths)):
                _out_path, _dyn_regions, _exc = parallel_results[i]
                case_started = time.perf_counter()
                row: Dict[str, Any] = {
                    "name": case.name,
                    "status": "ERROR",
                    "message": "",
                    "mismatch_pct": None,
                    "threshold_pct": case.threshold_pct,
                    "report": "",
                    "duration_seconds": 0.0,
                    "decision_status": None,
                    "ai_label": None,
                    "ai_score": None,
                    "severity": None,
                    "ai_explanation": None,
                }
                if _exc is not None:
                    row["message"] = str(_exc)
                    failed_any = True
                    print(f"[ERROR] {case.name} capture failed: {_exc}")
                else:
                    try:
                        from .ai_training import assess_result
                        from .decision import decide_pass_fail
                        from .image_compare import compare_images
                        from .reporter import generate_html_report, save_image, write_json

                        active_ignore = list(case.ignore_regions)
                        try:
                            meta = manager.load_metadata(case.name)
                            if "custom_threshold_pct" in meta:
                                case_threshold = float(meta["custom_threshold_pct"])
                            else:
                                case_threshold = case.threshold_pct
                            if not active_ignore:
                                for r in meta.get("ignore_regions", []):
                                    if isinstance(r, dict):
                                        active_ignore.append((int(r["x"]), int(r["y"]), int(r["width"]), int(r["height"])))
                                    elif isinstance(r, (list, tuple)) and len(r) == 4:
                                        active_ignore.append((int(r[0]), int(r[1]), int(r[2]), int(r[3])))
                        except Exception:
                            case_threshold = case.threshold_pct

                        run_dir = current_path.parent
                        baseline_image_path = manager.resolve_baseline_image_path(case.name)
                        result, diff_overlay, binary_diff = compare_images(
                            baseline_path=baseline_image_path,
                            current_path=current_path,
                            pixel_threshold=case.pixel_threshold,
                            min_region_area=case.min_region_area,
                            ignore_regions=active_ignore,
                        )

                        baseline_for_report = _copy_baseline_into_run(baseline_image_path, run_dir)
                        diff_overlay_path = run_dir / "diff_overlay.webp"
                        binary_diff_path = run_dir / "binary_diff.webp"
                        report_path = run_dir / "report.html"
                        json_path = run_dir / "result.json"

                        save_image(diff_overlay_path, diff_overlay)
                        save_image(binary_diff_path, binary_diff)

                        ai_assessment: Dict[str, Any] = {}
                        ai_error = False
                        ai_model_available = ai_model_is_available(ai_model_path)
                        if ai_model_available:
                            try:
                                ai_assessment = assess_result(
                                    result=result,
                                    model_path=ai_model_path,
                                    baseline_image_path=baseline_image_path,
                                    current_image_path=current_path,
                                ).to_dict()
                            except Exception as ai_exc:
                                ai_error = True
                                print(f"[WARN] AI assessment failed for {case.name} ({ai_exc}); falling back to pixel-only decision")

                        passed, comparison_decision = decide_pass_fail(
                            comparison_mode=case.comparison_mode,
                            mismatch_pct=result.mismatch_pct,
                            threshold_pct=case_threshold,
                            ai_assessment=ai_assessment,
                            ai_model_available=ai_model_available,
                            ai_error=ai_error,
                        )
                        decision = _initial_decision_status(passed)
                        severity = summarize_severity(
                            result.mismatch_pct,
                            len(result.regions),
                            ai_assessment.get("score"),
                            ai_assessment.get("label"),
                        )
                        ai_explanation = build_ai_explanation(result, ai_assessment)

                        output_payload = {
                            "case_name": case.name,
                            "baseline_name": case.name,
                            "suite_name": getattr(args, "suite", None),
                            "build_id": build_id,
                            "status": "PASS" if passed else "FAIL",
                            "threshold_pct": case_threshold,
                            "comparison_decision": comparison_decision,
                            "ignore_regions": [list(item) for item in active_ignore],
                            "capture": build_capture_metadata(cap_cfg),
                            "result": result.to_dict(),
                            "decision": decision,
                            "ai_assessment": ai_assessment,
                            "ai_explanation": ai_explanation,
                            "severity": severity,
                            "artifacts": {
                                "baseline": str(baseline_for_report),
                                "current": str(current_path),
                                "diff_overlay": str(diff_overlay_path),
                                "binary_diff": str(binary_diff_path),
                                "report": str(report_path),
                            },
                        }
                        write_json(json_path, output_payload)
                        _upsert_run_to_database(
                            paths=paths, run_dir=run_dir, case_name=case.name,
                            suite_name=getattr(args, "suite", None), passed=passed,
                            result=result, decision=decision, severity=severity,
                            ai_assessment=ai_assessment, capture_cfg=cap_cfg, build_id=build_id,
                        )
                        generate_html_report(
                            report_path=report_path,
                            test_name=case.name,
                            baseline_image=Path("baseline.webp"),
                            current_image=Path("current.webp"),
                            diff_image=Path("diff_overlay.webp"),
                            binary_image=Path("binary_diff.webp"),
                            result=result,
                            threshold_pct=case_threshold,
                            ignore_regions=case.ignore_regions,
                            capture=build_capture_metadata(cap_cfg),
                            review=decision,
                            decision_history=[decision],
                            ai_assessment=ai_assessment,
                            ai_explanation=ai_explanation,
                            severity=severity,
                            status=output_payload["status"],
                        )

                        print(f"[{'PASS' if passed else 'FAIL'}] {case.name}")
                        print(f"Mismatch: {result.mismatch_pct:.4f}% (threshold {case_threshold:.4f}%)")
                        print(f"Diff regions: {len(result.regions)}")
                        if ai_assessment:
                            print(f"AI assessment: {ai_assessment.get('label') or 'no meaningful change'}")
                        print(f"Severity: {severity['label']}")
                        print(f"Report: {report_path}")
                        print("")

                        row["status"] = "PASS" if passed else "FAIL"
                        row["mismatch_pct"] = result.mismatch_pct
                        row["threshold_pct"] = case_threshold
                        row["report"] = str(report_path)
                        row["decision_status"] = decision["status"]
                        row["ai_label"] = ai_assessment.get("label")
                        row["ai_score"] = ai_assessment.get("score")
                        row["severity"] = severity.get("label")
                        row["ai_explanation"] = ai_explanation
                        if not passed:
                            failed_any = True
                    except Exception as exc:
                        row["message"] = str(exc)
                        failed_any = True
                        print(f"[ERROR] {case.name}: {exc}")
                row["duration_seconds"] = round(time.perf_counter() - case_started, 4)
                pre_rows[case.name] = row

        # Reassemble in original case order
        case_rows = [pre_rows.get(case.name, {
            "name": case.name,
            "status": "ERROR",
            "message": "Unexpected missing result",
            "mismatch_pct": None,
            "threshold_pct": case.threshold_pct,
            "report": "",
            "duration_seconds": 0.0,
            "decision_status": None,
            "ai_label": None,
            "ai_score": None,
            "severity": None,
            "ai_explanation": None,
        }) for case in cases]

    for row in case_rows:
        if row["status"] == "PASS":
            pass_count += 1
        elif row["status"] == "SKIP":
            skip_count += 1
            if "Skipped due to" not in row["message"]:
                fail_count += 1
        elif row["status"] in {"FAIL", "ERROR"}:
            fail_count += 1
            if row["status"] == "ERROR":
                error_count += 1

    # Update build status
    build_payload = json.loads((build_meta_dir / "build.json").read_text(encoding="utf-8"))
    build_payload["status"] = "passed" if fail_count == 0 else "failed"
    build_payload["passed_count"] = pass_count
    build_payload["failed_count"] = fail_count
    build_payload["skipped_count"] = skip_count
    build_payload["error_count"] = error_count
    build_payload["total_count"] = len(case_rows)
    write_json(build_meta_dir / "build.json", build_payload)

    total_elapsed = round(time.perf_counter() - started_perf, 4)
    summary = {
        "suite": str(Path(args.suite).resolve()),
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(),
        "duration_seconds": total_elapsed,
        "passed": pass_count,
        "failed": fail_count,
        "skipped": skip_count,
        "errors": error_count,
        "total": len(case_rows),
        "ai_model": str(ai_model_path) if ai_model_path else None,
        "cases": case_rows,
    }

    summary_path = paths.reports_dir / f"suite-summary-{now_stamp()}.json"
    write_json(summary_path, summary)
    print(f"Suite summary file: {summary_path}")

    if not args.no_junit:
        junit_path = Path(args.junit_file) if args.junit_file else paths.reports_dir / f"suite-junit-{now_stamp()}.xml"
        write_junit_xml(
            output_path=junit_path,
            suite_name=Path(args.suite).stem,
            cases=case_rows,
            elapsed_seconds=total_elapsed,
        )
        print(f"JUnit file: {junit_path}")

    print(
        f"Suite result: passed={pass_count}, failed={fail_count}, "
        f"skipped={skip_count}, errors={error_count}, executed={len(case_rows)}"
    )

    # Integration Log
    try:
        int_manager = IntegrationsManager(paths.root)
        int_manager.log_activity(
            message=f"Suite execution: {Path(args.suite).name}",
            status="success" if fail_count == 0 else "failed"
        )
    except Exception:
        pass

    # Ensure any shared browser started by the CLI is cleaned up
    try:
        from .dashboard_server import close_shared_browser
        close_shared_browser()
    except Exception:
        pass

    return 0 if fail_count == 0 else 3


def cmd_list_baselines(manager: BaselineManager) -> int:
    items = manager.list_baselines()
    if not items:
        print("No baselines found.")
        return 0
    for item in items:
        print(
            f"{item['name']} | url={item.get('url')} | "
            f"created={item.get('created_at')} | updated={item.get('updated_at')}"
        )
    return 0


def cmd_migrate_baselines_to_webp(args, paths: WorkspacePaths) -> int:
    from .migrate_webp import migrate_baselines_to_webp

    dry_run = bool(getattr(args, "dry_run", False))
    if dry_run:
        print("[Migrate] Dry run — no files will be modified.\n")

    results = migrate_baselines_to_webp(paths, dry_run=dry_run)

    total_original = sum(r.get("original_bytes", 0) for r in results["converted"])
    total_new = sum(r.get("new_bytes", 0) for r in results["converted"])

    for r in results["converted"]:
        verb = "Would convert" if dry_run else "Converted"
        saved_pct = (1 - r["new_bytes"] / r["original_bytes"]) * 100 if r.get("original_bytes") else 0
        print(f"[{verb}] {r['path']} ({r['original_bytes']:,}B -> {r['new_bytes']:,}B, -{saved_pct:.0f}%)")

    for r in results["skipped"]:
        if r.get("reason") and r["reason"] != "already .webp":
            print(f"[SKIPPED] {r['path']}: {r['reason']}")

    for r in results["failed"]:
        print(f"[FAILED] {r['path']}: {r.get('reason')}")

    print(
        f"\nMigration summary: converted={len(results['converted'])}, "
        f"skipped={len(results['skipped'])}, failed={len(results['failed'])}"
    )
    if total_original:
        saved_pct = (1 - total_new / total_original) * 100
        print(f"Total size: {total_original:,}B -> {total_new:,}B ({saved_pct:.0f}% smaller){' [dry run, not applied]' if dry_run else ''}")

    return 1 if results["failed"] else 0


def cmd_train_ai(args, paths: WorkspacePaths) -> int:
    """Train a new model into a staging path, then gate deployment on real-run accuracy.

    Training/validation data for this classifier comes mostly from the
    synthetic dataset generator, so a high training accuracy does not by
    itself prove the model generalizes to real website regressions. To
    avoid silently shipping an untested model over a working one, the newly
    trained model is evaluated against actual human-reviewed run pairs
    (evaluate_model_on_runs) before it is promoted to the live model path.
    If no reviewed runs exist yet there is nothing real to gate on, so the
    model deploys with a warning; once reviewed runs accumulate, the gate
    becomes meaningful automatically.
    """
    from .ai_training import train_model, evaluate_model_on_runs

    paths.ensure()
    target_model_path = Path(args.model_path) if args.model_path else (paths.models_dir / "visual_ai.pt")
    staging_model_path = target_model_path.with_name(f"{target_model_path.stem}.staging{target_model_path.suffix}")

    # Clear any leftover staging artifacts from a previous interrupted run.
    for stale in staging_model_path.parent.glob(f"{staging_model_path.stem}.*"):
        stale.unlink(missing_ok=True)

    metadata = train_model(
        paths=paths,
        model_path=staging_model_path,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        samples_per_image=args.samples_per_image,
        pixel_threshold=args.pixel_threshold,
        min_region_area=args.min_region_area,
        pretrained_backbone=not args.no_pretrained,
        dataset_manifest_path=Path(args.dataset_manifest) if args.dataset_manifest else None,
        max_public_images=args.max_public_images,
        force_cpu=args.force_cpu,
        backbone_name=args.backbone,
        dom_dropout=args.dom_dropout,
    )

    real_eval = evaluate_model_on_runs(paths=paths, model_path=staging_model_path)
    real_samples = int(real_eval.get("samples") or 0)
    real_accuracy = real_eval.get("evaluation", {}).get("accuracy")
    metadata["real_run_evaluation"] = real_eval

    gate_passed = True
    gate_message = "No human-reviewed run pairs available yet; deploying without real-data validation."
    if real_samples > 0:
        if real_accuracy is not None and real_accuracy < args.min_real_accuracy:
            gate_passed = False
            gate_message = (
                f"Real-run accuracy {real_accuracy:.2%} on {real_samples} reviewed samples is below "
                f"the required {args.min_real_accuracy:.2%} threshold."
            )
        else:
            gate_message = f"Passed real-run accuracy gate: {real_accuracy:.2%} on {real_samples} reviewed samples."

    metadata["deployment_gate"] = {
        "passed": gate_passed,
        "forced": bool(args.force_deploy) and not gate_passed,
        "message": gate_message,
    }

    if gate_passed or args.force_deploy:
        timestamp = time.strftime("%Y%m%dT%H%M%S")
        staged_files = list(staging_model_path.parent.glob(f"{staging_model_path.stem}.*"))
        for staged_file in staged_files:
            suffix_chain = staged_file.name[len(staging_model_path.stem):]
            target_file = staged_file.with_name(f"{target_model_path.stem}{suffix_chain}")
            if target_file.exists():
                backup_file = target_file.with_name(f"{target_file.name}.bak-{timestamp}")
                shutil.move(str(target_file), str(backup_file))
            shutil.move(str(staged_file), str(target_file))
        print(f"[Deploy] {gate_message}")
    else:
        for staged_file in staging_model_path.parent.glob(f"{staging_model_path.stem}.*"):
            staged_file.unlink(missing_ok=True)
        print(f"[Deploy BLOCKED] {gate_message}")
        print("Re-run with --force-deploy to deploy anyway, or improve training data / lower --min-real-accuracy.")

    print(json.dumps(metadata, indent=2))
    return 0 if gate_passed or args.force_deploy else 1


def cmd_export_onnx(args, paths: WorkspacePaths) -> int:
    from .ai_training import export_to_onnx
    model_path = Path(args.model_path)
    if not model_path.exists():
        print(f"Error: model file not found: {model_path}")
        return 1
    export_to_onnx(model_path)
    return 0


def cmd_prepare_public_datasets(args, paths: WorkspacePaths) -> int:
    from .ai_datasets import build_public_dataset_manifest, save_public_dataset_manifest

    manifest = build_public_dataset_manifest(
        paths=paths,
        webui_dir=Path(args.webui_dir) if args.webui_dir else None,
        rico_dir=Path(args.rico_dir) if args.rico_dir else None,
        screen_annotation_dir=Path(args.screen_annotation_dir) if args.screen_annotation_dir else None,
        max_images_per_source=args.max_images_per_source,
    )
    output = save_public_dataset_manifest(paths, manifest, filename=args.output_name)
    print(json.dumps({"manifest": str(output), **manifest}, indent=2))
    return 0


def cmd_evaluate_ai(args, paths: WorkspacePaths) -> int:
    from .ai_training import evaluate_model_on_runs

    model_path = Path(args.model_path) if args.model_path else paths.models_dir / "visual_ai.pt"
    if not model_path.exists():
        raise FileNotFoundError(f"AI model not found: {model_path}")
    payload = evaluate_model_on_runs(paths=paths, model_path=model_path)
    print(json.dumps(payload, indent=2))
    return 0


def cmd_generate_pr_comment(args, paths: WorkspacePaths) -> int:
    from .pr_commenter import main as run_pr_commenter
    try:
        run_pr_commenter()
        return 0
    except Exception as e:
        print(f"Error generating PR comment: {e}", file=sys.stderr)
        return 1


def cmd_review_run(args, paths: WorkspacePaths) -> int:
    from .review_manager import ReviewManager

    manager = ReviewManager(paths)
    run_dir = manager.resolve_run_dir(args.run)
    decision = manager.save_decision(
        run_dir=run_dir,
        decision=args.decision,
        decider=args.reviewer,
        comment=args.comment,
    )
    print(f"Run decision saved: {run_dir.name}")
    print(json.dumps(decision, indent=2))
    return 0


def cmd_list_runs(paths: WorkspacePaths) -> int:
    from .review_manager import ReviewManager

    manager = ReviewManager(paths)
    items = manager.list_runs()
    if not items:
        print("No runs found.")
        return 0
    for item in items:
        print(
            f"{item['run']} | case={item['case_name']} | status={item['status']} | "
            f"decision={item['decision_status']} | report={item['report']}"
        )
    return 0


def cmd_serve_demo(args) -> int:
    from .demo_server import serve_demo

    site_dir = Path(args.site_dir).resolve()
    if not site_dir.exists():
        raise FileNotFoundError(f"Demo site directory not found: {site_dir}")
    serve_demo(site_dir=site_dir, host=args.host, port=args.port)
    return 0


def _check_and_build_frontend(project_root: Path) -> None:
    frontend_dir = project_root / "dashboard_frontend"
    if not frontend_dir.exists():
        return
    dist_dir = frontend_dir / "dist"
    src_dir = frontend_dir / "src"
    
    should_build = False
    if not dist_dir.exists() or not (dist_dir / "index.html").exists():
        should_build = True
    else:
        try:
            dist_mtime = 0.0
            for p in dist_dir.rglob("*"):
                if p.is_file():
                    dist_mtime = max(dist_mtime, p.stat().st_mtime)
            
            src_mtime = 0.0
            for p in src_dir.rglob("*"):
                if p.is_file():
                    src_mtime = max(src_mtime, p.stat().st_mtime)
            
            if src_mtime > dist_mtime:
                should_build = True
        except Exception:
            pass
            
    if should_build:
        print("[Frontend Builder] Frontend source changed or build output missing — building frontend assets...", flush=True)
        import subprocess
        try:
            subprocess.run("npm run build", shell=True, cwd=str(frontend_dir), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
            print("[Frontend Builder] Frontend build succeeded.", flush=True)
        except Exception as e:
            print(f"[Frontend Builder] Frontend build failed (make sure Node.js is installed and `npm install` has been run in dashboard_frontend): {e}", flush=True)


def cmd_serve_dashboard(args, paths: WorkspacePaths) -> int:
    from .dashboard_server import serve_dashboard

    _check_and_build_frontend(Path.cwd())
    serve_dashboard(project_root=Path.cwd(), paths=paths, host=args.host, port=args.port)
    return 0



def add_common_capture_args(parser: argparse.ArgumentParser, require_url: bool, include_url: bool = True) -> None:
    if include_url:
        parser.add_argument("--url", required=require_url, help="Website URL to capture")
    parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    parser.add_argument("--device", help="Playwright device name (example: iPhone 13)")
    parser.add_argument("--viewport", default="1440x900", help="Viewport format WIDTHxHEIGHT")
    parser.add_argument("--wait-ms", type=int, default=0, help="Extra wait time after load")
    parser.add_argument(
        "--wait-until",
        default="load",
        choices=["load", "domcontentloaded", "networkidle", "commit"],
        help="Playwright navigation wait strategy",
    )
    parser.add_argument("--timeout-ms", type=int, default=15000, help="Navigation timeout in milliseconds")
    parser.add_argument("--no-full-page", action="store_true", help="Capture viewport only")
    parser.add_argument("--allow-animations", action="store_true", help="Do not disable CSS animations")
    parser.add_argument("--locale", help="Locale for browser context, example en-US")
    parser.add_argument("--timezone-id", help="Timezone id, example Asia/Kuala_Lumpur")
    parser.add_argument("--color-scheme", default="light", choices=["light", "dark", "no-preference"])
    parser.add_argument("--header", action="append", default=[], help="Extra header in Key:Value format")
    parser.add_argument("--hide-selector", action="append", default=[], help="CSS selector to hide before capture")
    parser.add_argument("--wait-for-selector", help="Wait for selector before taking screenshot")
    parser.add_argument("--updated-by", default="system", help="Actor name recorded in baseline history")
    parser.add_argument("--login-url", help="URL of the login page to run authentication flow")
    parser.add_argument("--login-username", help="Username for authentication")
    parser.add_argument("--login-password", help="Password for authentication")
    parser.add_argument("--username-selector", help="CSS selector for username input field")
    parser.add_argument("--password-selector", help="CSS selector for password input field")
    parser.add_argument("--submit-selector", help="CSS selector for submit button")


def add_ai_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ai-model", help="Path to trained AI model")
    parser.add_argument("--no-ai", action="store_true", help="Disable AI assessment even if a model exists")
    parser.add_argument(
        "--comparison-mode",
        choices=["pixel", "ai", "hybrid"],
        default="hybrid",
        help="PASS/FAIL source: pixel threshold, AI meaningful-change detection, or both (hybrid)",
    )


from http.server import BaseHTTPRequestHandler

class AgentHTTPHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/capture":
            # This handler drives a real headless browser to whatever URL a
            # caller supplies and streams the rendered page back — without
            # a shared-secret check, any host that can reach this port can
            # use it as an unauthenticated SSRF proxy (e.g. pointing `url`
            # at cloud metadata endpoints or other internal-only services)
            # and get the rendered content back in the response. hmac.
            # compare_digest avoids leaking token length/content via timing.
            import hmac
            expected_token = os.environ.get("VRT_AGENT_TOKEN", "")
            provided_token = self.headers.get("X-Agent-Token", "")
            if not expected_token or not hmac.compare_digest(provided_token, expected_token):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing or invalid X-Agent-Token"}).encode('utf-8'))
                return
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                from pathlib import Path
                import tempfile
                from urllib.parse import urlparse
                from .config import CaptureConfig
                from .browser import capture_website

                data = json.loads(post_data.decode('utf-8'))
                target_url = data["url"]
                if urlparse(target_url).scheme not in ("http", "https"):
                    raise ValueError("url must use http or https scheme")
                cfg = CaptureConfig(
                    name=data["name"],
                    url=target_url,
                    browser=data.get("browser", "chromium"),
                    device=data.get("device"),
                    viewport=tuple(data.get("viewport", (1440, 900))),
                    wait_ms=data.get("wait_ms", 1200),
                    wait_until=data.get("wait_until", "networkidle"),
                    navigation_timeout_ms=data.get("navigation_timeout_ms", 45000),
                    full_page=data.get("full_page", True),
                    disable_animations=data.get("disable_animations", True),
                    locale=data.get("locale"),
                    timezone_id=data.get("timezone_id"),
                    color_scheme=data.get("color_scheme", "light"),
                    extra_headers=data.get("extra_headers", {}),
                    hide_selectors=data.get("hide_selectors", []),
                    wait_for_selector=data.get("wait_for_selector"),
                    mock_routes=data.get("mock_routes", {}),
                )
                
                with tempfile.TemporaryDirectory() as tmpdir:
                    out_path = Path(tmpdir) / "screenshot.webp"
                    capture_website(cfg, out_path)
                    if out_path.exists():
                        img_bytes = out_path.read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/webp")
                        self.send_header("Content-Length", str(len(img_bytes)))
                        self.end_headers()
                        self.wfile.write(img_bytes)
                        return
                    else:
                        raise Exception("Screenshot file was not generated.")
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

def cmd_agent(args) -> int:
    from http.server import HTTPServer
    if not os.environ.get("VRT_AGENT_TOKEN"):
        print(
            "[FATAL] VRT_AGENT_TOKEN is not set. This agent drives a real "
            "browser to any URL a caller supplies, so an unauthenticated "
            "listener is an SSRF risk to anything reachable from this host. "
            "Set VRT_AGENT_TOKEN to a shared secret (matching the value "
            "callers pass via capture_website_remotely/--agent-node) before "
            "starting.",
            flush=True,
        )
        return 1
    server = HTTPServer((args.host, args.port), AgentHTTPHandler)
    print(f"Distributed Capture Agent running at http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="visual-regression",
        description="Website-first visual regression workbench with CLI automation support",
    )
    parser.add_argument("--root", default=".visual-regression", help="Working directory for artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create-baseline", help="Create baseline by name")
    create_parser.add_argument("--name", required=True, help="Baseline name")
    create_parser.add_argument("--image", help="Use local image file instead of website capture")
    add_common_capture_args(create_parser, require_url=False)

    create_multiple_parser = subparsers.add_parser("create-multiple-baselines", help="Auto-crawl one site and create multiple baselines")
    create_multiple_parser.add_argument("--url", required=True, help="Start URL used for baseline crawling")
    create_multiple_parser.add_argument("--page-limit", type=int, default=30, help="Maximum number of pages to capture from the same domain")
    create_multiple_parser.add_argument("--preserve-query", action="store_true", help="Treat different query-string URLs as distinct pages")
    create_multiple_parser.add_argument("--overwrite", action="store_true", help="Replace existing baselines")
    create_multiple_parser.add_argument("--fail-fast", action="store_true", help="Stop on first capture error")
    create_multiple_parser.add_argument("--concurrency", type=int, default=4, help="Maximum concurrent capture processes")
    add_common_capture_args(create_multiple_parser, require_url=False, include_url=False)

    update_parser = subparsers.add_parser("update-baseline", help="Update one baseline only")
    update_parser.add_argument("--name", required=True, help="Baseline name")
    update_parser.add_argument("--image", help="Use local image file instead of website capture")
    add_common_capture_args(update_parser, require_url=False)

    compare_parser = subparsers.add_parser("compare", help="Compare website against one baseline")
    compare_parser.add_argument("--name", required=True, help="Baseline name")
    add_common_capture_args(compare_parser, require_url=False)
    add_ai_args(compare_parser)
    compare_parser.add_argument("--threshold-pct", type=float, default=0.5, help="Fail if mismatch exceeds this")
    compare_parser.add_argument("--pixel-threshold", type=int, default=20, help="Pixel delta threshold (0-255)")
    compare_parser.add_argument("--min-region-area", type=int, default=120, help="Min contour area to report")
    compare_parser.add_argument(
        "--ignore-region",
        action="append",
        default=[],
        help="Ignore area x,y,width,height. Can be used multiple times.",
    )

    compare_matrix_parser = subparsers.add_parser("compare-matrix", help="Run one baseline across multiple browser/device/locale combinations")
    compare_matrix_parser.add_argument("--name", required=True, help="Baseline name")
    compare_matrix_parser.add_argument("--url", help="Website URL to capture")
    compare_matrix_parser.add_argument("--browser", action="append", choices=["chromium", "firefox", "webkit"], default=[])
    compare_matrix_parser.add_argument("--device", action="append", default=[], help="Playwright device name; use desktop by leaving empty")
    compare_matrix_parser.add_argument("--locale", action="append", default=[], help="Locale for browser context")
    compare_matrix_parser.add_argument("--viewport", default="1440x900", help="Viewport format WIDTHxHEIGHT")
    compare_matrix_parser.add_argument("--wait-ms", type=int, default=0)
    compare_matrix_parser.add_argument("--wait-until", default="load", choices=["load", "domcontentloaded", "networkidle", "commit"])
    compare_matrix_parser.add_argument("--timeout-ms", type=int, default=45000)
    compare_matrix_parser.add_argument("--no-full-page", action="store_true")
    compare_matrix_parser.add_argument("--allow-animations", action="store_true")
    compare_matrix_parser.add_argument("--timezone-id")
    compare_matrix_parser.add_argument("--color-scheme", default="light", choices=["light", "dark", "no-preference"])
    compare_matrix_parser.add_argument("--header", action="append", default=[])
    compare_matrix_parser.add_argument("--hide-selector", action="append", default=[])
    compare_matrix_parser.add_argument("--wait-for-selector")
    add_ai_args(compare_matrix_parser)
    compare_matrix_parser.add_argument("--threshold-pct", type=float, default=0.5)
    compare_matrix_parser.add_argument("--pixel-threshold", type=int, default=20)
    compare_matrix_parser.add_argument("--min-region-area", type=int, default=120)
    compare_matrix_parser.add_argument("--fail-fast", action="store_true")
    compare_matrix_parser.add_argument("--ignore-region", action="append", default=[])
    compare_matrix_parser.add_argument("--login-url", help="URL of the login page to run authentication flow")
    compare_matrix_parser.add_argument("--login-username", help="Username for authentication")
    compare_matrix_parser.add_argument("--login-password", help="Password for authentication")
    compare_matrix_parser.add_argument("--username-selector", help="CSS selector for username input field")
    compare_matrix_parser.add_argument("--password-selector", help="CSS selector for password input field")
    compare_matrix_parser.add_argument("--submit-selector", help="CSS selector for submit button")

    subparsers.add_parser("list-baselines", help="List existing baselines")
    subparsers.add_parser("list-runs", help="List recorded visual regression runs")

    migrate_webp_parser = subparsers.add_parser(
        "migrate-baselines-to-webp",
        help="One-time migration: convert legacy .png baseline images (and archived versions) to .webp",
    )
    migrate_webp_parser.add_argument("--dry-run", action="store_true", help="Preview what would be converted without touching any files")

    review_parser = subparsers.add_parser("review-run", help="Approve or reject one run")
    review_parser.add_argument("--run", required=True, help="Run directory path or run id")
    review_parser.add_argument("--decision", required=True, choices=["approved", "rejected"])
    review_parser.add_argument("--reviewer", required=True, help="Decider name")
    review_parser.add_argument("--comment", default="", help="Optional decision comment")

    train_parser = subparsers.add_parser("train-ai", help="Train ResNet50 Siamese + rule-fusion visual classifier")
    train_parser.add_argument("--model-path", help="Output model path")
    train_parser.add_argument("--epochs", type=int, default=30)
    train_parser.add_argument("--batch-size", type=int, default=32)
    train_parser.add_argument("--learning-rate", type=float, default=0.001)
    train_parser.add_argument("--samples-per-image", type=int, default=16)
    train_parser.add_argument("--pixel-threshold", type=int, default=20)
    train_parser.add_argument("--min-region-area", type=int, default=120)
    train_parser.add_argument("--dom-dropout", type=float, default=0.0,
                              help="Fraction of training samples whose DOM/structural features are zeroed, teaching the model the screenshot-only case")
    train_parser.add_argument("--no-pretrained", action="store_true", help="Disable ImageNet pretrained weights for ResNet50")
    train_parser.add_argument("--dataset-manifest", help="Path to public dataset manifest created by prepare-public-datasets")
    train_parser.add_argument("--max-public-images", type=int, help="Cap the number of imported public dataset images used for training")
    train_parser.add_argument("--force-cpu", action="store_true", help="Force CPU training even if CUDA is available")
    train_parser.add_argument("--backbone", default="resnet50", choices=["resnet50", "efficientnet_b3"], help="Backbone model to use for feature extraction")
    train_parser.add_argument("--min-real-accuracy", type=float, default=0.5, help="Minimum accuracy required on real human-reviewed run pairs before the new model replaces the deployed one (ignored if no reviewed runs exist yet)")
    train_parser.add_argument("--force-deploy", action="store_true", help="Deploy the newly trained model even if it fails the real-run accuracy gate")

    dataset_parser = subparsers.add_parser(
        "prepare-public-datasets",
        help="Scan local WebUI/RICO/Screen Annotation directories and build a dataset manifest for AI training",
    )
    dataset_parser.add_argument("--webui-dir", help="Path to extracted WebUI screenshots directory")
    dataset_parser.add_argument("--rico-dir", help="Path to extracted RICO screenshots directory")
    dataset_parser.add_argument("--screen-annotation-dir", help="Path to extracted Screen Annotation image directory")
    dataset_parser.add_argument("--max-images-per-source", type=int, default=250, help="Limit imported screenshots per public source")
    dataset_parser.add_argument("--output-name", default="public-ui-manifest.json", help="Manifest filename written under .visual-regression/datasets")

    eval_parser = subparsers.add_parser("evaluate-ai", help="Evaluate the trained AI model against stored run data")
    eval_parser.add_argument("--model-path", help="Path to model to evaluate")

    export_onnx_parser = subparsers.add_parser("export-onnx", help="Export PyTorch model weights to ONNX format")
    export_onnx_parser.add_argument("--model-path", required=True, help="Path to input PyTorch (.pt) model file")

    subparsers.add_parser("generate-pr-comment", help="Generate a markdown comment summarizing visual regression results for GitHub Pull Requests")

    suite_bootstrap_parser = subparsers.add_parser(
        "create-suite-baselines",
        help="Create baselines for all test cases in suite yaml",
    )
    suite_bootstrap_parser.add_argument("--suite", required=True, help="Path to suite yaml")
    suite_bootstrap_parser.add_argument("--overwrite", action="store_true", help="Replace existing baselines")
    suite_bootstrap_parser.add_argument("--timeout-ms", type=int, default=45000)
    suite_bootstrap_parser.add_argument("--no-full-page", action="store_true")
    suite_bootstrap_parser.add_argument("--allow-animations", action="store_true")
    suite_bootstrap_parser.add_argument("--fail-fast", action="store_true", help="Stop on first error")
    suite_bootstrap_parser.add_argument("--updated-by", default="system", help="Actor name recorded in baseline history")

    suite_parser = subparsers.add_parser("run-suite", help="Run visual tests from YAML suite")
    suite_parser.add_argument("--suite", required=True, help="Path to suite yaml")
    suite_parser.add_argument("--create-missing-baseline", action="store_true", help="Auto create missing baseline")
    suite_parser.add_argument("--timeout-ms", type=int, default=45000)
    suite_parser.add_argument("--no-full-page", action="store_true")
    suite_parser.add_argument("--workers", type=int, default=4, help="Maximum concurrent browser contexts")
    suite_parser.add_argument("--allow-animations", action="store_true")
    suite_parser.add_argument("--fail-fast", action="store_true", help="Stop on first failure/error")
    suite_parser.add_argument("--junit-file", help="Write JUnit XML to this path")
    suite_parser.add_argument("--no-junit", action="store_true", help="Disable JUnit XML output")
    suite_parser.add_argument("--agent-node", action="append", default=[], help="Address of remote agent node(s)")
    add_ai_args(suite_parser)

    agent_parser = subparsers.add_parser("agent", help="Start a distributed capture agent worker")
    agent_parser.add_argument("--host", default="127.0.0.1", help="Host address to bind to (use 0.0.0.0 only behind a trusted network/firewall — this endpoint drives a real browser to caller-supplied URLs)")
    agent_parser.add_argument("--port", type=int, default=8140, help="Port to listen on")

    serve_parser = subparsers.add_parser("serve-demo", help="Serve local demo portal")
    serve_parser.add_argument("--site-dir", default="demo_portal")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8123)

    dashboard_parser = subparsers.add_parser("serve-dashboard", help="Serve the website-first decision dashboard")
    dashboard_parser.add_argument("--host", default="127.0.0.1")
    dashboard_parser.add_argument("--port", type=int, default=8130)

    ci_parser = subparsers.add_parser("check-ci", help="CI/CD Gatekeeper: fail build if high/critical visual defects exist")
    ci_parser.add_argument("--max-severity", default="high", choices=["low", "medium", "high", "critical"], help="Severity threshold to block CI build")
    ci_parser.add_argument("--viewports", default="desktop", help="User selected device viewports (desktop,tablet,mobile)")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    paths = WorkspacePaths(root=Path(args.root))
    paths.ensure()
    manager = BaselineManager(paths)

    if args.command == "create-baseline":
        return cmd_create_baseline(args, manager, paths)
    if args.command == "create-multiple-baselines":
        return cmd_create_multiple_baselines(args, manager, paths)
    if args.command == "update-baseline":
        return cmd_update_baseline(args, manager, paths)
    if args.command == "compare":
        return cmd_compare(args, manager, paths)
    if args.command == "compare-matrix":
        return cmd_compare_matrix(args, manager, paths)
    if args.command == "run-suite":
        return cmd_run_suite(args, manager, paths)
    if args.command == "create-suite-baselines":
        return cmd_create_suite_baselines(args, manager, paths)
    if args.command == "list-baselines":
        return cmd_list_baselines(manager)
    if args.command == "migrate-baselines-to-webp":
        return cmd_migrate_baselines_to_webp(args, paths)
    if args.command == "list-runs":
        return cmd_list_runs(paths)
    if args.command == "review-run":
        return cmd_review_run(args, paths)
    if args.command == "train-ai":
        return cmd_train_ai(args, paths)
    if args.command == "prepare-public-datasets":
        return cmd_prepare_public_datasets(args, paths)
    if args.command == "evaluate-ai":
        return cmd_evaluate_ai(args, paths)
    if args.command == "export-onnx":
        return cmd_export_onnx(args, paths)
    if args.command == "generate-pr-comment":
        return cmd_generate_pr_comment(args, paths)
    if args.command == "serve-demo":
        return cmd_serve_demo(args)
    if args.command == "serve-dashboard":
        return cmd_serve_dashboard(args, paths)
    if args.command == "check-ci":
        return cmd_check_ci(args, paths)
    if args.command == "agent":
        return cmd_agent(args)
    raise ValueError(f"Unknown command: {args.command}")


def cmd_check_ci(args: argparse.Namespace, paths: WorkspacePaths) -> int:
    """CI/CD Gatekeeper command: Fails with exit code 1 if critical/high visual defects exist."""
    print("=================================================================", flush=True)
    print("=== VISUAL AI REGRESSION CI/CD GATEKEEPER INSPECTION ===", flush=True)
    print("=================================================================", flush=True)
    max_severity = (getattr(args, "max_severity", "high") or "high").lower()
    severity_order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    threshold_level = severity_order.get(max_severity, 3)

    runs_dir = paths.runs_dir
    if not runs_dir.exists():
        print("[CI Gatekeeper] No test runs directory found. Passing CI check (0).", flush=True)
        return 0

    # Ordered by name, not mtime. Run directories are named
    # <UTC timestamp>_<case>, so the name already carries the ordering, and it
    # carries it at a resolution the filesystem does not have to agree with.
    # Sorting by st_mtime made the gate non-deterministic wherever two runs
    # landed in the same filesystem tick: ext4 on the CI runner reports whole
    # seconds for files a suite writes milliseconds apart, so ties broke in
    # directory order and the newest build was sometimes not the one picked.
    # Observed as an intermittent failure of
    # test_ignores_runs_from_a_different_build, which passes on Windows (100ns
    # timestamps, no ties) and failed on Linux — the gate reading a stale
    # build's FAIL and blocking a build that was green.
    run_dirs = sorted([d for d in runs_dir.iterdir() if d.is_dir()], key=lambda p: p.name, reverse=True)
    if not run_dirs:
        print("[CI Gatekeeper] No test runs recorded. Passing CI check (0).", flush=True)
        return 0

    def _load_result(run_dir: Path) -> Dict[str, Any] | None:
        result_json = run_dir / "result.json"
        if not result_json.exists():
            return None
        try:
            return json.loads(result_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    latest_data = _load_result(run_dirs[0])
    if latest_data is None:
        print(f"[CI Gatekeeper] No result.json found in {run_dirs[0].name}. Passing CI (0).", flush=True)
        return 0

    # A suite run produces one run directory per case, all sharing the same
    # build_id — gate on every run in that build, not just whichever run
    # directory happened to be modified last (a run-suite with N parallel
    # capture workers can finish any case last, so that single directory is
    # not representative of the whole build's result).
    build_id = latest_data.get("build_id")
    build_runs = [latest_data]
    if build_id:
        for run_dir in run_dirs[1:]:
            data = _load_result(run_dir)
            if data is not None and data.get("build_id") == build_id:
                build_runs.append(data)

    found_high_severity = False

    # result.json stores a single "severity" dict per run (see
    # summarize_severity), not an "assessments" list — that key is never
    # written anywhere, so reading it always yielded an empty list and this
    # gate silently passed every build regardless of actual severity.
    for data in build_runs:
        severity = data.get("severity") or {}
        sev = str(severity.get("label") or "low").lower()
        level = severity_order.get(sev, 1)
        label = (data.get("ai_assessment") or {}).get("label") or "unknown"
        # `status` is the actual, authoritative pass/fail outcome from
        # decide_pass_fail — e.g. a DOM-diff-confirmed defect with a small
        # pixel footprint (real, but affecting few pixels) can legitimately
        # score as "medium" severity under summarize_severity's heuristic
        # scoring, which sits below the default "high" --max-severity
        # threshold. Gating purely on the severity heuristic while ignoring
        # `status` means a run the platform itself already confirmed as a
        # real regression can still silently pass this gate — the actual
        # mechanism real CI pipelines call to decide whether to block a
        # deploy. A FAIL always blocks here regardless of severity; the
        # severity threshold only widens blocking to runs that passed their
        # own comparison but are still judged severe enough to flag.
        if str(data.get("status") or "").upper() == "FAIL":
            found_high_severity = True
            print(f"[CI BLOCKER] Detected a failed comparison: '{label}' in {data.get('case_name', 'run')}", flush=True)
        elif level >= threshold_level:
            found_high_severity = True
            print(f"[CI BLOCKER] Detected {sev.upper()} severity defect: '{label}' in {data.get('case_name', 'run')}", flush=True)

    if found_high_severity:
        print("\n[CI BLOCK] BUILD FAILED: Visual Regression CI Gatekeeper blocked the build due to severe UI defects!", flush=True)
        return 1
    
    print("\n[CI PASS] BUILD PASSED: All visual regression assessments passed safety threshold.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
