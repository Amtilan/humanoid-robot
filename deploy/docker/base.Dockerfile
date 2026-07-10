# Base image for every Python service in the humanoid-robot stack.
# Builds a single image with the whole uv workspace installed so services
# can `uv run cortex-core / cortex-robot-adapter / …` without any host-side
# Python setup.

FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "uv>=0.11.11"

WORKDIR /workspace

# Pull in the manifest layer first so lockfile changes don't invalidate
# the source-copy cache.
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps ./apps
COPY plugins ./plugins

# Install the workspace. Runtime image excludes dev extras.
RUN uv sync --all-packages --frozen --no-dev

ENV PATH="/workspace/.venv/bin:${PATH}"

# Sensible defaults; each service overrides in compose.
ENV HR_NATS__SERVERS='["nats://nats:4222"]' \
    HR_ROBOT_ADAPTER__NATS__SERVERS='["nats://nats:4222"]' \
    HR_VOICE__NATS__SERVERS='["nats://nats:4222"]'

# The compose file names an explicit command per service; keep the default
# empty so a bare `docker run humanoid-robot-base` exits with an error.
CMD ["python", "-c", "import sys; sys.exit('choose an explicit command (cortex-core / cortex-robot-adapter / …)')"]
