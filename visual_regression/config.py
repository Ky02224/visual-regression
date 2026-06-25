from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class WorkspacePaths:
    root: Path = Path(".visual-regression")
    baselines_dir: Path = field(init=False)
    runs_dir: Path = field(init=False)
    reports_dir: Path = field(init=False)
    reviews_dir: Path = field(init=False)
    models_dir: Path = field(init=False)
    datasets_dir: Path = field(init=False)
    builds_dir: Path = field(init=False)
    db_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.baselines_dir = self.root / "baselines"
        self.runs_dir = self.root / "runs"
        self.reports_dir = self.root / "reports"
        self.reviews_dir = self.root / "reviews"
        self.models_dir = self.root / "models"
        self.datasets_dir = self.root / "datasets"
        self.builds_dir = self.root / "builds"
        
        import os
        db_env = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PATH")
        if db_env:
            if db_env.startswith("sqlite:///"):
                self.db_path = Path(db_env[10:])
            else:
                self.db_path = Path(db_env)
        else:
            self.db_path = self.root / "storage.db"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.baselines_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.reviews_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.datasets_dir.mkdir(parents=True, exist_ok=True)
        self.builds_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class CaptureConfig:
    name: str
    url: str
    browser: str = "chromium"
    device: str | None = None
    viewport: Tuple[int, int] = (1440, 900)
    wait_ms: int = 1200
    wait_until: str = "networkidle"
    navigation_timeout_ms: int = 45000
    full_page: bool = True
    disable_animations: bool = True
    locale: str | None = None
    timezone_id: str | None = None
    color_scheme: str = "light"
    extra_headers: Dict[str, str] = field(default_factory=dict)
    hide_selectors: List[str] = field(default_factory=list)
    wait_for_selector: str | None = None
    mock_routes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompareConfig:
    threshold_pct: float = 0.50
    pixel_threshold: int = 20
    min_region_area: int = 120
