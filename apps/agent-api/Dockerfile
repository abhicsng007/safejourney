# SafeJourney agent-api — Cloud Run image.
# Build context is the REPO ROOT so the shared package is available:
#   docker build -f apps/agent-api/Dockerfile -t safejourney-api .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install shared package first (better layer caching).
COPY packages/shared /packages/shared
RUN pip install /packages/shared

# Install agent-api deps.
COPY apps/agent-api/requirements.txt ./requirements.txt
# The editable file:../../ reference isn't valid in the image; shared is already installed,
# so drop that line before installing the rest.
RUN grep -v "safejourney-shared" requirements.txt > reqs.txt && pip install -r reqs.txt

COPY apps/agent-api /app

ENV PORT=8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
