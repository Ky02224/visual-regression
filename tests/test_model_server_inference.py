"""Regression test: model_server._run_single_infer / infer_batch used to
hardcode CompareResult(baseline_size=[0, 0], current_size=[0, 0]) regardless
of the images actually sent in the request, even though the real dimensions
were decodable from the request's own base64 image payload. Since
width_ratio/height_ratio (ai_features.py) are computed from those sizes and
used as two of the model's rule features, every live inference request
through this microservice silently fed the model wrong feature values —
without ever raising an error. This test locks in that real dimensions now
flow through instead.
"""
import base64

import cv2
import numpy as np
import pytest
from fastapi import HTTPException

from visual_regression.model_server import InferencePayload, _run_single_infer, require_api_key


def _encode_png_b64(width: int, height: int) -> str:
    img = np.full((height, width, 3), 128, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("ascii")


@pytest.fixture
def captured_result(monkeypatch):
    captured = {}

    def fake_assess_result(result, model_path, baseline_image=None, current_image=None, **kwargs):
        captured["result"] = result
        from visual_regression.models import AIAssessment
        return AIAssessment(score=0.1, label="insignificant-change", threshold=0.5, model_name="fake")

    monkeypatch.setattr("visual_regression.ai_training.assess_result", fake_assess_result)
    monkeypatch.setattr("visual_regression.model_server._MODEL_PATH", "fake-model-path")
    return captured


def test_single_infer_uses_real_image_dimensions(captured_result):
    payload = InferencePayload(
        baseline_image_b64=_encode_png_b64(640, 480),
        current_image_b64=_encode_png_b64(320, 240),
        diff_pixels=10,
        total_pixels=1000,
        mismatch_pct=1.0,
    )

    _run_single_infer(payload)

    result = captured_result["result"]
    assert result.baseline_size == [640, 480]
    assert result.current_size == [320, 240]


def test_single_infer_falls_back_to_zero_size_without_images(captured_result):
    payload = InferencePayload(diff_pixels=0, total_pixels=1000, mismatch_pct=0.0)

    _run_single_infer(payload)

    result = captured_result["result"]
    assert result.baseline_size == [0, 0]
    assert result.current_size == [0, 0]


class TestRequireApiKey:
    """/model/reload loads an arbitrary local file via torch.load(weights_only=False)
    — a pickle-deserialization RCE primitive — so this microservice must reject
    every gated request unless a matching X-Access-Key is presented.
    """

    def test_rejects_when_no_server_key_configured(self, monkeypatch):
        monkeypatch.delenv("VRT_MODEL_SERVER_API_KEY", raising=False)
        with pytest.raises(HTTPException) as exc:
            require_api_key(x_access_key="anything")
        assert exc.value.status_code == 403

    def test_rejects_missing_header(self, monkeypatch):
        monkeypatch.setenv("VRT_MODEL_SERVER_API_KEY", "correct-secret")
        with pytest.raises(HTTPException) as exc:
            require_api_key(x_access_key=None)
        assert exc.value.status_code == 403

    def test_rejects_wrong_key(self, monkeypatch):
        monkeypatch.setenv("VRT_MODEL_SERVER_API_KEY", "correct-secret")
        with pytest.raises(HTTPException) as exc:
            require_api_key(x_access_key="wrong-secret")
        assert exc.value.status_code == 403

    def test_accepts_matching_key(self, monkeypatch):
        monkeypatch.setenv("VRT_MODEL_SERVER_API_KEY", "correct-secret")
        assert require_api_key(x_access_key="correct-secret") is True
