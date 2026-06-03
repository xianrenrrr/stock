# Multi-stage build for the STOCK system on Render.
# Cloud build skips the [gui] extra (pyautogui won't run on Linux without X server).

FROM python:3.12-slim AS base

# OS packages: build tools for compiled deps (sqlite-vec, sentence-transformers,
# httpx[h2], etc.), plus tzdata for cron triggers. pkg-config + libcairo2-dev are
# required to build pycairo from sdist -- it has no Linux wheel and is pulled in
# transitively by xhtml2pdf -> svglib -> rlpycairo -> pycairo (PDF export). Without
# them the deps layer fails with "Run-time dependency cairo found: NO".
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        tzdata \
        pkg-config \
        libcairo2-dev \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

WORKDIR /app

# --- deps stage ---
# CRITICAL: install dependencies based ONLY on pyproject.toml so the heavy
# pip layer is cached as long as the dep list is unchanged. The previous
# version COPY'd src/ before pip install, which invalidated the deps layer
# on every code commit -- meaning Render reinstalled
# torch+sentence-transformers+pandas+scipy from scratch on every deploy
# (~12-20 min). Now a code-only commit reuses the cached layer (~30 sec).
#
# Trick: we need src/stock to exist for `pip install -e .` to succeed, but
# we don't want the real source in this layer (it would re-bust the cache).
# Stub it with a one-line __init__.py; the COPY below overwrites with real code.
COPY pyproject.toml ./
RUN mkdir -p src/stock \
    && echo '"""stock package -- stub during dep install layer."""' > src/stock/__init__.py \
    && python -m pip install -e .

# --- runtime stage ---
# Now copy the real source. Editable install means imports resolve to /app/src/stock,
# so overwriting the stub with real files Just Works at runtime -- no reinstall needed.
COPY src/ ./src/
COPY prompts/ ./prompts/
COPY data/ ./data/
COPY scripts/ ./scripts/
COPY openclaw_skill/ ./openclaw_skill/
COPY README.md ./README.md
# tests are useful for "render run pytest" debugging, but optional in image:
COPY tests/ ./tests/

# Render injects PORT; default to 18790 for local docker runs.
ENV PORT=18790
EXPOSE 18790

# Persistent disk in Render mounts to /var/data; symlink so existing
# code paths (data/stock.db) keep working. Pre-create every symlink target as
# an empty directory at build time -- the free tier has no persistent disk so
# these need to exist or pathlib.mkdir() hits a dangling symlink. If a
# persistent disk is later mounted at /var/data, the mount shadows them.
RUN mkdir -p /var/data /var/data/wechat_inbox /var/data/wechat_outbox /var/data/rules \
    && rm -rf /app/data/stock.db /app/data/wechat_outbox /app/data/wechat_inbox /app/data/rules \
    && ln -sf /var/data/stock.db /app/data/stock.db \
    && ln -sf /var/data/wechat_outbox /app/data/wechat_outbox \
    && ln -sf /var/data/wechat_inbox /app/data/wechat_inbox \
    && ln -sf /var/data/rules /app/data/rules

# Healthcheck for Render (also reachable at /stock/health, no auth required).
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/stock/health" || exit 1

# `stock serve` blocks: starts FastAPI on PORT and the APScheduler in a daemon thread.
# We bind to 0.0.0.0 via uvicorn inside `run_api()` (override API_HOST via env if needed).
CMD ["python", "-m", "stock", "serve"]
