"""Model serialisation: ONNX export, quantisation, TorchScript, and loading.

Split out of ai_training.py. These share one concern — moving a trained model
between formats — and depend only on the architecture in ai_models, not on the
training loop.

_load_legacy_or_hybrid_model is here rather than in ai_models because it is the
inverse of the exporters: it reconstructs a model from whatever format a
checkpoint happens to be in, including two older layouts kept for
backward compatibility.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .ai_features import (
    DEFAULT_IMAGE_SIZE,
    FULL_FEATURE_NAMES,
    RULE_FEATURE_NAMES,
    normalize_batch_uint8,
)

from .ai_models import (
    CompleteSiameseModel,
    LegacyRuleMLP,
    PairSample,
    SiameseFusionHead,
    _build_backbone,
    _require_torch,
)

logger = logging.getLogger(__name__)

# Confidence floor used when a checkpoint does not record its own threshold.
DEFAULT_CONFIDENCE_FLOOR = 0.35

# Loading a checkpoint is expensive, so the most recent one is cached and
# invalidated by mtime. The mtime itself is cached briefly too — stat() on every
# single inference is measurable when a suite runs hundreds of comparisons.
_cached_loaded_model = None
_cached_model_path = None
_cached_model_mtime = None
_model_cache_lock = threading.Lock()  # Guards the three variables above

_cached_mtime_time = 0.0
_cached_mtime_val = None
_mtime_check_lock = threading.Lock()


def _reconstruct_backbone_and_head(checkpoint: Dict[str, Any]):
    """Rebuild the backbone + classifier head a checkpoint was actually
    trained with, from the checkpoint's own recorded shapes.

    export_to_onnx and compile_to_torchscript each carried their own copy of
    this, both hardcoded to _build_resnet50_backbone and a non-widened head —
    correct for the model this project shipped with, but resnet50_multiscale
    (added 2026-08-14, 3840-dim embedding vs. resnet50's 2048) uses a
    different backbone entirely, and a widened head projects the rule vector
    through "rule_proj"/"trunk" instead of a bare Sequential. Loading either
    checkpoint shape through the hardcoded path fails immediately on a
    state_dict mismatch, or in the widened case, on inferring the wrong
    in_features and building a head the weights cannot fill. This is the
    third copy of the fix already applied at the load side
    (_load_legacy_or_hybrid_model below); pulled out so a fourth callsite
    doesn't silently regress the same way.
    """
    torch, nn = _require_torch()
    backbone_name = checkpoint.get("backbone_name", "resnet50")
    backbone, embedding_dim, _, _ = _build_backbone(
        backbone_name, pretrained=bool(checkpoint.get("pretrained_backbone", True))
    )
    backbone = backbone.to("cpu")
    if checkpoint.get("backbone_state_dict"):
        backbone.load_state_dict(checkpoint["backbone_state_dict"])
    backbone.eval()

    class_names = list(checkpoint.get("class_names", []))
    output_dim = len(class_names) if class_names else 1
    rule_names = checkpoint.get("rule_feature_names") or RULE_FEATURE_NAMES
    rule_dim = len(rule_names)
    classifier_state = checkpoint["classifier_state_dict"]
    # Which head architecture produced this checkpoint is written in its own key
    # names: the widened head projects the rule vector through "rule_proj" and
    # keeps the classifier in "trunk", the flat one is a bare Sequential whose
    # first layer is "0". Reading the shape off the wrong one silently builds a
    # head the weights cannot load into.
    widened = any(k.startswith("rule_proj.") for k in classifier_state)
    image_projection_dim = None
    if widened:
        in_features = classifier_state["trunk.0.weight"].shape[1]
        projection_dim = classifier_state["rule_proj.3.weight"].shape[0]
        if "image_proj.0.weight" in classifier_state:
            # The image side is projected too. Its own layer states both widths,
            # which the trunk no longer can: trunk.0 now sees 512 columns, not
            # the 8192 the backbone actually produces, so deriving image_dim by
            # subtraction would build a head a quarter the right size and the
            # load would fail on shapes.
            image_dim = classifier_state["image_proj.0.weight"].shape[1]
            image_projection_dim = classifier_state["image_proj.0.weight"].shape[0]
        else:
            image_dim = in_features - projection_dim
    else:
        first_weight_key = "0.weight" if "0.weight" in classifier_state else next(iter(classifier_state))
        image_dim = classifier_state[first_weight_key].shape[1] - rule_dim
    num_streams = 3 if image_dim == embedding_dim * 3 else 4

    head = SiameseFusionHead(
        nn,
        embedding_dim=embedding_dim,
        rule_dim=rule_dim,
        output_dim=output_dim,
        num_streams=num_streams,
        widen_rule_features=widened,
        image_projection_dim=image_projection_dim,
    ).model
    head.load_state_dict(classifier_state)
    head.eval()
    return backbone, head, embedding_dim, class_names, rule_dim, num_streams


def export_to_onnx(model_path: Path):
    """Export the hybrid PyTorch Siamese model to ONNX format cleanly and fast."""
    torch, nn = _require_torch()
    if not model_path.exists():
        return
    # torch.onnx.export's dynamo-based path (default since a recent torch
    # version) prints Unicode progress markers (a checkmark, etc.) straight to
    # stdout. On Windows, sys.stdout's default encoding is the console
    # codepage (cp1252), not UTF-8, so that print raises UnicodeEncodeError —
    # observed killing the export entirely on this platform. Reconfiguring to
    # replace unencodable characters rather than crash keeps the export
    # working on every platform; it only affects what gets printed, never the
    # exported model's correctness.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    # Set before the try so a failure inside it (e.g. an architecture the
    # reconstruction can't yet build) reports that failure directly instead
    # of the validation/metadata blocks below raising an unrelated
    # UnboundLocalError on onnx_path/img_size when they run anyway.
    onnx_path = None
    try:
        checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
        model_type = checkpoint.get("model_type")
        if model_type == "legacy-rule-mlp" or "classifier_state_dict" not in checkpoint:
            logger.info(f"[ONNX Export] Model {model_path.name} is a legacy MLP model; skipping ONNX export.")
            return

        backbone, head_model, embedding_dim, class_names, rule_dim, _num_streams = _reconstruct_backbone_and_head(checkpoint)

        wrapper_model = CompleteSiameseModel(backbone, head_model)
        wrapper_model.eval()

        img_size = int(checkpoint.get("image_size", DEFAULT_IMAGE_SIZE))
        dummy_left = torch.zeros(1, 3, img_size, img_size, dtype=torch.float32)
        dummy_right = torch.zeros(1, 3, img_size, img_size, dtype=torch.float32)
        saved_rule_names = list(checkpoint.get("rule_feature_names", RULE_FEATURE_NAMES))
        dummy_rule = torch.zeros(1, len(saved_rule_names), dtype=torch.float32)

        onnx_path = model_path.with_suffix(".onnx")
        logger.info(f"[ONNX Export] Fast exporting to {onnx_path.name}...")

        torch.onnx.export(
            wrapper_model,
            (dummy_left, dummy_right, dummy_rule),
            str(onnx_path),
            input_names=["left_image", "right_image", "rule_features"],
            output_names=["logits"],
            dynamic_axes={
                "left_image": {0: "batch_size"},
                "right_image": {0: "batch_size"},
                "rule_features": {0: "batch_size"},
                "logits": {0: "batch_size"},
            },
            opset_version=14,
            do_constant_folding=True,
        )
        logger.info(f"[ONNX Export] Successfully exported ONNX model -> {onnx_path.name}")
    except Exception as exc:
        logger.warning(f"[ONNX Export] ONNX export warning: {exc}")

    if onnx_path is None:
        return

    try:
        import onnxruntime as ort
        ort_sess = ort.InferenceSession(str(onnx_path))
        
        rand_left = np.random.randn(1, 3, img_size, img_size).astype(np.float32)
        rand_right = np.random.randn(1, 3, img_size, img_size).astype(np.float32)
        rand_rule = np.random.randn(1, len(saved_rule_names)).astype(np.float32)

        with torch.no_grad():
            pt_out = wrapper_model(
                torch.tensor(rand_left),
                torch.tensor(rand_right),
                torch.tensor(rand_rule)
            ).numpy()

        ort_out = ort_sess.run(
            ["logits"],
            {
                "left_image": rand_left,
                "right_image": rand_right,
                "rule_features": rand_rule
            }
        )[0]

        diff = np.max(np.abs(pt_out - ort_out))
        logger.info(f"[ONNX Validation] Maximum numerical diff: {diff:.2e}")
    except Exception as e:
        logger.warning(f"[ONNX Validation Warning] Validation failed: {e}")

    try:
        meta = {
            "model_type": model_type,
            "threshold": float(checkpoint.get("threshold", 0.5)),
            "image_size": img_size,
            "class_names": class_names,
            "accuracy": float(checkpoint.get("accuracy", 1.0)),
            "samples": int(checkpoint.get("samples", 0)),
            # Without this, the TorchScript inference path (which reads this
            # sidecar, not the checkpoint) can't tell a DOM-augmented model
            # (48-dim rule vector) from a base one (9-dim) and always assumes
            # 9 — feeding the wrong input width into a model traced with more.
            "rule_feature_names": list(checkpoint.get("rule_feature_names", RULE_FEATURE_NAMES)),
            # The same reasoning one line up, for scale rather than width. A
            # model trained on standardised features and then served
            # unstandardised receives inputs orders of magnitude away from
            # anything it saw in training — and the ONNX sidecar, not the
            # checkpoint, is what the deployed path reads.
            "rule_feature_mean": checkpoint.get("rule_feature_mean"),
            "noise_override_confidence": checkpoint.get("noise_override_confidence"),
            "rule_feature_std": checkpoint.get("rule_feature_std"),
        }
        json_path = model_path.with_suffix(".json")
        json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        logger.info(f"[ONNX Export] Saved metadata sidecar to {json_path.name}")
    except Exception as e:
        logger.warning(f"[ONNX Export Warning] Failed to save metadata sidecar: {e}")
def quantize_onnx_model(
    onnx_path: Path,
    calibration_samples: List[PairSample],
    output_path: Path,
    rule_feature_mean=None,
    rule_feature_std=None,
):
    """Run static INT8 quantization on the exported ONNX model."""
    try:
        import onnx
        from onnxruntime.quantization import quantize_static, QuantType, QuantFormat, CalibrationDataReader, CalibrationMethod
        from .ai_features import standardise_rule_vector

        class ONNXCalibrationDataReader(CalibrationDataReader):
            def __init__(self, samples, image_size, rule_dim, rule_mean, rule_std):
                super().__init__()
                self.samples = samples
                self.image_size = image_size
                # The width the graph being calibrated actually declares. This
                # was hardcoded to len(FULL_FEATURE_NAMES), so quantising a
                # model trained at any other width fed the calibrator inputs the
                # graph could not take — and the activation ranges it collects
                # are what the INT8 scales are derived from.
                self.rule_dim = int(rule_dim)
                self.rule_mean = rule_mean
                self.rule_std = rule_std
                self.index = 0

            def get_next(self):
                if self.index >= len(self.samples):
                    return None
                sample = self.samples[self.index]
                self.index += 1
                if isinstance(sample, tuple):
                    baseline_rgb, current_rgb, rule_features = sample[0], sample[1], sample[2]
                else:
                    baseline_rgb = sample.baseline_rgb
                    current_rgb = sample.current_rgb
                    rule_features = sample.rule_features

                left_batch = normalize_batch_uint8(np.expand_dims(baseline_rgb, 0))
                right_batch = normalize_batch_uint8(np.expand_dims(current_rgb, 0))
                rule_features = np.asarray(rule_features)
                if len(rule_features) > self.rule_dim:
                    rule_features = rule_features[: self.rule_dim]
                elif len(rule_features) < self.rule_dim:
                    rule_features = np.pad(
                        rule_features, (0, self.rule_dim - len(rule_features)), mode="constant")
                # The model was trained on standardised features (see
                # standardise_rule_vector's docstring: raw columns span a
                # standard-deviation ratio of 2.4e10), and the real inference
                # path always standardises before calling the model —
                # _standardised_rule_vector, not the raw PairSample.
                # calibration_samples here comes straight from
                # _build_pair_sample/train_dataset[idx], which never applied
                # that step, so the calibrator was fitting INT8 ranges to a
                # completely different scale of input than the model ever
                # sees in production. That's not a rounding-error kind of
                # miscalibration -- measured, it collapsed every prediction
                # to the same class regardless of input.
                rule_features = standardise_rule_vector(rule_features, self.rule_mean, self.rule_std)
                rule_batch = np.expand_dims(rule_features, 0).astype(np.float32)
                return {
                    "left_image": left_batch,
                    "right_image": right_batch,
                    "rule_features": rule_batch
                }

        # Plain onnx.shape_inference.infer_shapes (below, now unused for this
        # step) is not what onnxruntime's own quantizer asks for -- it warns
        # every run to use quant_pre_process instead, which also runs a model
        # optimization pass first. Skipping that isn't cosmetic: an op whose
        # output shape isn't resolved is left unquantized, and measured here
        # that was enough to make every prediction collapse to one class
        # (missing-element, argmax agreement 0/20 against the unquantized
        # model) rather than merely losing some precision.
        #
        # Two more steps needed before quant_pre_process will actually run on
        # this export, both specific to torch's dynamo-based exporter (the
        # default since a recent torch version):
        #
        # 1. That exporter writes weights to a separate .onnx.data file by
        #    default (not because this model exceeds any size limit -- it's
        #    ~160MB, nowhere near the 2GB single-file cap -- just the
        #    exporter's default). quant_pre_process's skip_symbolic_shape
        #    path (next point) loads the model from a temp copy that doesn't
        #    carry the external-data sidecar along, so it fails to find the
        #    weights. Consolidating back to one self-contained file first
        #    avoids that path entirely.
        # 2. quant_pre_process's symbolic shape inference step crashes on a
        #    Reshape node this exporter's graph shape produces
        #    (TypeError: 'NoneType' object is not iterable, inside
        #    onnxruntime's own symbolic_shape_infer.py) -- a real
        #    incompatibility between the newest torch.onnx path and
        #    onnxruntime's shape-inference tool, not anything specific to
        #    this model's architecture. skip_symbolic_shape=True keeps the
        #    plain ONNX shape inference and model-optimization passes
        #    (quant_pre_process still does both), which is what actually
        #    fixed the collapsed-to-one-class quantization -- only the
        #    symbolic (shape-algebra) pass is skipped.
        logger.info(f"[ONNX Quantization] Running quantization pre-processing on {onnx_path.name}...")
        consolidated_path = onnx_path.with_name(f"{onnx_path.stem}.consolidated.onnx")
        model = onnx.load(str(onnx_path), load_external_data=True)
        onnx.save_model(model, str(consolidated_path), save_as_external_data=False)

        inferred_path = onnx_path.with_suffix(".inferred.onnx")
        from onnxruntime.quantization.shape_inference import quant_pre_process
        quant_pre_process(
            input_model=str(consolidated_path),
            output_model_path=str(inferred_path),
            save_as_external_data=True,
            skip_symbolic_shape=True,
        )
        consolidated_path.unlink(missing_ok=True)

        torch, _ = _require_torch()
        checkpoint = torch.load(onnx_path.with_suffix(".pt"), map_location="cpu", weights_only=False) if onnx_path.with_suffix(".pt").exists() else {}
        img_size = int(checkpoint.get("image_size", DEFAULT_IMAGE_SIZE))
        rule_dim = len(checkpoint.get("rule_feature_names", FULL_FEATURE_NAMES))
        rule_mean = rule_feature_mean if rule_feature_mean is not None else checkpoint.get("rule_feature_mean")
        rule_std = rule_feature_std if rule_feature_std is not None else checkpoint.get("rule_feature_std")
        reader = ONNXCalibrationDataReader(calibration_samples, img_size, rule_dim, rule_mean, rule_std)

        logger.info("[ONNX Quantization] Starting static INT8 quantization...")
        # quant_format=0 (QuantFormat.QOperator) fuses quantization directly
        # into specialised int8 op kernels, whose x64 CPU coverage is
        # inconsistent — onnxruntime's own quantize_static call prints a
        # warning recommending QDQ for this exact activation/weight
        # combination, every run, unactioned. Measured consequence: a
        # QOperator-quantized resnet50_multiscale model disagreed with the
        # unquantized model on 20/20 argmax comparisons on random inputs — not
        # degraded, completely wrong. QDQ inserts explicit Quantize/
        # DeQuantize node pairs around each op instead of relying on a fused
        # int8 kernel existing for every op in the graph, so it works
        # correctly on architectures QOperator's kernel set doesn't cover.
        quantize_static(
            model_input=str(inferred_path),
            model_output=str(output_path),
            calibration_data_reader=reader,
            quant_format=QuantFormat.QDQ,
            activation_type=QuantType.QUInt8,
            weight_type=QuantType.QInt8,
            per_channel=True,
            calibrate_method=CalibrationMethod.Percentile,
        )
        logger.info(f"[ONNX Quantization] Saved quantized model to {output_path.name}")

        if inferred_path.exists():
            inferred_path.unlink()
    except Exception as e:
        logger.warning(f"[ONNX Quantization Warning] Quantization failed: {e}")
def _load_legacy_or_hybrid_model(model_path: Path):
    global _cached_loaded_model, _cached_model_path, _cached_model_mtime
    global _cached_mtime_time, _cached_mtime_val
    import os
    import time
    
    now = time.time()
    with _mtime_check_lock:
        if now - _cached_mtime_time < 5.0 and _cached_mtime_val is not None:
            mtime = _cached_mtime_val
        else:
            mtime = None
            try:
                mtime = os.path.getmtime(model_path)
                _cached_mtime_time = now
                _cached_mtime_val = mtime
            except Exception:
                pass

    # Fast path: return cached model if path and mtime match.
    if mtime is not None:
        with _model_cache_lock:
            if (
                _cached_loaded_model is not None
                and _cached_model_path == model_path
                and _cached_model_mtime == mtime
            ):
                return _cached_loaded_model

    # ── TorchScript fast-load branch (check before ONNX/PyTorch) ────────────
    torchscript_path = model_path.with_suffix(".torchscript.pt")
    if torchscript_path.exists():
        try:
            torch, _ = _require_torch()
            json_path_ts = model_path.with_suffix(".json")
            ts_meta: Dict[str, Any] = {}
            if json_path_ts.exists():
                ts_meta = json.loads(json_path_ts.read_text(encoding="utf-8"))
            scripted = torch.jit.load(str(torchscript_path), map_location="cpu")
            scripted.eval()
            class_names_ts = list(ts_meta.get("class_names", []))
            loaded_dict_ts: Dict[str, Any] = {
                "models_dir": model_path.parent,
                "type": "torchscript-multiclass" if class_names_ts else "torchscript-binary",
                "torch": torch,
                "scripted": scripted,
                "threshold": float(ts_meta.get("threshold", DEFAULT_CONFIDENCE_FLOOR)),
                "image_size": int(ts_meta.get("image_size", DEFAULT_IMAGE_SIZE)),
                "model_type": ts_meta.get("model_type", "resnet50-siamese-rule-fusion-multiclass"),
                "class_names": class_names_ts,
                "rule_dim": len(ts_meta.get("rule_feature_names", RULE_FEATURE_NAMES)),
                "rule_feature_mean": ts_meta.get("rule_feature_mean"),
                "noise_override_confidence": ts_meta.get("noise_override_confidence"),
                "rule_feature_std": ts_meta.get("rule_feature_std"),
            }
            logger.info("[TorchScript] Loaded scripted model from %s", torchscript_path.name)
            if mtime is not None:
                with _model_cache_lock:
                    _cached_loaded_model = loaded_dict_ts
                    _cached_model_path = model_path
                    _cached_model_mtime = mtime
            return loaded_dict_ts
        except Exception as ts_err:
            logger.warning(
                "[TorchScript] Failed to load %s: %s — falling back to ONNX/PyTorch.",
                torchscript_path.name,
                ts_err,
            )

    # Determine if we have ONNX & JSON sidecars
    onnx_quant_path = model_path.with_suffix(".quant.onnx")
    onnx_standard_path = model_path.with_suffix(".onnx")
    json_path = model_path.with_suffix(".json")

    has_onnx = onnx_quant_path.exists() or onnx_standard_path.exists()
    has_json = json_path.exists()

    if has_onnx and has_json:
        try:
            import onnxruntime as ort
            # Load metadata from JSON
            meta = json.loads(json_path.read_text(encoding="utf-8"))
            model_type = meta.get("model_type")
            class_names = meta.get("class_names", [])
            threshold = float(meta.get("threshold", 0.5))
            image_size = int(meta.get("image_size", DEFAULT_IMAGE_SIZE))

            # Select model file
            onnx_file = onnx_quant_path if onnx_quant_path.exists() else onnx_standard_path
            logger.info(f"[ONNX Inference] Loading session for {onnx_file.name}...")
            
            # Disable unneeded ONNX logging to speed up startup
            sess_opts = ort.SessionOptions()
            sess_opts.log_severity_level = 3
            session = ort.InferenceSession(str(onnx_file), sess_opts)

            loaded_dict = {
                "models_dir": model_path.parent,
                "type": "onnx-hybrid-multiclass" if class_names else "onnx-hybrid-binary",
                "session": session,
                "threshold": threshold,
                "image_size": image_size,
                "model_type": model_type,
                "class_names": class_names,
                "rule_feature_mean": meta.get("rule_feature_mean"),
                "noise_override_confidence": meta.get("noise_override_confidence"),
                "rule_feature_std": meta.get("rule_feature_std"),
            }
            if mtime is not None:
                with _model_cache_lock:
                    _cached_loaded_model = loaded_dict
                    _cached_model_path = model_path
                    _cached_model_mtime = mtime
            return loaded_dict
        except Exception as e:
            logger.warning(f"[ONNX Load Warning] Failed to load ONNX session: {e}. Falling back to PyTorch.")

    # Slow path: load from disk (lock NOT held during I/O to avoid blocking other threads)
    torch, nn = _require_torch()
    checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
    model_type = str(checkpoint.get("model_type") or "legacy-rule-mlp")

    if model_type == "legacy-rule-mlp" or "classifier_state_dict" not in checkpoint:
        loaded_dict = {
            "type": "legacy",
            "runner": LegacyRuleMLP(torch, nn, checkpoint),
            "threshold": float(checkpoint.get("threshold", 0.5)),
        }
        if mtime is not None:
            with _model_cache_lock:
                _cached_loaded_model = loaded_dict
                _cached_model_path = model_path
                _cached_model_mtime = mtime
        return loaded_dict

    backbone, head, embedding_dim, class_names, rule_dim, num_streams = _reconstruct_backbone_and_head(checkpoint)

    loaded_dict = {
        "models_dir": model_path.parent,
        "type": "hybrid-multiclass" if class_names else "hybrid-binary",
        "torch": torch,
        "backbone": backbone,
        "head": head,
        "threshold": float(checkpoint.get("threshold", 0.5)),
        "image_size": int(checkpoint.get("image_size", DEFAULT_IMAGE_SIZE)),
        "model_type": model_type,
        "class_names": class_names,
        "calibrated_temperature": float(checkpoint.get("calibrated_temperature", 1.3)),
        "rule_feature_mean": checkpoint.get("rule_feature_mean"),
        "noise_override_confidence": checkpoint.get("noise_override_confidence"),
        "rule_feature_std": checkpoint.get("rule_feature_std"),
        # The three numbers an inference path needs to build an input this head
        # will accept. They are known exactly here — rule_dim from the width the
        # checkpoint was trained at, embedding_dim from the backbone that was
        # actually built, num_streams from the head's own first layer — and
        # dropping them forced every consumer to reverse-engineer them from
        # `head.parameters()` against a hardcoded 2048, which is right only for
        # ResNet50 and guesses wrong whenever a stream count changes.
        "rule_dim": rule_dim,
        "embedding_dim": embedding_dim,
        "num_streams": num_streams,
    }
    if mtime is not None:
        with _model_cache_lock:
            _cached_loaded_model = loaded_dict
            _cached_model_path = model_path
            _cached_model_mtime = mtime
    return loaded_dict
def compile_to_torchscript(model_path: Path, output_path: Optional[Path] = None) -> Path:
    """Trace the complete Siamese model with TorchScript and save to a .torchscript.pt file.

    WARNING (2026-08-15): tracing this architecture is unsound, not just
    unfinished. ai_models.py's forward pass has a data-dependent branch
    (`if expected_dim >= emb_dim * 4`, flagged by torch's own TracerWarning
    at trace time), so torch.jit.trace bakes in whichever branch the dummy
    input happened to take and produces a graph with a fixed linear-layer
    shape. Verified against the deployed resnet50_multiscale checkpoint: the
    traced model matched the eager model exactly for inputs shaped like the
    tracing dummy, then crashed with a real batch of DOM-diff rule features
    ("mat1 and mat2 shapes cannot be multiplied") the first time production
    code called it with a different shape. Do not install a .torchscript.pt
    produced by this function without either switching to torch.jit.script
    (which handles Python control flow correctly) or removing the
    data-dependent branch from the forward pass first — a passing numeric
    match on one input shape is not evidence it's safe for others.

    Args:
        model_path: Path to the saved PyTorch checkpoint (.pt file).
        output_path: Destination path for the TorchScript file. Defaults to
            ``model_path.with_suffix('.torchscript.pt')``.

    Returns:
        The path where the TorchScript model was saved.

    Raises:
        RuntimeError: If tracing fails for any reason.
    """
    torch, nn = _require_torch()
    output_path = output_path or model_path.with_suffix(".torchscript.pt")
    logger.info("[TorchScript] Compiling model from %s -> %s", model_path.name, output_path.name)

    checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
    model_type = str(checkpoint.get("model_type") or "")
    if model_type == "legacy-rule-mlp" or "classifier_state_dict" not in checkpoint:
        raise RuntimeError(
            "[TorchScript] Only hybrid ResNet50-Siamese models can be compiled to TorchScript."
        )

    backbone, head_model, embedding_dim, class_names, rule_dim, _num_streams = _reconstruct_backbone_and_head(checkpoint)

    wrapper = CompleteSiameseModel(backbone, head_model)
    wrapper.eval()

    img_size = int(checkpoint.get("image_size", DEFAULT_IMAGE_SIZE))
    rule_dim = len(checkpoint.get("rule_feature_names", RULE_FEATURE_NAMES))
    dummy_left = torch.zeros(1, 3, img_size, img_size, dtype=torch.float32)
    dummy_right = torch.zeros(1, 3, img_size, img_size, dtype=torch.float32)
    dummy_rule = torch.zeros(1, rule_dim, dtype=torch.float32)

    with torch.no_grad():
        traced = torch.jit.trace(wrapper, (dummy_left, dummy_right, dummy_rule))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    traced.save(str(output_path))
    logger.info("[TorchScript] Saved -> %s", output_path.name)
    return output_path
