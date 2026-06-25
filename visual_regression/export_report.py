from __future__ import annotations
import base64
import json
from pathlib import Path
from html import escape
from typing import Any, Dict


def _img_to_b64(path: Path) -> str:
    """Read an image file and return a base64 data URI."""
    if not path.exists():
        return ""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def generate_standalone_report(run_dir: Path) -> str:
    """Generate a single, self-contained HTML file for a run directory.
    All images are base64-inlined. No external dependencies required.
    Returns the full HTML string.
    """
    json_path = run_dir / "result.json"
    if not json_path.exists():
        raise FileNotFoundError(f"result.json not found in {run_dir}")

    payload: Dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))

    baseline_b64 = _img_to_b64(run_dir / "baseline.png")
    current_b64 = _img_to_b64(run_dir / "current.png")
    diff_b64 = _img_to_b64(run_dir / "diff_overlay.png")

    status = payload.get("status", "UNKNOWN")
    case_name = escape(str(payload.get("case_name") or payload.get("baseline_name") or run_dir.name))
    result = payload.get("result") or {}
    mismatch = result.get("mismatch_pct", 0)
    diff_px = result.get("diff_pixels", 0)
    ssim = result.get("ssim_score")
    regions = result.get("regions", [])
    ai = payload.get("ai_assessment") or {}
    ai_label = escape(str(ai.get("label") or "—"))
    ai_score = ai.get("score")
    severity = payload.get("severity") or {}
    severity_label = escape(str(severity.get("label") or "—"))
    capture = payload.get("capture") or {}
    decision = payload.get("decision") or {}
    decision_status = escape(str(decision.get("status") or "pending"))
    run_id = escape(run_dir.name)

    status_color = "#22c55e" if status == "PASS" else "#ef4444"
    status_bg = "#f0fdf4" if status == "PASS" else "#fef2f2"

    # Build regions table rows
    region_rows = ""
    sorted_regions = sorted(regions, key=lambda r: r.get("area", 0) * r.get("mean_delta", 0), reverse=True)
    for i, r in enumerate(sorted_regions, 1):
        area = r.get("area", 0)
        delta = r.get("mean_delta", 0)
        score = area * delta
        if score > 40000 or delta > 120 or area > 80000:
            badge = '<span style="background:#fef2f2;color:#dc2626;border:1px solid #fca5a5;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:600">Critical</span>'
        elif score > 4000 or delta > 30 or area > 10000:
            badge = '<span style="background:#fffbeb;color:#d97706;border:1px solid #fcd34d;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:600">Warning</span>'
        else:
            badge = '<span style="background:#eff6ff;color:#2563eb;border:1px solid #93c5fd;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:600">Low</span>'
        region_rows += f"<tr><td>{i}</td><td>{badge}</td><td>[{r.get('x',0)}, {r.get('y',0)}]</td><td>{r.get('width',0)}×{r.get('height',0)}</td><td>{area:,}</td><td>{delta:.1f}</td></tr>\n"

    if not region_rows:
        region_rows = "<tr><td colspan='6' style='text-align:center;color:#6b7280'>No changed regions detected</td></tr>"

    ssim_str = f"{ssim:.4f}" if ssim is not None else "—"
    ai_score_str = f"{ai_score:.3f}" if ai_score is not None else "—"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Visual Regression Report — {case_name}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f8fafc; color: #1e293b; line-height: 1.6; }}
  .header {{ background: #0f172a; color: white; padding: 24px 32px; display: flex; align-items: center; gap: 16px; }}
  .header h1 {{ font-size: 20px; font-weight: 600; }}
  .header .sub {{ font-size: 13px; color: #94a3b8; margin-top: 2px; }}
  .status-badge {{ padding: 6px 16px; border-radius: 20px; font-weight: 700; font-size: 14px; background: {status_bg}; color: {status_color}; border: 2px solid {status_color}; }}
  .container {{ max-width: 1280px; margin: 0 auto; padding: 32px; }}
  .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 32px; }}
  .metric {{ background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; }}
  .metric .label {{ font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; margin-bottom: 4px; }}
  .metric .value {{ font-size: 22px; font-weight: 700; color: #0f172a; }}
  .section {{ background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px; margin-bottom: 24px; }}
  .section h2 {{ font-size: 16px; font-weight: 600; margin-bottom: 16px; color: #0f172a; border-bottom: 1px solid #f1f5f9; padding-bottom: 12px; }}
  .images {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
  .img-block {{ border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }}
  .img-label {{ padding: 8px 12px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; background: #f8fafc; border-bottom: 1px solid #e2e8f0; }}
  .img-block img {{ width: 100%; display: block; object-fit: contain; max-height: 400px; background: #f1f5f9; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; padding: 10px 12px; background: #f8fafc; border-bottom: 2px solid #e2e8f0; font-weight: 600; color: #374151; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #f1f5f9; }}
  tr:last-child td {{ border-bottom: none; }}
  .footer {{ text-align: center; padding: 24px; color: #94a3b8; font-size: 12px; }}
  @media (max-width: 768px) {{ .images {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="header">
  <div style="flex:1">
    <h1>{case_name}</h1>
    <div class="sub">Run ID: {run_id} &bull; {escape(str(capture.get('url','')))} &bull; {escape(str(capture.get('browser','')))} {escape(str(capture.get('viewport','')))} </div>
  </div>
  <span class="status-badge">{status}</span>
</div>
<div class="container">
  <div class="metrics">
    <div class="metric"><div class="label">Mismatch</div><div class="value" style="color:{'#ef4444' if float(mismatch)>0.5 else '#22c55e'}">{mismatch:.2f}%</div></div>
    <div class="metric"><div class="label">Diff Pixels</div><div class="value">{diff_px:,}</div></div>
    <div class="metric"><div class="label">SSIM Score</div><div class="value">{ssim_str}</div></div>
    <div class="metric"><div class="label">AI Label</div><div class="value" style="font-size:14px">{ai_label}</div></div>
    <div class="metric"><div class="label">AI Confidence</div><div class="value">{ai_score_str}</div></div>
    <div class="metric"><div class="label">Severity</div><div class="value" style="font-size:14px">{severity_label}</div></div>
    <div class="metric"><div class="label">Decision</div><div class="value" style="font-size:14px">{decision_status}</div></div>
    <div class="metric"><div class="label">Changed Regions</div><div class="value">{len(regions)}</div></div>
  </div>

  <div class="section">
    <h2>Visual Comparison</h2>
    <div class="images">
      <div class="img-block"><div class="img-label">Baseline</div>{'<img src="' + baseline_b64 + '" alt="baseline">' if baseline_b64 else '<div style="padding:32px;text-align:center;color:#94a3b8">No baseline image</div>'}</div>
      <div class="img-block"><div class="img-label">Current</div>{'<img src="' + current_b64 + '" alt="current">' if current_b64 else '<div style="padding:32px;text-align:center;color:#94a3b8">No current image</div>'}</div>
      <div class="img-block"><div class="img-label">Diff Overlay</div>{'<img src="' + diff_b64 + '" alt="diff">' if diff_b64 else '<div style="padding:32px;text-align:center;color:#94a3b8">No diff image</div>'}</div>
    </div>
  </div>

  <div class="section">
    <h2>Changed Regions ({len(regions)} detected, sorted by severity)</h2>
    <table>
      <thead><tr><th>#</th><th>Priority</th><th>Position</th><th>Size</th><th>Area (px²)</th><th>Avg Delta</th></tr></thead>
      <tbody>{region_rows}</tbody>
    </table>
  </div>
</div>
<div class="footer">Generated by Visual Regression Workbench &bull; {run_id}</div>
</body>
</html>"""
    return html
