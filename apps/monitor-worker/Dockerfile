# SafeJourney monitor-worker — Cloud Run image.
# Build context is the REPO ROOT (needs shared + agent-api engine):
#   docker build -f apps/monitor-worker/Dockerfile -t safejourney-monitor .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Shared domain package.
COPY packages/shared /packages/shared
RUN pip install /packages/shared

# The monitoring engine lives in the agent-api package; install it (without ADK — the
# worker only needs the engine, tools and repo, and imports ADK lazily if ever used).
COPY apps/agent-api /agent-api
RUN pip install /agent-api

# Worker deps + code.
COPY apps/monitor-worker/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY apps/monitor-worker /app

# Cloud Run injects PORT (defaults to 8080). Honor it via shell expansion so the container
# always listens where Cloud Run sends traffic.
ENV PORT=8080
CMD ["/bin/sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
