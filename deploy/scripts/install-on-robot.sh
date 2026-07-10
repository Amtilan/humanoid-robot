#!/usr/bin/env bash
#
# One-liner install for the robot side. Downloads the pull-only compose
# file + nats.conf into /opt/humanoid-robot, then pulls the images.
#
#   curl -sSL https://raw.githubusercontent.com/Amtilan/humanoid-robot/main/deploy/scripts/install-on-robot.sh | sudo bash
#
# Or with a pinned tag:
#
#   curl -sSL … | sudo IMAGE_TAG=v1.0.0 bash
#
# No `git clone`, no build-toolchain, no dev deps on the robot.

set -euo pipefail

RELEASE_REF="${RELEASE_REF:-main}"
IMAGE_TAG="${IMAGE_TAG:-$RELEASE_REF}"
INSTALL_DIR="${INSTALL_DIR:-/opt/humanoid-robot}"
CONFIG_DIR="${CONFIG_DIR:-/etc/humanoid-robot}"

REPO="Amtilan/humanoid-robot"
RAW_BASE="https://raw.githubusercontent.com/${REPO}/${RELEASE_REF}"

need_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "must run as root (use sudo)" >&2
        exit 1
    fi
}

need_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "docker not found. Install Docker Engine, then re-run this script." >&2
        exit 1
    fi
    if ! docker compose version >/dev/null 2>&1; then
        echo "'docker compose' plugin not found. Install docker-compose-plugin." >&2
        exit 1
    fi
}

fetch() {
    local rel="$1" dest="$2"
    curl -fsSL "${RAW_BASE}/${rel}" -o "${dest}"
    echo "  fetched ${rel} → ${dest}"
}

main() {
    need_root
    need_docker

    install -d -m 0755 "${INSTALL_DIR}"
    install -d -m 0755 "${CONFIG_DIR}"

    fetch deploy/docker-compose.pull.yaml "${INSTALL_DIR}/docker-compose.yaml"
    fetch deploy/nats.conf                "${INSTALL_DIR}/nats.conf"

    for env in cortex-core cortex-robot-adapter cortex-voice cortex-rag; do
        local src="deploy/config/${env}.env.example"
        local dst="${CONFIG_DIR}/${env}.env"
        if [[ -e "${dst}" ]]; then
            echo "  keeping existing ${dst}"
        else
            fetch "${src}" "${dst}"
            chmod 0640 "${dst}"
        fi
    done

    cat >"${INSTALL_DIR}/.env" <<EOF
IMAGE_REGISTRY=ghcr.io
IMAGE_OWNER=amtilan
IMAGE_TAG=${IMAGE_TAG}
HR_ROBOT_ADAPTER__ADAPTER_NAME=mock
EOF
    chmod 0640 "${INSTALL_DIR}/.env"

    echo
    echo "Pulling images (IMAGE_TAG=${IMAGE_TAG})…"
    ( cd "${INSTALL_DIR}" && docker compose pull )

    cat <<EOF

Install complete. To start the platform:

  cd ${INSTALL_DIR}
  docker compose up -d

Dashboard: http://127.0.0.1:8081/
API:       http://127.0.0.1:8080/

Config files:
  ${CONFIG_DIR}/cortex-core.env
  ${CONFIG_DIR}/cortex-robot-adapter.env
  ${CONFIG_DIR}/cortex-voice.env    (once you enable voice)
  ${CONFIG_DIR}/cortex-rag.env      (once you enable RAG)

Switch adapter (e.g. unitree_g1_edu):
  edit ${INSTALL_DIR}/.env and set HR_ROBOT_ADAPTER__ADAPTER_NAME
  docker compose up -d --force-recreate robot-adapter

Upgrade:
  edit ${INSTALL_DIR}/.env and set IMAGE_TAG=vX.Y.Z
  docker compose pull && docker compose up -d
EOF
}

main "$@"
