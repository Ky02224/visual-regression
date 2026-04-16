from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DiffRegion:
    x: int
    y: int
    width: int
    height: int
    area: int
    mean_delta: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CompareResult:
    baseline_size: List[int]
    current_size: List[int]
    diff_pixels: int
    total_pixels: int
    mismatch_pct: float
    ssim_score: Optional[float]
    regions: List[DiffRegion] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_size": self.baseline_size,
            "current_size": self.current_size,
            "diff_pixels": self.diff_pixels,
            "total_pixels": self.total_pixels,
            "mismatch_pct": self.mismatch_pct,
            "ssim_score": self.ssim_score,
            "regions": [region.to_dict() for region in self.regions],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompareResult":
        return cls(
            baseline_size=list(data.get("baseline_size", [])),
            current_size=list(data.get("current_size", [])),
            diff_pixels=int(data.get("diff_pixels", 0)),
            total_pixels=int(data.get("total_pixels", 0)),
            mismatch_pct=float(data.get("mismatch_pct", 0.0)),
            ssim_score=data.get("ssim_score"),
            regions=[DiffRegion(**region) for region in data.get("regions", [])],
        )


@dataclass
class AIAssessment:
    score: float
    label: str
    threshold: float
    model_name: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewRecord:
    status: str
    reviewer: str | None = None
    comment: str | None = None
    timestamp: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
