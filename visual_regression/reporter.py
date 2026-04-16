from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Any, Dict, Sequence

import cv2

from .models import CompareResult


def save_image(path: Path, image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), image)
    if not ok:
        raise ValueError(f"Failed to save image to {path}")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _regions_table_rows(result: CompareResult) -> str:
    if not result.regions:
        return "<tr><td colspan='7'>No changed regions found.</td></tr>"

    rows = []
    for idx, region in enumerate(result.regions, start=1):
        rows.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{region.x}</td>"
            f"<td>{region.y}</td>"
            f"<td>{region.width}</td>"
            f"<td>{region.height}</td>"
            f"<td>{region.area}</td>"
            f"<td>{region.mean_delta}</td>"
            "</tr>"
        )
    return "".join(rows)


def _h(value: Any, default: str = "n/a") -> str:
    text = default if value is None or value == "" else str(value)
    return escape(text, quote=True)


def _artifact_name(value: str | None, fallback: str) -> str:
    return _h(Path(value or fallback).name)


def _metric_card(title: str, value: str) -> str:
    return f"<div class='metric'><strong>{_h(title)}:</strong> {value}</div>"


def _summary_sentence(status: str, severity: Dict[str, Any], ai_assessment: Dict[str, Any], result: CompareResult) -> str:
    if status == "PASS":
        return "This run stayed within the allowed threshold. The captured page is visually close to the baseline."
    severity_label = severity.get("label", "n/a")
    ai_label = ai_assessment.get("label") or "an unspecified change"
    return (
        f"This run failed the visual threshold and is currently marked as {severity_label} severity. "
        f"The AI classifier highlighted the change as {ai_label}, and {len(result.regions)} changed regions were detected."
    )


def _focus_points(result: CompareResult, ai_assessment: Dict[str, Any], severity: Dict[str, Any]) -> str:
    items = []
    if result.mismatch_pct >= 5.0:
        items.append(f"<li>Mismatch is elevated at <strong>{result.mismatch_pct:.4f}%</strong>.</li>")
    if result.regions:
        largest = max(result.regions, key=lambda region: region.area)
        items.append(
            "<li>"
            f"Largest changed region starts at ({largest.x}, {largest.y}) and covers <strong>{largest.area}</strong> pixels."
            "</li>"
        )
    if ai_assessment.get("label"):
        items.append(
            f"<li>AI label: <strong>{_h(ai_assessment.get('label'))}</strong> with score <strong>{_h(ai_assessment.get('score'))}</strong>.</li>"
        )
    if severity.get("label"):
        items.append(f"<li>Severity assessment: <strong>{_h(severity.get('label'))}</strong>.</li>")
    if not items:
        items.append("<li>No strong defect indicators were found in this run.</li>")
    return "".join(items)


def _decision_rows(decision_history: Sequence[Dict[str, Any]]) -> str:
    if not decision_history:
        return "<tr><td colspan='4'>No decision recorded yet.</td></tr>"
    rows = []
    for decision in reversed(list(decision_history)):
        rows.append(
            "<tr>"
            f"<td>{_h(decision.get('status') or 'pending')}</td>"
            f"<td>{_h(decision.get('decider') or decision.get('reviewer') or 'n/a')}</td>"
            f"<td>{_h(decision.get('timestamp') or 'n/a')}</td>"
            f"<td>{_h(decision.get('comment') or '-')}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_html_report_from_payload(report_path: Path, payload: Dict[str, Any]) -> None:
    result = CompareResult.from_dict(payload["result"])
    decision = payload.get("decision") or payload.get("review", {})
    decision_history = list(payload.get("decision_history") or payload.get("review_history") or [])
    if decision and not decision_history:
        decision_history = [decision]
    ai_assessment = payload.get("ai_assessment", {})
    ai_explanation = payload.get("ai_explanation") or "No AI explanation available."
    severity = payload.get("severity", {})
    artifacts = payload.get("artifacts", {})
    capture = payload.get("capture", {})
    threshold_pct = float(payload.get("threshold_pct", 0.0))
    ignore_regions = payload.get("ignore_regions", [])

    status = payload.get("status", "UNKNOWN")
    status_class = "pass" if status == "PASS" else "fail"
    decision_status = decision.get("status", "pending")
    decision_class = "pass" if decision_status in {"approved", "auto-pass"} else ("fail" if decision_status == "rejected" else "pending")
    ssim_text = f"{result.ssim_score:.6f}" if result.ssim_score is not None else "N/A"
    ignore_summary = ", ".join([f"[{x},{y},{w},{h}]" for x, y, w, h in ignore_regions]) or "None"
    locale_text = capture.get("locale") or "default"
    timezone_text = capture.get("timezone_id") or "default"
    ai_text = "Not evaluated"
    if ai_assessment:
        ai_text = (
            f"{ai_assessment.get('label')} "
            f"(score={ai_assessment.get('score')}, threshold={ai_assessment.get('threshold')})"
        )
    severity_text = f"{severity.get('label', 'n/a')} (score={severity.get('score', 'n/a')})"

    summary_text = _summary_sentence(status, severity, ai_assessment, result)
    focus_points = _focus_points(result, ai_assessment, severity)
    current_decider = decision.get("decider") or decision.get("reviewer") or "n/a"
    current_comment = decision.get("comment") or "n/a"
    current_timestamp = decision.get("timestamp") or "n/a"
    case_name = _h(payload.get("case_name"))
    status_text = _h(status)
    decision_status_text = _h(decision_status)
    severity_label = _h(severity.get("label", "n/a"))
    safe_summary = _h(summary_text)
    safe_ai_explanation = _h(ai_explanation)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Visual Regression Report - {case_name}</title>
  <style>
    :root {{
      --bg: #f2f5f8;
      --panel: #ffffff;
      --text: #1f2937;
      --muted: #5b6474;
      --line: #d7dde5;
      --pass-bg: #dcfce7;
      --pass-text: #166534;
      --fail-bg: #fee2e2;
      --fail-text: #991b1b;
      --pending-bg: #fef3c7;
      --pending-text: #92400e;
    }}
    body {{
      margin: 0;
      padding: 24px;
      font-family: "Segoe UI", Tahoma, sans-serif;
      background:
        radial-gradient(circle at top right, rgba(56, 189, 248, 0.08), transparent 22%),
        radial-gradient(circle at bottom left, rgba(14, 165, 233, 0.08), transparent 20%),
        var(--bg);
      color: var(--text);
    }}
    .card {{
      background: var(--panel);
      border-radius: 16px;
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
      padding: 18px;
      margin-bottom: 16px;
      border: 1px solid rgba(215, 221, 229, 0.75);
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }}
    .hero {{
      display: grid;
      gap: 14px;
    }}
    .hero-summary {{
      font-size: 15px;
      color: var(--muted);
      line-height: 1.7;
      margin: 0;
    }}
    .badge {{
      display: inline-block;
      border-radius: 999px;
      padding: 7px 14px;
      font-weight: 700;
      margin-right: 8px;
      margin-bottom: 8px;
    }}
    .pass {{ background: var(--pass-bg); color: var(--pass-text); }}
    .fail {{ background: var(--fail-bg); color: var(--fail-text); }}
    .pending {{ background: var(--pending-bg); color: var(--pending-text); }}
    .images {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 12px;
    }}
    .compare-stack {{
      position: relative;
      overflow: hidden;
    }}
    .compare-stack img {{
      width: 100%;
    }}
    .compare-stack .baseline-layer {{
      position: absolute;
      inset: 0 auto 0 0;
      overflow: hidden;
      width: 50%;
      border-right: 2px solid rgba(12, 92, 134, 0.75);
    }}
    .compare-slider {{
      width: 100%;
      margin-top: 12px;
    }}
    figure {{
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: auto;
      background: #fff;
    }}
    figure figcaption {{
      padding: 10px 12px;
      font-weight: 600;
      border-bottom: 1px solid var(--line);
      background: #fbfcfd;
    }}
    .zoom-wrap {{
      transform-origin: top left;
      width: fit-content;
    }}
    img {{
      display: block;
      max-width: none;
      width: 100%;
      height: auto;
    }}
    .metric {{
      background: #f9fafb;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 12px;
      min-height: 48px;
    }}
    .callout {{
      padding: 14px 16px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #fbfcfd;
    }}
    .callout ul {{
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      line-height: 1.65;
    }}
    .kv {{
      display: grid;
      grid-template-columns: 180px 1fr;
      gap: 8px 12px;
      font-size: 14px;
      color: var(--muted);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 9px 8px;
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="hero">
      <div>
        <h1>Visual Regression Report</h1>
        <div class="badge {status_class}">{status_text}</div>
        <div class="badge {decision_class}">Decision: {decision_status_text}</div>
        <div class="badge pending">Severity: {severity_label}</div>
        <p><strong>Case:</strong> {case_name}</p>
      </div>
      <p class="hero-summary">{safe_summary}</p>
    </div>
    <div class="grid">
      {_metric_card("Mismatch", f"{result.mismatch_pct:.4f}%")}
      {_metric_card("SSIM", ssim_text)}
      {_metric_card("Diff Pixels", f"{result.diff_pixels:,}")}
      {_metric_card("Regions", str(len(result.regions)))}
      {_metric_card("AI Assessment", _h(ai_text))}
      {_metric_card("AI Explanation", safe_ai_explanation)}
      {_metric_card("Severity", _h(severity_text))}
      {_metric_card("Threshold", f"{threshold_pct:.4f}%")}
    </div>
  </div>

  <div class="card">
    <h2>What Needs Attention</h2>
    <div class="callout">
      <ul>{focus_points}</ul>
    </div>
  </div>

  <div class="card">
    <h2>Capture Context</h2>
    <div class="kv">
      <div>URL</div><div>{_h(capture.get("url"))}</div>
      <div>Browser</div><div>{_h(capture.get("browser"))}</div>
      <div>Device</div><div>{_h(capture.get("device") or "none")}</div>
      <div>Locale</div><div>{_h(locale_text)}</div>
      <div>Timezone</div><div>{_h(timezone_text)}</div>
      <div>Color Scheme</div><div>{_h(capture.get("color_scheme") or "light")}</div>
      <div>Ignore Regions</div><div>{_h(ignore_summary, default="None")}</div>
    </div>
  </div>

  <div class="card">
    <h2>Current Decision</h2>
    <div class="kv">
      <div>Status</div><div>{decision_status_text}</div>
      <div>Decider</div><div>{_h(current_decider)}</div>
      <div>Comment</div><div>{_h(current_comment)}</div>
      <div>Decided At</div><div>{_h(current_timestamp)}</div>
    </div>
  </div>

  <div class="card">
    <label for="zoom">Zoom: <span id="zoom-value">100%</span></label>
    <input id="zoom" type="range" min="0.5" max="4" step="0.1" value="1" />
    <label for="compare-slider">Before/After Split: <span id="compare-value">50%</span></label>
    <input id="compare-slider" class="compare-slider" type="range" min="0" max="100" step="1" value="50" />
  </div>

  <div class="card images">
    <figure>
      <figcaption>Before / After Slider</figcaption>
      <div class="zoom-wrap compare-stack">
        <img src="{_artifact_name(artifacts.get("current"), 'current.png')}" alt="current layer" />
        <div class="baseline-layer" id="baseline-layer">
          <img src="{_artifact_name(artifacts.get("baseline"), 'baseline.png')}" alt="baseline layer" />
        </div>
      </div>
    </figure>
    <figure>
      <figcaption>Baseline</figcaption>
      <div class="zoom-wrap"><img src="{_artifact_name(artifacts.get("baseline"), 'baseline.png')}" alt="baseline" /></div>
    </figure>
    <figure>
      <figcaption>Current</figcaption>
      <div class="zoom-wrap"><img src="{_artifact_name(artifacts.get("current"), 'current.png')}" alt="current" /></div>
    </figure>
    <figure>
      <figcaption>Diff Overlay</figcaption>
      <div class="zoom-wrap"><img src="{_artifact_name(artifacts.get("diff_overlay"), 'diff_overlay.png')}" alt="diff" /></div>
    </figure>
    <figure>
      <figcaption>Binary Diff</figcaption>
      <div class="zoom-wrap"><img src="{_artifact_name(artifacts.get("binary_diff"), 'binary_diff.png')}" alt="binary" /></div>
    </figure>
  </div>

  <div class="card">
    <h2>Changed Regions</h2>
    <table>
      <thead>
        <tr>
          <th>#</th><th>X</th><th>Y</th><th>Width</th><th>Height</th><th>Area</th><th>Mean Delta</th>
        </tr>
      </thead>
      <tbody>{_regions_table_rows(result)}</tbody>
    </table>
  </div>

  <div class="card">
    <h2>Decision History</h2>
    <table>
      <thead>
        <tr>
          <th>Status</th><th>Decider</th><th>Timestamp</th><th>Comment</th>
        </tr>
      </thead>
      <tbody>{_decision_rows(decision_history)}</tbody>
    </table>
  </div>

  <script>
    const slider = document.getElementById("zoom");
    const value = document.getElementById("zoom-value");
    const wraps = document.querySelectorAll(".zoom-wrap");
    const compareSlider = document.getElementById("compare-slider");
    const compareValue = document.getElementById("compare-value");
    const baselineLayer = document.getElementById("baseline-layer");
    slider.addEventListener("input", () => {{
      const scale = Number(slider.value);
      value.textContent = `${{Math.round(scale * 100)}}%`;
      wraps.forEach((wrap) => {{
        wrap.style.transform = `scale(${{scale}})`;
      }});
    }});
    compareSlider.addEventListener("input", () => {{
      const amount = Number(compareSlider.value);
      compareValue.textContent = `${{amount}}%`;
      baselineLayer.style.width = `${{amount}}%`;
    }});
  </script>
</body>
</html>
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(html, encoding="utf-8")


def generate_html_report(
    report_path: Path,
    test_name: str,
    baseline_image: Path,
    current_image: Path,
    diff_image: Path,
    binary_image: Path,
    result: CompareResult,
    threshold_pct: float,
    ignore_regions: Sequence[tuple[int, int, int, int]],
    capture: Dict[str, Any] | None = None,
    review: Dict[str, Any] | None = None,
    decision_history: Sequence[Dict[str, Any]] | None = None,
    ai_assessment: Dict[str, Any] | None = None,
    ai_explanation: str | None = None,
    severity: Dict[str, Any] | None = None,
    status: str | None = None,
) -> None:
    payload = {
        "case_name": test_name,
        "status": status or ("PASS" if result.mismatch_pct <= threshold_pct else "FAIL"),
        "threshold_pct": threshold_pct,
        "ignore_regions": [list(item) for item in ignore_regions],
        "capture": capture or {},
        "result": result.to_dict(),
        "decision": review or {},
        "decision_history": list(decision_history or ([] if not review else [review])),
        "ai_assessment": ai_assessment or {},
        "ai_explanation": ai_explanation,
        "severity": severity or {},
        "artifacts": {
            "baseline": str(baseline_image),
            "current": str(current_image),
            "diff_overlay": str(diff_image),
            "binary_diff": str(binary_image),
            "report": str(report_path),
        },
    }
    render_html_report_from_payload(report_path, payload)
