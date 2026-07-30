# Stage 1: Build React Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/dashboard_frontend
COPY dashboard_frontend/package*.json ./
RUN npm ci
COPY dashboard_frontend/ ./
RUN npm run build

# Stage 2: Python Runtime and Server Setup
# Pinned to bookworm (not the floating `python:3.11-slim` tag): that tag now
# resolves to Debian 13 "trixie", which playwright==1.51.0's `install-deps`
# doesn't recognize — it falls back to an Ubuntu 20.04 package list and fails
# on renamed font packages (ttf-unifont/ttf-ubuntu-font-family no longer exist).
FROM python:3.11-slim-bookworm
WORKDIR /app

LABEL maintainer="FYP Visual Regression Testing System" \
      description="AI-powered visual regression testing dashboard" \
      version="1.0.0"

# Install curl (required for HEALTHCHECK) and Playwright system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy python dependencies and install
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium and its OS dependencies.
# PLAYWRIGHT_BROWSERS_PATH pins the install location under /app instead of
# root's default $HOME/.cache/ms-playwright: the app drops to the non-root
# `appuser` below (whose home isn't root's), and without this the browser
# binary installed here is invisible/inaccessible at runtime, so every
# capture silently fails with "Executable doesn't exist".
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.ms-playwright
RUN playwright install chromium && playwright install-deps chromium

# Copy Python backend files
COPY visual_regression/ ./visual_regression/
COPY suite.demo.yaml suite.ci-smoke.yaml ./

# The demo portal is the target of every URL in suite.demo.yaml
# (http://127.0.0.1:8130/demo/...) and is served by dashboard_server's
# /demo/{file_path} route straight off the filesystem. Without it in the image
# those routes 404 and the bundled suite cannot run at all.
COPY demo_portal/ ./demo_portal/

# Copy built frontend assets from Stage 1
COPY --from=frontend-builder /app/dashboard_frontend/dist ./dashboard_frontend/dist

# Expose server port
EXPOSE 8130

# Health check — verifies the API is responding every 30 seconds
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8130/api/health || exit 1

# Setup runtime environment directories and non-root user.
# The app writes under /app/.visual-regression (see config.py WorkspacePaths),
# which is also the named volume mount point in docker-compose.yml — it must
# already exist with correct ownership in the image, otherwise Docker creates
# it as root-owned on first volume mount and the app can't write to it.
RUN mkdir -p /app/.visual-regression/baselines \
             /app/.visual-regression/runs \
             /app/.visual-regression/reports \
             /app/.visual-regression/reviews \
             /app/.visual-regression/models \
             /app/.visual-regression/datasets \
             /app/.visual-regression/builds && \
    addgroup --system appgroup && \
    adduser --system --ingroup appgroup appuser && \
    chown -R appuser:appgroup /app

USER appuser

# Run the dashboard server (binding to 0.0.0.0 for container access)
CMD ["python", "-m", "visual_regression.cli", "serve-dashboard", "--port", "8130", "--host", "0.0.0.0"]
