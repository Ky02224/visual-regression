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

    if ai_label in {"missing-element", "layout-shift", "text-truncation", "broken-image", "misaligned-fields"}:
        score += 2
    elif ai_label in {"color-regression", "overlay-obstruction", "unreadable-text"}:
        score += 1

    if score >= 5:
        label = "high"
    elif score >= 3:
        label = "medium"
    else:
        label = "low"
    return {"label": label, "score": score}


def build_ai_explanation(result, ai_assessment: Dict[str, Any]) -> str:
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

    sentence = " ".join([label_sentence, *evidence]).strip()
    return sentence or "No strong defect indicators were detected in this run."


def resolve_ai_model_path(paths: WorkspacePaths, explicit: str | None, no_ai: bool) -> Path | None:
    if no_ai:
        return None
    if explicit:
        return Path(explicit)
    default_path = paths.models_dir / "visual_ai.pt"
    if default_path.exists():
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
    )


def _copy_baseline_into_run(baseline_path: Path, run_dir: Path) -> Path:
    target = run_dir / "baseline.png"
    shutil.copy2(baseline_path, target)
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
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
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
    from .ai_training import assess_result
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

    current_path = run_dir / "current.png"
    if agent_node:
        capture_website_remotely(agent_node, capture_cfg, current_path)
    else:
        capture_website(capture_cfg, current_path, playwright_instance=playwright_instance, browser_instance=browser_instance)

    baseline_image_path = manager.baseline_image_path(case_name)
    result, diff_overlay, binary_diff = compare_images(
        baseline_path=baseline_image_path,
        current_path=current_path,
        pixel_threshold=pixel_threshold,
        min_region_area=min_region_area,
        ignore_regions=active_ignore_regions,
    )

    baseline_for_report = _copy_baseline_into_run(baseline_image_path, run_dir)
    diff_overlay_path = run_dir / "diff_overlay.png"
    binary_diff_path = run_dir / "binary_diff.png"
    report_path = run_dir / "report.html"
    json_path = run_dir / "result.json"

    save_image(diff_overlay_path, diff_overlay)
    save_image(binary_diff_path, binary_diff)

    ai_assessment: Dict[str, Any] = {}
    ai_model_available = bool(ai_model_path and ai_model_path.exists())
    if ai_model_available:
        ai_assessment = assess_result(
            result=result,
            model_path=ai_model_path,
            baseline_image_path=baseline_image_path,
            current_image_path=current_path,
        ).to_dict()

    passed, comparison_decision = decide_pass_fail(
        comparison_mode=comparison_mode,
        mismatch_pct=result.mismatch_pct,
        threshold_pct=threshold_pct,
        ai_assessment=ai_assessment,
        ai_model_available=ai_model_available,
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

    generate_html_report(
        report_path=report_path,
        test_name=case_name,
        baseline_image=Path("baseline.png"),
        current_image=Path("current.png"),
        diff_image=Path("diff_overlay.png"),
        binary_image=Path("binary_diff.png"),
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

    # Integration Hooks
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
                dashboard_url=dashboard_url
                ,
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
            )
            git_sha_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(paths.root),
                capture_output=True,
                text=True,
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

    return passed, report_path, details


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
    from .browser import discover_same_domain_urls

    capture_cfg = make_capture_config(name="crawl-root", args=args, url=args.url)
    urls = discover_same_domain_urls(capture_cfg, page_limit=args.page_limit, preserve_query=args.preserve_query)
    created = 0
    skipped = 0
    failed = 0

    for url in urls:
        baseline_name = _baseline_name_from_capture(url, args.browser, args.device, args.locale)
        try:
            if manager.exists(baseline_name) and not args.overwrite:
                print(f"[SKIP] {baseline_name}: baseline exists")
                skipped += 1
                continue
            item_cfg = make_capture_config(name=baseline_name, args=args, url=url)
            _capture_and_save_baseline(
                manager=manager,
                paths=paths,
                name=baseline_name,
                capture_cfg=item_cfg,
                capture_meta={
                    **build_capture_metadata(item_cfg),
                    "updated_by": args.updated_by,
                    "source": "auto-crawl",
                    "start_url": args.url,
                },
            )
            created += 1
            print(f"[CREATED] {baseline_name} <- {url}")
        except Exception as exc:
            failed += 1
            print(f"[ERROR] {baseline_name}: {exc}")
            if args.fail_fast:
                break

    print(
        f"Create multiple baselines: discovered={len(urls)}, created={created}, skipped={skipped}, failed={failed}, page_limit={args.page_limit}"
    )
    return 0 if failed == 0 else 4


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


def _capture_config_from_case(case: Any, args) -> CaptureConfig:
    return CaptureConfig(
        name=case.name,
        url=case.url,
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

            capture_cfg = _capture_config_from_case(case, args)
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
        res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(project_root), capture_output=True, text=True)
        if res.returncode == 0:
            info["branch"] = res.stdout.strip()
        # sha
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(project_root), capture_output=True, text=True)
        if res.returncode == 0:
            info["sha"] = res.stdout.strip()
        # message
        res = subprocess.run(["git", "log", "-1", "--pretty=%B"], cwd=str(project_root), capture_output=True, text=True)
        if res.returncode == 0:
            info["message"] = res.stdout.strip().split('\n')[0]
        # author
        res = subprocess.run(["git", "log", "-1", "--pretty=%an"], cwd=str(project_root), capture_output=True, text=True)
        if res.returncode == 0:
            info["author"] = res.stdout.strip()
    except Exception:
        pass
    return info


def cmd_run_suite(args, manager: BaselineManager, paths: WorkspacePaths) -> int:
    from .ci_reporter import write_junit_xml
    from .reporter import write_json
    from .suite_runner import load_suite
    from playwright.sync_api import sync_playwright
    from concurrent.futures import ThreadPoolExecutor
    import uuid

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

    # Build creation
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
                    playwright, browser = get_shared_browser()

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
        case_rows = [process_case(c) for c in cases]

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
    except:
        pass

    # Ensure any shared browser started by the CLI is cleaned up
    try:
        from .dashboard_server import close_shared_browser
        close_shared_browser()
    except:
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


def cmd_train_ai(args, paths: WorkspacePaths) -> int:
    from .ai_training import train_model

    metadata = train_model(
        paths=paths,
        model_path=Path(args.model_path) if args.model_path else None,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        samples_per_image=args.samples_per_image,
        pixel_threshold=args.pixel_threshold,
        min_region_area=args.min_region_area,
        pretrained_backbone=not args.no_pretrained,
        dataset_manifest_path=Path(args.dataset_manifest) if args.dataset_manifest else None,
        max_public_images=args.max_public_images,
    )
    print(json.dumps(metadata, indent=2))
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


def cmd_serve_dashboard(args, paths: WorkspacePaths) -> int:
    from .dashboard_server import serve_dashboard

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
    parser.add_argument("--timeout-ms", type=int, default=45000, help="Navigation timeout in milliseconds")
    parser.add_argument("--no-full-page", action="store_true", help="Capture viewport only")
    parser.add_argument("--allow-animations", action="store_true", help="Do not disable CSS animations")
    parser.add_argument("--locale", help="Locale for browser context, example en-US")
    parser.add_argument("--timezone-id", help="Timezone id, example Asia/Kuala_Lumpur")
    parser.add_argument("--color-scheme", default="light", choices=["light", "dark", "no-preference"])
    parser.add_argument("--header", action="append", default=[], help="Extra header in Key:Value format")
    parser.add_argument("--hide-selector", action="append", default=[], help="CSS selector to hide before capture")
    parser.add_argument("--wait-for-selector", help="Wait for selector before taking screenshot")
    parser.add_argument("--updated-by", default="system", help="Actor name recorded in baseline history")


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
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                import json
                from pathlib import Path
                import tempfile
                from .config import CaptureConfig
                from .browser import capture_website
                
                data = json.loads(post_data.decode('utf-8'))
                cfg = CaptureConfig(
                    name=data["name"],
                    url=data["url"],
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
                    out_path = Path(tmpdir) / "screenshot.png"
                    capture_website(cfg, out_path)
                    if out_path.exists():
                        img_bytes = out_path.read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
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

    subparsers.add_parser("list-baselines", help="List existing baselines")
    subparsers.add_parser("list-runs", help="List recorded visual regression runs")

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
    train_parser.add_argument("--no-pretrained", action="store_true", help="Disable ImageNet pretrained weights for ResNet50")
    train_parser.add_argument("--dataset-manifest", help="Path to public dataset manifest created by prepare-public-datasets")
    train_parser.add_argument("--max-public-images", type=int, help="Cap the number of imported public dataset images used for training")

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
    suite_parser.add_argument("--allow-animations", action="store_true")
    suite_parser.add_argument("--fail-fast", action="store_true", help="Stop on first failure/error")
    suite_parser.add_argument("--junit-file", help="Write JUnit XML to this path")
    suite_parser.add_argument("--no-junit", action="store_true", help="Disable JUnit XML output")
    suite_parser.add_argument("--agent-node", action="append", default=[], help="Address of remote agent node(s)")
    add_ai_args(suite_parser)

    agent_parser = subparsers.add_parser("agent", help="Start a distributed capture agent worker")
    agent_parser.add_argument("--host", default="0.0.0.0", help="Host address to bind to")
    agent_parser.add_argument("--port", type=int, default=8140, help="Port to listen on")

    serve_parser = subparsers.add_parser("serve-demo", help="Serve local demo portal")
    serve_parser.add_argument("--site-dir", default="demo_portal")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8123)

    dashboard_parser = subparsers.add_parser("serve-dashboard", help="Serve the website-first decision dashboard")
    dashboard_parser.add_argument("--host", default="127.0.0.1")
    dashboard_parser.add_argument("--port", type=int, default=8130)

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
    if args.command == "generate-pr-comment":
        return cmd_generate_pr_comment(args, paths)
    if args.command == "serve-demo":
        return cmd_serve_demo(args)
    if args.command == "serve-dashboard":
        return cmd_serve_dashboard(args, paths)
    if args.command == "agent":
        return cmd_agent(args)
    raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
