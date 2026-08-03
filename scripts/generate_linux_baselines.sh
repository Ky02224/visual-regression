#!/usr/bin/env bash
# Capture baselines inside the project's own Docker image.
#
# Baselines are only meaningful when the environment that produced them matches
# the environment that compares against them. Chromium renders text differently
# across platforms and font sets, so a baseline captured on a Windows dev
# machine fails against a Linux runner for reasons that have nothing to do with
# the page. Capturing inside the image the CI job also uses removes that gap.
#
# Usage:
#   docker build -t visual-regression:local .
#   bash scripts/generate_linux_baselines.sh [suite]
#
# Default suite is suite.ci-smoke.yaml — the one visual-test.yml runs.
set -euo pipefail

SUITE="${1:-suite.ci-smoke.yaml}"
IMAGE="${IMAGE:-visual-regression:local}"
OUT_DIR="$(pwd)/.visual-regression/baselines"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Image '$IMAGE' not found. Build it first:" >&2
    echo "    docker build -t $IMAGE ." >&2
    exit 1
fi

mkdir -p "$OUT_DIR"

# Git Bash on Windows rewrites arguments that look like absolute POSIX paths
# into Windows ones, so `-w /app` arrives as 'C:/Program Files/Git/app' and
# docker rejects it. MSYS_NO_PATHCONV turns that off for this invocation.
export MSYS_NO_PATHCONV=1

echo "Capturing baselines for $SUITE inside $IMAGE"
echo "Writing to $OUT_DIR"
echo

# The container serves the demo portal itself and captures against 127.0.0.1, so
# nothing outside the container is involved and the result is reproducible.
docker run --rm \
    -v "$OUT_DIR:/app/.visual-regression/baselines" \
    -w /app \
    "$IMAGE" \
    bash -c "
        set -euo pipefail
        python -m visual_regression.cli serve-dashboard --port 8130 --host 127.0.0.1 &
        SERVER_PID=\$!
        trap 'kill \$SERVER_PID 2>/dev/null || true' EXIT

        python - <<'WAIT'
import time, urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen('http://127.0.0.1:8130/demo/index.html?lang=en-US', timeout=3)
        print('Dashboard ready.')
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit('Dashboard did not start in time.')
WAIT

        python -m visual_regression.cli create-suite-baselines --suite '$SUITE' --overwrite
    "

echo
echo "Done. Review, then commit:"
echo "    git add .visual-regression/baselines/"
echo "    git status --short .visual-regression/baselines/"
