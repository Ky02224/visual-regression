#!/usr/bin/env python3
"""
Standalone AI model inference microservice.
Run with: python -m visual_regression.model_server --port 8765

Requires VRT_MODEL_SERVER_API_KEY to be set to a strong shared secret; callers
must send it as the X-Access-Key header on /model/reload, /infer, and
/infer/batch. Without it, those endpoints reject every request.
"""
from __future__ import annotations

import argparse
import base64
import hmac
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("model_server")

# See visual_regression/cli.py for why this is necessary on Windows.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Try importing FastAPI/Uvicorn, print custom install help if missing
try:
    from contextlib import asynccontextmanager
    from fastapi import FastAPI, HTTPException, Depends, Header
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("Error: FastAPI, Uvicorn, and Pydantic are required to run the model server.")
    print("Please install them using: pip install fastapi uvicorn pydantic")
    sys.exit(1)

# _run_single_infer() below calls assess_result(), which by default routes
# through the VRT_AI_SERVICE_URL HTTP microservice (this same process). Since
# the event loop is synchronously blocked serving the inbound /infer request,
# that self-call can never be answered and just burns the full 5s timeout
# before falling back to local inference. Force local inference instead.
os.environ.setdefault("VRT_DISABLE_AI_SPLIT", "true")

# Global model state
_MODEL_PATH: Optional[Path] = None
_LOADED_MODEL: Optional[dict] = None
_SEMAPHORE = None  # Will be initialised in startup to control concurrency


@asynccontextmanager
async def _lifespan(app: FastAPI):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    global _SEMAPHORE
    import asyncio
    _SEMAPHORE = asyncio.Semaphore(4)

    if not os.environ.get("VRT_MODEL_SERVER_API_KEY"):
        logger.warning(
            "[SECURITY WARNING] VRT_MODEL_SERVER_API_KEY is not set — "
            "/model/reload, /infer, and /infer/batch will reject all requests "
            "until it is configured. Set it to a strong shared secret and send "
            "it as the X-Access-Key header from any caller."
        )

    model_env = os.environ.get("VRT_MODEL_PATH")
    if model_env:
        try:
            load_model(Path(model_env))
        except Exception:
            pass
    yield


# App instance
app = FastAPI(title="Visual Regression AI Inference Service", lifespan=_lifespan)

class InferencePayload(BaseModel):
    baseline_image_b64: Optional[str] = None
    current_image_b64: Optional[str] = None
    diff_pixels: int = 0
    total_pixels: int = 1
    mismatch_pct: float = 0.0
    ssim_score: Optional[float] = None
    regions: List[dict] = []
    dom_elements: List[dict] = []
    baseline_dom_elements: List[dict] = []
    current_dom_elements: List[dict] = []

class BatchInferencePayload(BaseModel):
    items: List[InferencePayload]

def get_semaphore():
    global _SEMAPHORE
    if _SEMAPHORE is None:
        import asyncio
        # Limit concurrency to 4 threads to prevent GPU/CPU thrashing
        _SEMAPHORE = asyncio.Semaphore(4)
    return _SEMAPHORE

def load_model(model_path: Path):
    global _LOADED_MODEL, _MODEL_PATH
    from .ai_training import _load_legacy_or_hybrid_model
    try:
        logger.info("Loading model from: %s", model_path)
        _LOADED_MODEL = _load_legacy_or_hybrid_model(model_path)
        _MODEL_PATH = model_path
        logger.info("Model loaded successfully. Type: %s", _LOADED_MODEL["type"])
    except Exception as e:
        logger.error("Failed to load model: %s", e)
        raise RuntimeError(f"Failed to load model: {e}")


def require_api_key(x_access_key: Optional[str] = Header(None)):
    """Gate state-changing/compute endpoints behind a shared secret.

    /model/reload loads an arbitrary local file via torch.load(weights_only=False),
    which executes arbitrary Python objects embedded in a malicious checkpoint —
    a standard pickle-deserialization RCE primitive. Unlike dashboard_server.py
    (every comparable route there requires require_auth/require_admin/
    require_authorized_client), this standalone service had no access control at
    all. Fails closed: with no VRT_MODEL_SERVER_API_KEY configured, every gated
    request is rejected rather than silently left open.
    """
    expected = os.environ.get("VRT_MODEL_SERVER_API_KEY", "")
    if not expected or not x_access_key or not hmac.compare_digest(x_access_key, expected):
        raise HTTPException(status_code=403, detail="Missing or invalid X-Access-Key header")
    return True


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "model_loaded": _LOADED_MODEL is not None,
        "model_path": str(_MODEL_PATH) if _MODEL_PATH else None,
    }

@app.get("/model/info")
def model_info():
    if not _LOADED_MODEL:
        raise HTTPException(status_code=404, detail="No model loaded")
    return {
        "type": _LOADED_MODEL.get("type"),
        "image_size": _LOADED_MODEL.get("image_size"),
        "threshold": _LOADED_MODEL.get("threshold"),
        "class_names": _LOADED_MODEL.get("class_names"),
        "model_path": str(_MODEL_PATH),
    }

@app.post("/model/reload")
def reload_model(path: str, _auth=Depends(require_api_key)):
    try:
        load_model(Path(path))
        return {"ok": True, "message": f"Model reloaded from {path}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def _run_single_infer(payload: InferencePayload) -> dict:
    from .models import CompareResult, DiffRegion
    from .ai_training import assess_result

    import numpy as np
    import cv2

    baseline_image = None
    current_image = None

    if payload.baseline_image_b64:
        b64_data = payload.baseline_image_b64.split(",")[-1]
        nparr = np.frombuffer(base64.b64decode(b64_data), np.uint8)
        baseline_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if payload.current_image_b64:
        b64_data = payload.current_image_b64.split(",")[-1]
        nparr = np.frombuffer(base64.b64decode(b64_data), np.uint8)
        current_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    # Real dimensions (not [0, 0]) so width_ratio/height_ratio rule features —
    # computed identically at training time from real baseline/current sizes —
    # aren't silently zeroed out for every request through this service.
    baseline_size = [int(baseline_image.shape[1]), int(baseline_image.shape[0])] if baseline_image is not None else [0, 0]
    current_size = [int(current_image.shape[1]), int(current_image.shape[0])] if current_image is not None else [0, 0]

    # Construct CompareResult
    regions = [
        DiffRegion(
            x=r.get("x", 0),
            y=r.get("y", 0),
            width=r.get("width", 0),
            height=r.get("height", 0),
            area=r.get("area", 0),
            mean_delta=r.get("mean_delta", 0.0)
        )
        for r in payload.regions
    ]
    result = CompareResult(
        baseline_size=baseline_size,
        current_size=current_size,
        diff_pixels=payload.diff_pixels,
        total_pixels=payload.total_pixels,
        mismatch_pct=payload.mismatch_pct,
        ssim_score=payload.ssim_score,
        regions=regions
    )

    if not _MODEL_PATH:
        # Load the default trained model — same path convention cli.py/dashboard_server.py use.
        default_path = Path(".visual-regression/models/visual_ai.pt")
        if default_path.exists():
            load_model(default_path)
        else:
            raise HTTPException(status_code=500, detail="No model loaded and visual_ai.pt not found")

    assessment = assess_result(
        result=result,
        model_path=_MODEL_PATH,  # type: ignore
        baseline_image=baseline_image,
        current_image=current_image,
        dom_elements=payload.dom_elements,
        baseline_dom_elements=payload.baseline_dom_elements,
        current_dom_elements=payload.current_dom_elements,
    )

    # Include confidence calibration
    from .ai_training import calibrate_confidence
    calib = calibrate_confidence(assessment.score, assessment.label)

    out = assessment.to_dict()
    out.update(calib)
    return out

@app.post("/infer")
async def infer(payload: InferencePayload, sem=Depends(get_semaphore), _auth=Depends(require_api_key)):
    async with sem:
        start = time.time()
        try:
            res = _run_single_infer(payload)
            logger.info("Inference completed in %.3fs", time.time() - start)
            return res
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Inference failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/infer/batch")
async def infer_batch(payload: BatchInferencePayload, sem=Depends(get_semaphore), _auth=Depends(require_api_key)):
    async with sem:
        start = time.time()
        results = []
        try:
            # We can use the batch inference functions if model path is set
            if not _MODEL_PATH:
                default_path = Path(".visual-regression/models/visual_ai.pt")
                # A single local stat(), and only on the first request before a
                # model is loaded — not worth an async filesystem dependency.
                if default_path.exists():  # noqa: ASYNC240
                    load_model(default_path)
                else:
                    raise HTTPException(status_code=500, detail="No model loaded")

            # Let's run Single infer or assess_results_batch
            # To run assess_results_batch we need local paths. Since payload contains b64,
            # we write them to temporary files and batch process them.
            temp_files = []
            batch_items = []

            import numpy as np
            import cv2
            from .models import CompareResult, DiffRegion
            from .ai_training import assess_results_batch
            
            for item in payload.items:
                regions = [
                    DiffRegion(
                        x=r.get("x", 0),
                        y=r.get("y", 0),
                        width=r.get("width", 0),
                        height=r.get("height", 0),
                        area=r.get("area", 0),
                        mean_delta=r.get("mean_delta", 0.0)
                    )
                    for r in item.regions
                ]
                baseline_size = [0, 0]
                current_size = [0, 0]

                bl_path = None
                cu_path = None
                if item.baseline_image_b64:
                    bl_temp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    b64_data = item.baseline_image_b64.split(",")[-1]
                    bl_bytes = base64.b64decode(b64_data)
                    bl_temp.write(bl_bytes)
                    bl_temp.close()
                    bl_path = Path(bl_temp.name)
                    temp_files.append(bl_path)
                    decoded = cv2.imdecode(np.frombuffer(bl_bytes, np.uint8), cv2.IMREAD_COLOR)
                    if decoded is not None:
                        baseline_size = [int(decoded.shape[1]), int(decoded.shape[0])]

                if item.current_image_b64:
                    cu_temp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    b64_data = item.current_image_b64.split(",")[-1]
                    cu_bytes = base64.b64decode(b64_data)
                    cu_temp.write(cu_bytes)
                    cu_temp.close()
                    cu_path = Path(cu_temp.name)
                    temp_files.append(cu_path)
                    decoded = cv2.imdecode(np.frombuffer(cu_bytes, np.uint8), cv2.IMREAD_COLOR)
                    if decoded is not None:
                        current_size = [int(decoded.shape[1]), int(decoded.shape[0])]

                # Real dimensions (not [0, 0]) so width_ratio/height_ratio rule
                # features aren't silently zeroed out for every batch request.
                result = CompareResult(
                    baseline_size=baseline_size,
                    current_size=current_size,
                    diff_pixels=item.diff_pixels,
                    total_pixels=item.total_pixels,
                    mismatch_pct=item.mismatch_pct,
                    ssim_score=item.ssim_score,
                    regions=regions
                )

                batch_items.append({
                    "result": result,
                    "baseline_image_path": bl_path,
                    "current_image_path": cu_path
                })
                
            try:
                results = assess_results_batch(batch_items, _MODEL_PATH)
            finally:
                # Clean up temp files
                for tf in temp_files:
                    try:
                        if tf.exists():
                            tf.unlink()
                    except Exception:
                        pass
                        
            logger.info("Batch inference of %d items completed in %.3fs", len(payload.items), time.time() - start)
            return {"results": results}
        except Exception as e:
            logger.error("Batch inference failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics")
def prometheus_metrics():
    # Expose basic metrics
    return {
        "model_loaded": 1 if _LOADED_MODEL else 0,
        "inference_service_uptime": 1.0,
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run VRT AI Inference Microservice")
    parser.add_argument("--host", default="127.0.0.1", help="Host address")
    parser.add_argument("--port", type=int, default=8765, help="Port to run on")
    parser.add_argument("--model-path", help="Path to visual_ai.pt model file")
    args = parser.parse_args()
    
    if args.model_path:
        load_model(Path(args.model_path))
        
    uvicorn.run(app, host=args.host, port=args.port)
