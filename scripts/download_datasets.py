"""
Download public UI screenshot datasets for AI training.
Usage:  python download_datasets.py
Output: scratch/datasets/webui/   (desktop web screenshots)
        scratch/datasets/rico/    (mobile app screenshots)

Target: ~12000 new images on top of your existing ~4004
Total after download: ~16000 images
Recommended training config: samples_per_image=4
"""
from __future__ import annotations

import io
import importlib
import importlib.util
import json
import sys
import urllib.request
import threading
from pathlib import Path



WEBUI_TARGET = 5000  
RICO_TARGET  = 4000   

OUT_WEBUI = Path("scratch/datasets/webui")
OUT_RICO  = Path("scratch/datasets/rico")


def _require(pkg: str, install: str | None = None) -> None:
    if importlib.util.find_spec(pkg) is None:
        pip_name = install or pkg
        print(f"[setup] Installing {pip_name}...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name, "-q"])


def _save_image(data: bytes, dest: Path) -> bool:
    try:
        import cv2
        import numpy as np
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return False
        h, w = img.shape[:2]
        if min(h, w) < 64:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(dest), img)
        return True
    except Exception:
        return False


def _stream_dataset_with_timeout(
    dataset_id: str,
    split: str,
    target: int,
    out_dir: Path,
    prefix: str,
    offset: int = 0,
) -> int:
    """Stream a HuggingFace image dataset with stall detection and graceful abort."""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    skipped = 0

    print(f"  Trying {dataset_id}...")
    try:
        from datasets import load_dataset  
        ds = load_dataset(dataset_id, split=split, streaming=True)
    except Exception as e:
        print(f"  Could not load {dataset_id}: {e}")
        return 0

    def _iter():
        nonlocal saved, skipped
        for item in ds:
            if saved >= target:
                break
            try:
                img = (
                    item.get("image")
                    or item.get("screenshot")
                    or item.get("img")
                    or item.get("ui_screenshot")
                    or item.get("ground_truth")
                )
                if img is None:
                    skipped += 1
                    continue
                dest = out_dir / f"{prefix}_{offset + saved:05d}.png"
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                if _save_image(buf.getvalue(), dest):
                    saved += 1
                    if saved % 200 == 0:
                        print(f"  {dataset_id}: {saved}/{target}")
                else:
                    skipped += 1
            except Exception:
                skipped += 1

    t = threading.Thread(target=_iter, daemon=True)
    t.start()

    deadline  = 3600
    stall_limit = 600  
    elapsed = 0
    last_saved = -1
    stall_sec = 0

    while t.is_alive() and elapsed < deadline and saved < target:
        t.join(timeout=5)
        elapsed += 5
        if saved == last_saved:
            stall_sec += 5
            if stall_sec >= stall_limit:
                print(f"  Stalled {stall_limit}s — aborting {dataset_id}")
                break
        else:
            stall_sec = 0
            last_saved = saved

    print(f"  {dataset_id}: {saved} saved, {skipped} skipped")
    return saved


def download_websight(target: int, offset: int = 0) -> int:
    """Download desktop web screenshots from HuggingFace WebSight dataset."""
    print(f"\n[WebSight] Downloading up to {target} desktop screenshots...")
    _require("datasets")

    OUT_WEBUI.mkdir(parents=True, exist_ok=True)
    saved = 0

    # 主要来源
    try:
        saved = _stream_dataset_with_timeout(
            "HuggingFaceM4/WebSight", "train", target, OUT_WEBUI, "websight", offset=offset
        )
    except Exception as e:
        print(f"  [WebSight] Primary source error: {e}")

    # Fallback：直接下 parquet shard
    if saved < target:
        print(f"  [WebSight] Got {saved}/{target}, trying parquet fallback...")
        saved += _download_websight_parquet(target - saved, offset + saved)

    print(f"  WebSight total: {saved} saved")
    return saved


def _download_websight_parquet(target: int, offset: int) -> int:
    """Fallback: download WebSight parquet shard and extract images."""
    _require("pandas")
    _require("pyarrow")
    import pandas as pd  # type: ignore

    saved = 0
    url = "https://huggingface.co/datasets/HuggingFaceM4/WebSight/resolve/main/data/train-00000-of-00020.parquet"
    parquet_path = Path("scratch/datasets/websight_tmp.parquet")
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        print("  Downloading parquet shard (~300MB)...")
        urllib.request.urlretrieve(url, parquet_path)
        df = pd.read_parquet(parquet_path, columns=["image"])
        for _, row in df.iterrows():
            if saved >= target:
                break
            try:
                img_data = row["image"]
                if isinstance(img_data, dict):
                    img_bytes = img_data.get("bytes") or img_data.get("path")
                    if isinstance(img_bytes, (bytes, bytearray)):
                        dest = OUT_WEBUI / f"websight_{offset + saved:05d}.png"
                        if _save_image(bytes(img_bytes), dest):
                            saved += 1
            except Exception:
                pass
        parquet_path.unlink(missing_ok=True)
    except Exception as e:
        print(f"  [WebSight parquet] Failed: {e}")
    return saved


def download_rico(target: int, offset: int = 0) -> int:
    """Download mobile app screenshots from multiple HuggingFace sources."""
    print(f"\n[Mobile/RICO] Downloading up to {target} mobile screenshots...")
    _require("datasets")

    saved = 0
    candidates = [
        ("rootsautomation/RICO-Screen2Words", "train", "rico"),
        ("Voxel51/rico", "train", "rico"),
    ]

    for dataset_id, split, prefix in candidates:
        if saved >= target:
            break
        got = _stream_dataset_with_timeout(
            dataset_id, split, target - saved, OUT_RICO, prefix, offset=offset + saved
        )
        saved += got

    # [FIX] 原代码在全部失败时只 print，这里改成明确提示但不崩溃
    if saved == 0:
        print("  [Mobile] All sources failed — will train with desktop data only.")
        print("  (This is OK — WebSight alone is sufficient for visual regression training)")
    else:
        print(f"  Mobile total: {saved} saved")
    return saved


def build_manifest(webui_saved: int, rico_saved: int) -> Path | None:
    total = webui_saved + rico_saved
    if total == 0:
        print("\n[manifest] No images downloaded — skipping manifest.")
        return None

    print("\n[manifest] Building dataset manifest...")
    cmd_parts = [sys.executable, "-m", "visual_regression", "prepare-public-datasets"]
    if webui_saved > 0:
        cmd_parts += ["--webui-dir", str(OUT_WEBUI.resolve())]
    if rico_saved > 0:
        cmd_parts += ["--rico-dir", str(OUT_RICO.resolve())]
    cmd_parts += ["--max-images-per-source", "9999"]

    import subprocess
    result = subprocess.run(cmd_parts, capture_output=True, text=True)
    manifest_path = Path(".visual-regression/datasets/public-ui-manifest.json")

    if manifest_path.exists():
        data = json.loads(manifest_path.read_text())
        total_in_manifest = data.get("total_images", 0)
        print(f"  Manifest saved: {manifest_path} ({total_in_manifest} images)")
        return manifest_path

    # [FIX] 原代码这里没有任何错误信息，调试困难
    print(f"  [manifest] WARNING: manifest file not found at {manifest_path}")
    print(f"  [manifest] stdout: {result.stdout[-500:] if result.stdout else '(empty)'}")
    print(f"  [manifest] stderr: {result.stderr[-500:] if result.stderr else '(empty)'}")
    return None


def main() -> None:
    print("=" * 60)
    print("  UI Dataset Downloader for Visual Regression AI Training")
    print("=" * 60)
    print(f"  Target: {WEBUI_TARGET} desktop  +  {RICO_TARGET} mobile ")
    print(f"  Total after download: ~{ WEBUI_TARGET + RICO_TARGET:,} images")
    print("  Estimated download size: ~2.5 - 4 GB")
    print()

    _require("cv2", "opencv-python")

    existing_webui = len(list(OUT_WEBUI.glob("*.png"))) if OUT_WEBUI.exists() else 0
    if existing_webui >= WEBUI_TARGET:
        print(f"\n[WebSight] Already have {existing_webui} images — skipping.")
        webui_saved = existing_webui
    else:
        need = WEBUI_TARGET - existing_webui
        print(f"\n[WebSight] Have {existing_webui}, need {need} more.")
        webui_saved = existing_webui + download_websight(need, offset=existing_webui)

    existing_rico = len(list(OUT_RICO.glob("*.png"))) if OUT_RICO.exists() else 0
    if existing_rico >= RICO_TARGET:
        print(f"\n[RICO] Already have {existing_rico} images — skipping.")
        rico_saved = existing_rico
    else:
        need = RICO_TARGET - existing_rico
        print(f"\n[RICO] Have {existing_rico}, need {need} more.")
        rico_saved = existing_rico + download_rico(need, offset=existing_rico)

    manifest = build_manifest(webui_saved, rico_saved)
    total = webui_saved + rico_saved

    print("\n" + "=" * 60)
    print(f"  Download complete: {total} new images")
    print(f"    Desktop (WebSight) : {webui_saved}")
    print(f"    Mobile  (RICO)     : {rico_saved}")

    if manifest:
       
        print("\n  Next step — retrain the AI:")
        print(
             f"python -m visual_regression train-ai "
             f"--epochs 10 "
             f"--samples-per-image 4 "
             f"--dataset-manifest {manifest} "
             f"--max-public-images {total}"
        )

if __name__ == "__main__":
    main()