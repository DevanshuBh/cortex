# syntax=docker/dockerfile:1.7
# CORTEX backend image: API, Celery workers and CLI. Multi-stage, non-root, models baked in (offline start).
ARG PYTHON_IMAGE=python:3.13.18-slim

FROM ghcr.io/astral-sh/uv:0.13.8 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_HTTP_TIMEOUT=180 UV_CONCURRENT_DOWNLOADS=4 UV_HTTP_RETRIES=8
WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --extra eval --no-install-project
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --extra eval --no-editable

# Download the pinned embedding model and reranker at build time (revisions come from cortex.config).
FROM build AS models
ENV HF_HOME=/opt/models
RUN /opt/venv/bin/python - <<'PY'
from sentence_transformers import CrossEncoder, SentenceTransformer
from cortex.config import get_settings
s = get_settings()
SentenceTransformer(s.embedding_model, revision=s.embedding_revision, device="cpu")
CrossEncoder(s.reranker_model, revision=s.reranker_revision, device="cpu")
PY

FROM ${PYTHON_IMAGE} AS runtime
RUN groupadd --system --gid 10001 cortex && useradd --system --uid 10001 --gid cortex --home /app cortex
COPY --from=build /opt/venv /opt/venv
COPY --from=build /src /app
COPY --from=models --chown=cortex:cortex /opt/models /opt/models
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    XDG_CACHE_HOME=/tmp/.cache HOME=/tmp
WORKDIR /app
USER 10001:10001
EXPOSE 8000 9100
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)" || exit 1
CMD ["uvicorn", "cortex.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-graceful-shutdown", "20"]
