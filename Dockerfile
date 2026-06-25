# Stage 1: Build React Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/dashboard_frontend
COPY dashboard_frontend/package*.json ./
RUN npm ci
COPY dashboard_frontend/ ./
RUN npm run build

# Stage 2: Python Runtime and Server Setup
FROM python:3.11-slim
WORKDIR /app

LABEL maintainer="FYP Visual Regression Testing System" \
      description="AI-powered visual regression testing dashboard" \
      version="1.0.0"

# Install system dependencies required for Playwright / headless browsers
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy python dependencies and install
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-dev.txt

# Install Playwright Chromium and its OS dependencies
RUN playwright install chromium && playwright install-deps chromium

# Copy Python backend files
COPY visual_regression/ ./visual_regression/
COPY baselines/ ./baselines/
COPY suite.demo.yaml ./

# Copy built frontend assets from Stage 1
COPY --from=frontend-builder /app/dashboard_frontend/dist ./dashboard_frontend/dist

# Expose server port
EXPOSE 8130

# Health check — verifies the API is responding every 30 seconds
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8130/api/health || exit 1

# Run the dashboard server (binding to 0.0.0.0 for container access)
CMD ["python", "-m", "visual_regression.cli", "serve-dashboard", "--port", "8130", "--host", "0.0.0.0"]
