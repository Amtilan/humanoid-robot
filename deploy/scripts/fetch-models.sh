#!/usr/bin/env bash
#
# Fetch reference models for the humanoid-robot voice + RAG pipelines
# into /var/lib/humanoid-robot/models on the host.  Idempotent: skips
# any files already present.
#
# Model choice comes from deploy/config/voice.yaml and rag.yaml.  Swap
# a URL below by editing this script before running — we deliberately
# don't wire this into any automated flow so a model upgrade is always
# a conscious decision.
#
# Usage:
#   sudo bash deploy/scripts/fetch-models.sh          # full set
#   sudo MODELS="asr tts"  bash deploy/scripts/fetch-models.sh  # subset
#
# Approximate on-disk sizes (INT4/INT8 quantized where possible):
#   asr           ~1.5 GB   faster-whisper-large-v3-turbo-int8
#   tts           ~30 MB    piper voices (ru + en)
#   wake          ~5 MB     openwakeword hey_robot
#   embedder      ~2.2 GB   BGE-M3
#   reranker      ~600 MB   BGE-reranker-v2-m3
#   llm           ~5 GB     Qwen 3 8B Instruct GGUF Q5_K_M
#
#   Full download: ~9.5 GB. Bandwidth-check before starting.

set -euo pipefail

MODELS_DIR="${MODELS_DIR:-/var/lib/humanoid-robot/models}"
MODELS="${MODELS:-asr tts wake embedder reranker llm}"

# --- Model URLs (edit these to swap versions) ---------------------------------
# Systran/faster-whisper-large-v3-turbo became gated (401); deepdml's CT2
# conversion of the same model is public and byte-compatible for
# faster-whisper.
URL_ASR_TAR="https://huggingface.co/deepdml/faster-whisper-large-v3-turbo-ct2/resolve/main"
ASR_FILES=(
    "config.json"
    "model.bin"
    "preprocessor_config.json"
    "tokenizer.json"
    "vocabulary.json"
)
URL_TTS_RU="https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx"
URL_TTS_RU_JSON="https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json"
URL_TTS_EN="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
URL_TTS_EN_JSON="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"

URL_EMBED_ROOT="https://huggingface.co/BAAI/bge-m3/resolve/main"
EMBED_FILES=(
    "config.json"
    "colbert_linear.pt"
    "sentencepiece.bpe.model"
    "sparse_linear.pt"
    "tokenizer.json"
    "tokenizer_config.json"
    "pytorch_model.bin"
)

URL_RERANK_ROOT="https://huggingface.co/BAAI/bge-reranker-v2-m3/resolve/main"
RERANK_FILES=(
    "config.json"
    "sentencepiece.bpe.model"
    "tokenizer.json"
    "tokenizer_config.json"
    "pytorch_model.bin"
)

# The official Qwen GGUF is split into 2 shards; llama.cpp loads the whole
# model when pointed at the -00001-of-00002 shard.
URL_LLM_ROOT="https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main"
LLM_FILES=(
    "qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf"
    "qwen2.5-7b-instruct-q5_k_m-00002-of-00002.gguf"
)

WAKE_URL="https://github.com/dscripka/openWakeWord/releases/download/v0.1.0/embedding_model.tflite"

# --- Helpers ------------------------------------------------------------------

need_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "must run as root (use sudo)" >&2
        exit 1
    fi
}

ensure_dir() {
    install -d -o root -g root -m 0755 "$1"
}

download() {
    local url="$1" dest="$2"
    if [[ -s "${dest}" ]]; then
        echo "  keep ${dest}"
        return
    fi
    echo "  fetch ${url}"
    ensure_dir "$(dirname "${dest}")"
    curl -fSL --retry 3 --retry-delay 4 -o "${dest}.part" "${url}"
    mv "${dest}.part" "${dest}"
}

fetch_asr() {
    local dir="${MODELS_DIR}/faster-whisper-large-v3-turbo"
    for f in "${ASR_FILES[@]}"; do
        download "${URL_ASR_TAR}/${f}" "${dir}/${f}"
    done
}

fetch_tts() {
    local dir="${MODELS_DIR}/piper"
    download "${URL_TTS_RU}"      "${dir}/ru_RU-irina-medium.onnx"
    download "${URL_TTS_RU_JSON}" "${dir}/ru_RU-irina-medium.onnx.json"
    download "${URL_TTS_EN}"      "${dir}/en_US-lessac-medium.onnx"
    download "${URL_TTS_EN_JSON}" "${dir}/en_US-lessac-medium.onnx.json"
}

fetch_wake() {
    local dir="${MODELS_DIR}/openwakeword"
    download "${WAKE_URL}" "${dir}/embedding_model.tflite"
    echo "  NOTE: install your own wake-word .onnx into ${dir}/ before enabling"
    echo "  wake-word gating in voice.yaml.  See openwakeword docs."
}

fetch_embedder() {
    local dir="${MODELS_DIR}/bge-m3"
    for f in "${EMBED_FILES[@]}"; do
        download "${URL_EMBED_ROOT}/${f}" "${dir}/${f}"
    done
}

fetch_reranker() {
    local dir="${MODELS_DIR}/bge-reranker-v2-m3"
    for f in "${RERANK_FILES[@]}"; do
        download "${URL_RERANK_ROOT}/${f}" "${dir}/${f}"
    done
}

fetch_llm() {
    local dir="${MODELS_DIR}/llm"
    for f in "${LLM_FILES[@]}"; do
        download "${URL_LLM_ROOT}/${f}" "${dir}/${f}"
    done
}

main() {
    need_root
    ensure_dir "${MODELS_DIR}"

    for kind in ${MODELS}; do
        echo "== ${kind} =="
        case "${kind}" in
            asr)      fetch_asr ;;
            tts)      fetch_tts ;;
            wake)     fetch_wake ;;
            embedder) fetch_embedder ;;
            reranker) fetch_reranker ;;
            llm)      fetch_llm ;;
            *)
                echo "unknown model kind: ${kind}" >&2
                exit 1
                ;;
        esac
    done

    echo
    echo "Done. Files landed under ${MODELS_DIR}."
    echo "Enable the pipelines:"
    echo "  cd /opt/humanoid-robot"
    echo "  docker compose --profile voice --profile rag up -d"
}

main "$@"
