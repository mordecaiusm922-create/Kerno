# Kerno runtime image (API and workers). Non-root, hash-pinned dependencies.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt

COPY pyproject.toml README.md ./
COPY kerno ./kerno
COPY models ./models
RUN pip install --no-deps . && useradd --system --uid 10001 kerno && mkdir -p /data && chown kerno /data
USER kerno

ENV KERNO_MODELS_DIR=/app/models KERNO_ARCHIVE_DIR=/data/archive
EXPOSE 8000
# default: API. Workers: `docker run ... kerno run-all`
CMD ["kerno", "api", "--host", "0.0.0.0", "--port", "8000"]
