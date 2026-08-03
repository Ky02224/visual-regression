from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

@dataclass
class ScheduledJob:
    job_id: str
    name: str
    cron_expression: str  # e.g. '*/5 * * * *'
    suite_path: str
    enabled: bool = True
    last_run: float | None = None
    next_run: float | None = None

class Scheduler:
    """Lightweight cron-like scheduler for running visual regression suites."""

    def __init__(self, db_store: Any, paths: Any):
        self.db_store = db_store
        self.paths = paths
        self.jobs_file = paths.root / "schedules.json"
        self.jobs: Dict[str, ScheduledJob] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        self.load_jobs()

    def load_jobs(self):
        with self._lock:
            if not self.jobs_file.exists():
                self.jobs = {}
                return
            try:
                data = json.loads(self.jobs_file.read_text(encoding="utf-8"))
                self.jobs = {
                    jid: ScheduledJob(**jdata)
                    for jid, jdata in data.items()
                }
                logger.info("[Scheduler] Loaded %d jobs from %s", len(self.jobs), self.jobs_file.name)
            except Exception as e:
                logger.error("[Scheduler] Failed to load jobs: %s", e)
                self.jobs = {}

    def save_jobs(self):
        with self._lock:
            try:
                self.paths.root.mkdir(parents=True, exist_ok=True)
                serialized = {jid: asdict(job) for jid, job in self.jobs.items()}
                self.jobs_file.write_text(json.dumps(serialized, indent=2), encoding="utf-8")
            except Exception as e:
                logger.error("[Scheduler] Failed to save jobs: %s", e)

    def add_job(self, name: str, cron_expression: str, suite_path: str) -> str:
        job_id = f"job_{int(time.time())}_{len(self.jobs)}"
        job = ScheduledJob(
            job_id=job_id,
            name=name,
            cron_expression=cron_expression,
            suite_path=suite_path,
            enabled=True,
            next_run=self._calculate_next_run(cron_expression, time.time()),
        )
        with self._lock:
            self.jobs[job_id] = job
        self.save_jobs()
        logger.info("[Scheduler] Added job: %s (%s)", name, cron_expression)
        return job_id

    def remove_job(self, job_id: str) -> bool:
        with self._lock:
            removed = self.jobs.pop(job_id, None) is not None
        if removed:
            self.save_jobs()
            logger.info("[Scheduler] Removed job: %s", job_id)
        return removed

    def enable_job(self, job_id: str, enabled: bool) -> bool:
        # save_jobs() takes _lock itself, so calling it from inside this method's
        # own `with self._lock` deadlocked the calling thread outright — and
        # /api/scheduler/jobs/toggle calls straight into here, so toggling a job
        # from the dashboard hung that request forever. add_job and remove_job
        # already release the lock before saving; this now matches them.
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None:
                return False
            job.enabled = enabled
            job.next_run = (
                self._calculate_next_run(job.cron_expression, time.time()) if enabled else None
            )
        self.save_jobs()
        return True

    def list_jobs(self) -> List[ScheduledJob]:
        with self._lock:
            return list(self.jobs.values())

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            logger.info("[Scheduler] Background scheduler thread started")

    def stop(self):
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            logger.info("[Scheduler] Background scheduler thread stopped")

    def _loop(self):
        while self._running:
            try:
                now = time.time()
                jobs_to_run = []
                should_save = False
                with self._lock:
                    for job in self.jobs.values():
                        if not job.enabled:
                            continue
                        # If next_run calculation failed or is missing, compute it
                        if job.next_run is None:
                            next_val = self._calculate_next_run(job.cron_expression, now)
                            if next_val is None:
                                logger.error(
                                    "[Scheduler] Invalid cron expression or no match within 1 year for job '%s': '%s'. Disabling job.",
                                    job.name,
                                    job.cron_expression,
                                )
                                job.enabled = False
                                should_save = True
                                continue
                            else:
                                job.next_run = next_val
                        
                        if job.next_run and now >= job.next_run:
                            jobs_to_run.append(job)
                            # Update schedules
                            job.last_run = now
                            next_val = self._calculate_next_run(job.cron_expression, now + 1.0)
                            if next_val is None:
                                logger.error(
                                    "[Scheduler] Invalid cron expression or no match within 1 year for job '%s': '%s'. Disabling job.",
                                    job.name,
                                    job.cron_expression,
                                )
                                job.enabled = False
                                job.next_run = None
                                should_save = True
                            else:
                                job.next_run = next_val
                
                if jobs_to_run or should_save:
                    self.save_jobs()
                    for job in jobs_to_run:
                        # Run job in thread or subprocess
                        threading.Thread(target=self._run_job_action, args=(job,), daemon=True).start()

            except Exception as e:
                logger.error("[Scheduler] Error in scheduler loop: %s", e)
            
            # Check every 10 seconds (ticks are fast, but action depends on cron precision)
            time.sleep(10)

    def _run_job_action(self, job: ScheduledJob):
        logger.info("[Scheduler] Triggering job '%s' (Suite: %s)", job.name, job.suite_path)
        try:
            import sys
            cmd = [sys.executable, "-m", "visual_regression", "run-suite", job.suite_path]
            # Capture output and log with 600s timeout
            res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=600.0)
            if res.returncode == 0:
                logger.info("[Scheduler] Job '%s' completed successfully", job.name)
            else:
                logger.error("[Scheduler] Job '%s' failed with code %d. Error: %s", job.name, res.returncode, res.stderr)
        except Exception as e:
            logger.error("[Scheduler] Exception running job '%s': %s", job.name, e)

    def _calculate_next_run(self, cron_expr: str, from_timestamp: float) -> Optional[float]:
        """Calculates next run timestamp using croniter if installed, falling back to simple minute-by-minute search."""
        try:
            from croniter import croniter
            from datetime import datetime, timezone
            # Convert timestamp to UTC datetime
            base = datetime.fromtimestamp(from_timestamp, timezone.utc)
            iter = croniter(cron_expr, base)
            return float(iter.get_next(datetime).timestamp())
        except ImportError:
            pass
        except Exception as e:
            logger.error("[Scheduler] Error parsing cron '%s' with croniter: %s", cron_expr, e)

        try:
            parts = cron_expr.split()
            if len(parts) != 5:
                raise ValueError("Cron expression must have 5 fields")
            
            # Find next minute
            t = from_timestamp + 60.0
            for _ in range(525600):  # Search up to 1 year in minutes
                struct = time.localtime(t)
                # tm_wday is 0=Monday (Python) but cron is usually 0=Sunday. Convert:
                # Python tm_wday: 0(Mon)-6(Sun). Cron wday: 0(Sun)-6(Sat) or 7(Sun).
                cron_wday = (struct.tm_wday + 1) % 7
                if self._match_field(parts[0], struct.tm_min) and \
                   self._match_field(parts[1], struct.tm_hour) and \
                   self._match_field(parts[2], struct.tm_mday) and \
                   self._match_field(parts[3], struct.tm_mon) and \
                   (self._match_field(parts[4], cron_wday) or (parts[4] == '7' and cron_wday == 0)):
                    return float(time.mktime(struct))
                t += 60.0
        except Exception as e:
            logger.error("[Scheduler] Error parsing cron '%s': %s", cron_expr, e)
        return None

    def _match_field(self, pattern: str, value: int) -> bool:
        if pattern == "*":
            return True
        if "," in pattern:
            return any(self._match_field(p, value) for p in pattern.split(","))
        if pattern.startswith("*/"):
            step = int(pattern[2:])
            return value % step == 0
        if "/" in pattern:
            parts = pattern.split("/")
            step = int(parts[1])
            base_pattern = parts[0]
            if base_pattern == "*":
                return value % step == 0
            if "-" in base_pattern:
                start, end = map(int, base_pattern.split("-"))
                return start <= value <= end and (value - start) % step == 0
            return value % step == 0
        if "-" in pattern:
            start, end = map(int, pattern.split("-"))
            return start <= value <= end
        return int(pattern) == value
