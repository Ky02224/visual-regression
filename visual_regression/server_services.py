from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .baseline_manager import BaselineManager
from .config import WorkspacePaths
from .integrations_manager import IntegrationsManager


def handle_run_upload(
    paths: WorkspacePaths,
    project_root: Path,
    parts: Dict[str, Any],
    github_repo_url: str,
    dashboard_base_url: str,
) -> Dict[str, Any]:
    name = parts.get("name")
    current_image_part = parts.get("current_image")
    
    if not name or not current_image_part:
        raise ValueError("Missing 'name' or 'current_image'")
    
    manager = BaselineManager(paths)
    if not manager.exists(name):
        raise FileNotFoundError(f"Baseline '{name}' does not exist")
    
    image_bytes = current_image_part["content"]
    
    from .cli import (
        _copy_baseline_into_run,
        _slug_part,
        now_stamp_precise,
        summarize_severity,
        build_ai_explanation,
        resolve_ai_model_path,
        build_capture_metadata,
        _initial_decision_status,
    )
    from .image_compare import compare_images, parse_ignore_regions
    from .decision import decide_pass_fail
    from .reporter import generate_html_report, save_image, write_json
    from .ai_training import assess_result
    
    now_str = now_stamp_precise()
    browser_part = _slug_part(parts.get("browser"), "upload-client")
    device_part = _slug_part(parts.get("device"), "desktop")
    locale_part = _slug_part(parts.get("locale"), "default")
    run_name = f"{now_str}_{BaselineManager.normalize_name(name)}_{browser_part}_{device_part}_{locale_part}"
    
    run_dir = paths.runs_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    
    current_path = run_dir / "current.png"
    current_path.write_bytes(image_bytes)
    
    baseline_image_path = manager.baseline_image_path(name)
    
    try:
        threshold_pct = float(parts.get("threshold_pct", 0.1))
    except ValueError:
        threshold_pct = 0.1
    try:
        pixel_threshold = int(parts.get("pixel_threshold", 10))
    except ValueError:
        pixel_threshold = 10
    try:
        min_region_area = int(parts.get("min_region_area", 20))
    except ValueError:
        min_region_area = 20
    comparison_mode = parts.get("comparison_mode", "hybrid")
    no_ai = parts.get("no_ai") == "true"
    ignore_regions_raw = parts.get("ignore_region", "")
    ignore_regions_list = [r.strip() for r in ignore_regions_raw.split(";") if r.strip()] if ignore_regions_raw else []
    ignore_regions = parse_ignore_regions(ignore_regions_list)
    if not ignore_regions:
        try:
            meta = manager.load_metadata(name)
            saved_regions = meta.get("ignore_regions", [])
            for r in saved_regions:
                if isinstance(r, dict):
                    ignore_regions.append((int(r["x"]), int(r["y"]), int(r["width"]), int(r["height"])))
                elif isinstance(r, (list, tuple)) and len(r) == 4:
                    ignore_regions.append((int(r[0]), int(r[1]), int(r[2]), int(r[3])))
        except Exception:
            pass
    
    result, diff_overlay, binary_diff = compare_images(
        baseline_path=baseline_image_path,
        current_path=current_path,
        pixel_threshold=pixel_threshold,
        min_region_area=min_region_area,
        ignore_regions=ignore_regions,
    )
    
    baseline_for_report = _copy_baseline_into_run(baseline_image_path, run_dir)
    diff_overlay_path = run_dir / "diff_overlay.png"
    binary_diff_path = run_dir / "binary_diff.png"
    report_path = run_dir / "report.html"
    json_path = run_dir / "result.json"
    
    save_image(diff_overlay_path, diff_overlay)
    save_image(binary_diff_path, binary_diff)
    
    ai_model_path = resolve_ai_model_path(paths, None, no_ai)
    ai_assessment = {}
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
    
    from .config import CaptureConfig
    mock_cfg = CaptureConfig(
        name=name,
        url="http://upload-api-url",
        browser=parts.get("browser", "upload-client"),
        device=parts.get("device", "desktop"),
        viewport=(1440, 900),
        wait_ms=0,
        wait_until="",
        navigation_timeout_ms=30000,
        full_page=True,
        disable_animations=True,
        locale=parts.get("locale", "default"),
        timezone_id="UTC",
        color_scheme="light",
        extra_headers={},
        hide_selectors=[],
        wait_for_selector=None,
    )
    
    output_payload = {
        "case_name": name,
        "baseline_name": name,
        "suite_name": None,
        "status": "PASS" if passed else "FAIL",
        "threshold_pct": threshold_pct,
        "comparison_decision": comparison_decision,
        "ignore_regions": [list(item) for item in ignore_regions],
        "capture": build_capture_metadata(mock_cfg),
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
        test_name=name,
        baseline_image=Path("baseline.png"),
        current_image=Path("current.png"),
        diff_image=Path("diff_overlay.png"),
        binary_image=Path("binary_diff.png"),
        result=result,
        threshold_pct=threshold_pct,
        ignore_regions=ignore_regions,
        capture=build_capture_metadata(mock_cfg),
        review=decision,
        decision_history=[decision],
        ai_assessment=ai_assessment,
        ai_explanation=ai_explanation,
        severity=severity,
        status=output_payload["status"],
    )
    
    sha = parts.get("sha")
    if sha:
        integrations_manager = IntegrationsManager(paths.root)
        github_config = integrations_manager.get_config().get("github", {})
        if github_config.get("connected"):
            if github_repo_url:
                target_url = f"{dashboard_base_url}/runs"
                state_map = "success" if passed else "failure"
                desc_msg = f"Visual check: {output_payload['status']}. Mismatch: {result.mismatch_pct:.2f}%"
                integrations_manager.post_github_commit_status(
                    repo_url=github_repo_url,
                    sha=sha,
                    state=state_map,
                    target_url=target_url,
                    description=desc_msg
                )
    
    return {
        "ok": True, 
        "passed": passed, 
        "run_id": run_name, 
        "mismatch_pct": result.mismatch_pct, 
        "ai_label": ai_assessment.get("label"),
        "severity": severity.get("label"),
        "report_href": f"/artifacts/{run_name}/report.html"
    }


def handle_ignore_regions_update(
    paths: WorkspacePaths,
    name: str,
    run_id: str,
    ignore_regions: list[Any],
    find_selectors_fn: Any,
    github_repo_url: str,
    dashboard_base_url: str,
) -> Dict[str, Any]:
    manager = BaselineManager(paths)
    manager.save_ignore_regions(name, ignore_regions)

    if run_id:
        run_dir = paths.runs_dir / run_id
        if run_dir.is_dir():
            from .image_compare import compare_images
            from .reporter import save_image, write_json, generate_html_report
            from .decision import decide_pass_fail
            from .ai_training import assess_result
            from .cli import resolve_ai_model_path, _initial_decision_status, summarize_severity, build_ai_explanation
            import json as _json

            result_file = run_dir / "result.json"
            if result_file.exists():
                with open(result_file, "r", encoding="utf-8") as f:
                    run_payload = _json.load(f)

                baseline_path = run_dir / "baseline.png"
                current_path = run_dir / "current.png"
                if baseline_path.exists() and current_path.exists():
                    threshold_pct = float(run_payload.get("threshold_pct", 0.5))
                    pixel_threshold = int(run_payload.get("pixel_threshold") or 20)
                    min_region_area = int(run_payload.get("min_region_area") or 120)
                    capture = run_payload.get("capture") or {}

                    ignore_tuples = []
                    for r in ignore_regions:
                        ignore_tuples.append((int(r["x"]), int(r["y"]), int(r["width"]), int(r["height"])))

                    result, diff_overlay, binary_diff = compare_images(
                        baseline_path=baseline_path,
                        current_path=current_path,
                        pixel_threshold=pixel_threshold,
                        min_region_area=min_region_area,
                        ignore_regions=ignore_tuples
                    )

                    save_image(run_dir / "diff_overlay.png", diff_overlay)
                    save_image(run_dir / "binary_diff.png", binary_diff)

                    no_ai = False
                    ai_model_path = resolve_ai_model_path(paths, None, no_ai)
                    ai_assessment = {}
                    ai_model_available = bool(ai_model_path and ai_model_path.exists())
                    if ai_model_available:
                        try:
                            ai_assessment = assess_result(
                                result=result, model_path=ai_model_path,
                                baseline_image_path=baseline_path,
                                current_image_path=current_path,
                            ).to_dict()
                        except Exception:
                            pass

                    passed, comparison_decision = decide_pass_fail(
                        comparison_mode="hybrid", mismatch_pct=result.mismatch_pct,
                        threshold_pct=threshold_pct, ai_assessment=ai_assessment,
                        ai_model_available=ai_model_available,
                    )

                    run_payload["status"] = "PASS" if passed else "FAIL"
                    run_payload["ignore_regions"] = ignore_regions
                    run_payload["result"] = result.to_dict()
                    run_payload["ai_assessment"] = ai_assessment
                    run_payload["severity"] = summarize_severity(
                        result.mismatch_pct, len(result.regions),
                        ai_assessment.get("score"), ai_assessment.get("label"),
                    )
                    run_payload["ai_explanation"] = build_ai_explanation(result, ai_assessment)

                    write_json(result_file, run_payload)

                    generate_html_report(
                        report_path=run_dir / "report.html",
                        test_name=run_payload.get("case_name", name),
                        baseline_image=Path("baseline.png"),
                        current_image=Path("current.png"),
                        diff_image=Path("diff_overlay.png"),
                        binary_image=Path("binary_diff.png"),
                        result=result,
                        threshold_pct=threshold_pct,
                        ignore_regions=ignore_tuples,
                        capture=capture,
                        review=run_payload.get("decision") or _initial_decision_status(passed),
                        decision_history=run_payload.get("decision_history") or [],
                        ai_assessment=ai_assessment,
                        ai_explanation=run_payload["ai_explanation"],
                        severity=run_payload["severity"],
                        status=run_payload["status"],
                    )

    return {
        "ok": True,
        "ignore_regions": ignore_regions,
        "ignore_css_selectors": []
    }
