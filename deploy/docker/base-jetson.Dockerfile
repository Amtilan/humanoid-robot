# Jetson-native base image.
#
# Same workspace layout as base.Dockerfile, but rooted on
# nvcr.io/nvidia/l4t-pytorch so faster-whisper / BGE-M3 / llama.cpp
# can actually reach the Tegra iGPU at runtime.  ARM64-only — L4T
# containers don't exist for amd64.  The x86 flow keeps using the
# ordinary CPU-only base image.
#
# Pin: r36.2.0 corresponds to JetPack 6.0 GA. Bump both the tag here
# and any JetPack version references in deploy/README.md together.

FROM nvcr.io/nvidia/l4t-pytorch:r36.2.0-pth2.2-py3 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy

# L4T-PyTorch base already ships CUDA + cuDNN + torch. We only need
# curl (for healthchecks) and libgomp (for CTranslate2). apt lists
# come pre-cleaned in the L4T base but re-clean to be safe.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "uv>=0.11.11"

WORKDIR /workspace

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps ./apps
COPY plugins ./plugins

# --no-dev drops the workspace-wide dev deps; --python /usr/bin/python3
# keeps uv on the L4T-native interpreter so torch stays imported
# against the vendor CUDA build (a fresh venv would drag in the CPU
# wheel from PyPI and shadow the pre-installed one).
RUN uv sync \
    --all-packages \
    --frozen \
    --no-dev \
    --python /usr/bin/python3

ENV PATH="/workspace/.venv/bin:${PATH}" \
    HR_NATS__SERVERS='["nats://nats:4222"]' \
    HR_ROBOT_ADAPTER__NATS__SERVERS='["nats://nats:4222"]' \
    HR_VOICE__NATS__SERVERS='["nats://nats:4222"]'

CMD ["python", "-c", "import sys; sys.exit('choose an explicit command (cortex-core / cortex-robot-adapter / …)')"]
