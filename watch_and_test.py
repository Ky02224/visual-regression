"""
Auto Visual Regression Watcher
-------------------------------
Monitors your project files. When you save a change,
it automatically runs the visual regression suite and
opens the dashboard to show results.

Usage:
    python watch_and_test.py
    python watch_and_test.py --suite suite.demo.yaml
    python watch_and_test.py --suite suite.demo.yaml --watch-dir ./my_app
"""

import argparse
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

DASHBOARD_URL = "http://127.0.0.1:8130"
COOLDOWN_SECONDS = 3  # Debounce: wait 3s after last save before running

class ChangeHandler(FileSystemEventHandler):
    def __init__(self, suite: str, project_root: Path):
        self.suite = suite
        self.project_root = project_root
        self._pending = False
        self._last_event = 0

    def on_modified(self, event: FileSystemEvent):
        if event.is_directory:
            return
        path = str(event.src_path)
        # Ignore irrelevant files
        if any(x in path for x in [".visual-regression", "__pycache__", ".git", "node_modules", ".pyc"]):
            return
        self._last_event = time.time()
        if not self._pending:
            self._pending = True
            self._schedule_run()

    def _schedule_run(self):
        import threading
        def _wait_and_run():
            while True:
                time.sleep(0.5)
                if time.time() - self._last_event >= COOLDOWN_SECONDS:
                    break
            self._run_suite()
            self._pending = False
        threading.Thread(target=_wait_and_run, daemon=True).start()

    def _run_suite(self):
        print(f"\n{'='*60}")
        print(f"  Change detected — running visual regression suite...")
        print(f"  Suite: {self.suite}")
        print(f"{'='*60}\n")

        result = subprocess.run(
            [sys.executable, "-m", "visual_regression", "run-suite",
             "--suite", self.suite, "--no-junit"],
            cwd=str(self.project_root),
        )

        print(f"\n{'='*60}")
        if result.returncode == 0:
            print("  ✅  ALL TESTS PASSED")
        else:
            print("  ❌  REGRESSION DETECTED — check the dashboard!")
            webbrowser.open(DASHBOARD_URL)
        print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Auto visual regression watcher")
    parser.add_argument("--suite", default="suite.demo.yaml", help="Suite YAML file to run")
    parser.add_argument("--watch-dir", default=".", help="Directory to watch for changes")
    args = parser.parse_args()

    project_root = Path(__file__).parent.resolve()
    watch_dir = (project_root / args.watch_dir).resolve()
    suite_path = (project_root / args.suite).resolve()

    if not suite_path.exists():
        print(f"ERROR: Suite file not found: {suite_path}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  👁  Visual Regression Watcher")
    print(f"  Watching : {watch_dir}")
    print(f"  Suite    : {suite_path.name}")
    print(f"  Dashboard: {DASHBOARD_URL}")
    print(f"  Save any file to trigger auto comparison.")
    print(f"  Press Ctrl+C to stop.")
    print(f"{'='*60}\n")

    handler = ChangeHandler(suite=str(suite_path), project_root=project_root)
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nWatcher stopped.")
    observer.join()


if __name__ == "__main__":
    main()
