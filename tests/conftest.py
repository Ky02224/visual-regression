import os

# Explicit, documented signal that the dashboard server is running under the
# test suite: it must route CLI actions through subprocess.run (which tests
# patch) instead of an in-process cli.main() call or a real Playwright
# browser launch. See visual_regression.dashboard_server._is_test_environment.
os.environ["VRT_TEST_MODE"] = "1"
