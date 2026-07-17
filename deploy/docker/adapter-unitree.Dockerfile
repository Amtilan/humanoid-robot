# Real Unitree G1 adapter image.
#
# Extends the CPU base with the vendor Python SDK (unitree_sdk2_python)
# and its CycloneDDS backend, so `cortex-robot-adapter run unitree_g1_edu`
# can join the G1 DDS domain on the robot's control interface (eth10).
#
# The base image already carries our humanoid-robot-adapters-unitree-g1
# package (part of the workspace `uv sync --all-packages`); this image
# only adds the vendor runtime deps its lazy loader (sdk.py) imports:
#   unitree_sdk2py.core.channel
#   unitree_sdk2py.g1.audio.g1_audio_client
#   unitree_sdk2py.g1.arm.g1_arm_action_client
#   unitree_sdk2py.g1.loco.g1_loco_client (optional)
#
# arm64-only in practice — it only ever runs on the Jetson. Build it
# natively on the robot (see deploy/scripts/build-unitree-adapter.sh) to
# avoid QEMU emulation of the CycloneDDS C build.

ARG BASE_IMAGE=ghcr.io/amtilan/humanoid-robot-base:main
FROM ${BASE_IMAGE}

USER root

# Toolchain for the CycloneDDS C library + the cyclonedds python binding's
# native extension. git is needed to fetch the pinned sources.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        cmake \
        build-essential \
        alsa-utils \
    && rm -rf /var/lib/apt/lists/*

# CycloneDDS C runtime. unitree_sdk2_python pins the 0.10.x line; keep
# the C lib and the python wheel on the same minor to avoid ABI drift.
ARG CYCLONEDDS_VERSION=0.10.2
RUN git clone --depth 1 -b "${CYCLONEDDS_VERSION}" \
        https://github.com/eclipse-cyclonedds/cyclonedds /tmp/cyclonedds \
    && cmake -S /tmp/cyclonedds -B /tmp/cyclonedds/build \
        -DCMAKE_INSTALL_PREFIX=/opt/cyclonedds \
        -DBUILD_EXAMPLES=OFF \
        -DBUILD_TESTING=OFF \
    && cmake --build /tmp/cyclonedds/build --target install -j"$(nproc)" \
    && rm -rf /tmp/cyclonedds
ENV CYCLONEDDS_HOME=/opt/cyclonedds

# Install the vendor SDK + its DDS binding INTO the workspace venv so the
# already-on-PATH `cortex-robot-adapter` console script imports them.
# uv is installed fresh (the slim base's pip has it available); the
# uv-created venv has no pip of its own.
RUN pip install --no-cache-dir uv \
    && CYCLONEDDS_HOME=/opt/cyclonedds uv pip install \
        --python /workspace/.venv/bin/python \
        "cyclonedds==${CYCLONEDDS_VERSION}" \
    && uv pip install \
        --python /workspace/.venv/bin/python \
        "git+https://github.com/unitreerobotics/unitree_sdk2_python.git"

# Voice runtime. cortex-voice runs on THIS image (host net for the G1 mic +
# speaker), and its ASR/TTS/VAD adapters lazily import these — the base image
# ships the adapter packages but not their `[runtime]` extras, so without this
# the pipeline reaches TTS and dies with "No module named 'piper'". All have
# prebuilt aarch64 wheels (no source build under QEMU).
RUN uv pip install \
        --python /workspace/.venv/bin/python \
        "faster-whisper>=1.1" "piper-tts>=1.4" "silero-vad>=5.1" \
        "onnxruntime>=1.19" "numpy>=1.24"

# CycloneDDS shared libs live outside the default loader path.
ENV LD_LIBRARY_PATH=/opt/cyclonedds/lib:/opt/cyclonedds/lib64:${LD_LIBRARY_PATH:-}

# Fail fast at build time if the import contract the adapter relies on
# isn't satisfied — better here than at first hardware contact.
RUN /workspace/.venv/bin/python -c "\
import unitree_sdk2py.core.channel; \
import unitree_sdk2py.g1.audio.g1_audio_client; \
import unitree_sdk2py.g1.arm.g1_arm_action_client; \
print('unitree_sdk2py import OK')"

# Voice runtime import contract — the exact modules the ASR/TTS/VAD adapters
# import lazily. Fail the build here rather than at first utterance.
RUN /workspace/.venv/bin/python -c "\
import faster_whisper; \
import piper.voice; \
import silero_vad; \
import onnxruntime; \
print('voice runtime import OK')"
