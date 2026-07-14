# syntax=docker/dockerfile:1
#
# CUDA-accelerated llama.cpp server for the Jetson Orin NX on the G1
# (L4T r35.3.1 / JetPack 5.1.1 / CUDA 11.4 / iGPU compute capability 8.7).
#
# Why build from source instead of pulling a tag:
#   * ghcr.io/ggml-org/llama.cpp:server-cuda is linux/amd64 only — it does
#     not run on Tegra/arm64.
#   * The only prebuilt Jetson image, dustynv/llama_cpp:r35.3.1, is frozen
#     at Aug-2023 llama.cpp — it predates the Qwen2.5 architecture and the
#     split-GGUF loader, so it cannot load our model.
# So we compile llama.cpp against the device's CUDA 11.4, targeting sm_87.
#
# Single stage on the -devel base: NVIDIA only publishes an l4t-cuda
# `-devel` tag for 11.4.19 (there is no `-runtime` tag), and the runtime
# CUDA libs we need (libcublas, libcudart) live in that same image, so a
# split build/runtime buys nothing but a second multi-GB base pull. Disk
# on the appliance is ample; keep it simple.
#
# This image is arm64-ONLY (it links Tegra CUDA); there is no amd64 variant.
# Build it natively on the Jetson or on a linux/arm64 runner — NOT under
# QEMU emulation (an emulated CUDA compile takes hours):
#
#   docker build -f deploy/docker/llamacpp-cuda.Dockerfile \
#     --build-arg LLAMACPP_REF=master \
#     -t humanoid-robot-llamacpp-cuda:r35.3.1 deploy/docker
#
# Run under the nvidia container runtime (runtime: nvidia) so the iGPU is
# visible; pass `-ngl 99` to offload every transformer layer to the GPU.

ARG L4T_CUDA=11.4.19

FROM nvcr.io/nvidia/l4t-cuda:${L4T_CUDA}-devel
ARG LLAMACPP_REF=master
ENV DEBIAN_FRONTEND=noninteractive
# The -devel image carries the CUDA headers + cuBLAS but not nvcc, so pull the
# matching compiler from the L4T apt repo that ships in the image. The base
# (Ubuntu 20.04) apt cmake is 3.16, but the ggml-cuda backend needs >= 3.18 —
# get a current cmake from pip instead (installs to /usr/local/bin, ahead of
# /usr/bin on PATH).
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ninja-build build-essential ccache python3 python3-pip \
        cuda-nvcc-11-4 cuda-cudart-dev-11-4 libcublas-dev-11-4 \
        libcurl4-openssl-dev libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir "cmake>=3.22,<4"
ENV PATH=/usr/local/bin:/usr/local/cuda/bin:${PATH} \
    CUDA_HOME=/usr/local/cuda \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64
WORKDIR /src
RUN git clone --depth 1 --branch "${LLAMACPP_REF}" \
        https://github.com/ggml-org/llama.cpp.git . 2>/dev/null \
    || (git clone https://github.com/ggml-org/llama.cpp.git . \
        && git checkout "${LLAMACPP_REF}")
# sm_87 = Orin. GGML_NATIVE off keeps the CPU codegen portable across the
# build host; the GPU path is what matters here. No `|| true` masking — a
# compile failure must fail the image build, not ship an empty one. Kept as
# its own layer so the ~40-min compile stays cached across later edits.
RUN cmake -B build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DGGML_CUDA=ON \
        -DCMAKE_CUDA_ARCHITECTURES=87 \
        -DGGML_NATIVE=OFF \
        -DGGML_CUDA_FORCE_MMQ=ON \
        -DLLAMA_CURL=ON \
    && cmake --build build --config Release -j"$(nproc)" \
    && cmake --install build --prefix /usr/local \
    && ldconfig
# Verify the binary exists — do NOT run it: CUDA binaries need libcuda.so.1,
# which the nvidia container runtime only injects at RUN time, not build time.
RUN test -x /usr/local/bin/llama-server \
    || ( cp build/bin/llama-server /usr/local/bin/ && ldconfig )
EXPOSE 8080
# HEALTHCHECK mirrors the compose one so `docker run` alone is observable.
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=10 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1
ENTRYPOINT ["llama-server"]
CMD ["--host", "0.0.0.0", "--port", "8080"]
