"""The optional vision-LLM narration must not destroy the DOM-diff evidence.

_add_ollama_explanation_if_needed used to assign over assessment.ai_explanation.
Where a structural DOM comparison had already written a specific, checkable
sentence about the page, enabling the flag replaced it with generated prose
about the same crop — an auditable finding swapped for an unverifiable one.
These tests pin the flag's default (off), and that when it is on the evidence
survives.
"""
import numpy as np
import pytest

from visual_regression.ai_training import _add_ollama_explanation_if_needed
from visual_regression.models import AIAssessment

DOM_EVIDENCE = "DOM diff: the <img> at (399,417) decoded to nothing (naturalWidth 0)."


def _assessment(explanation: str = DOM_EVIDENCE) -> AIAssessment:
    return AIAssessment(
        score=0.9, label="broken-image", threshold=0.35, model_name="test",
        ai_explanation=explanation,
    )


def _crops():
    img = np.zeros((32, 32, 3), dtype=np.uint8)
    return [(img, img)]


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("VRT_ENABLE_OLLAMA", raising=False)
    called = []
    monkeypatch.setattr(
        "visual_regression.ai_training.query_ollama_for_explanation",
        lambda *a, **k: called.append(1) or "narration",
    )
    assessment = _assessment()
    _add_ollama_explanation_if_needed(assessment, _crops(), 1.0)

    assert not called, "the service must not be contacted unless explicitly enabled"
    assert assessment.ai_explanation == DOM_EVIDENCE


def test_enabled_appends_and_keeps_the_dom_evidence(monkeypatch):
    monkeypatch.setenv("VRT_ENABLE_OLLAMA", "true")
    monkeypatch.setattr(
        "visual_regression.ai_training.query_ollama_for_explanation",
        lambda *a, **k: "The product thumbnail failed to load.",
    )
    assessment = _assessment()
    _add_ollama_explanation_if_needed(assessment, _crops(), 1.0)

    # The checkable claim is what a reviewer acts on; it has to still be there.
    assert DOM_EVIDENCE in assessment.ai_explanation
    assert "The product thumbnail failed to load." in assessment.ai_explanation


def test_a_silent_service_leaves_the_evidence_untouched(monkeypatch):
    """Ollama not installed / model not pulled returns "" — that must not
    blank out an explanation the DOM diff had already produced."""
    monkeypatch.setenv("VRT_ENABLE_OLLAMA", "true")
    monkeypatch.setattr(
        "visual_regression.ai_training.query_ollama_for_explanation",
        lambda *a, **k: "",
    )
    assessment = _assessment()
    _add_ollama_explanation_if_needed(assessment, _crops(), 1.0)

    assert assessment.ai_explanation == DOM_EVIDENCE


def test_narration_stands_alone_when_there_was_no_evidence(monkeypatch):
    monkeypatch.setenv("VRT_ENABLE_OLLAMA", "true")
    monkeypatch.setattr(
        "visual_regression.ai_training.query_ollama_for_explanation",
        lambda *a, **k: "The heading font changed.",
    )
    assessment = _assessment(explanation="")
    _add_ollama_explanation_if_needed(assessment, _crops(), 1.0)

    assert assessment.ai_explanation == "The heading font changed."


@pytest.mark.parametrize("label", ["", None])
def test_no_label_means_nothing_to_narrate(monkeypatch, label):
    monkeypatch.setenv("VRT_ENABLE_OLLAMA", "true")
    called = []
    monkeypatch.setattr(
        "visual_regression.ai_training.query_ollama_for_explanation",
        lambda *a, **k: called.append(1) or "narration",
    )
    assessment = _assessment()
    assessment.label = label
    _add_ollama_explanation_if_needed(assessment, _crops(), 1.0)

    assert not called
