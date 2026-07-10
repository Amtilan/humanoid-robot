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

# --skip-verify (or HR_INSTALL_SKIP_VERIFY=1) bypasses the fail-closed
# cosign check. Use ONLY for dev builds that were never pushed to GHCR.
SKIP_VERIFY="${HR_INSTALL_SKIP_VERIFY:-0}"
for arg in "$@"; do
    case "${arg}" in
        --skip-verify) SKIP_VERIFY=1 ;;
        *) echo "unknown argument: ${arg}" >&2; exit 2 ;;
    esac
done

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
    install -d -m 0755 /var/lib/humanoid-robot/models

    fetch deploy/docker-compose.pull.yaml "${INSTALL_DIR}/docker-compose.yaml"
    fetch deploy/docker-compose.jetson.yaml "${INSTALL_DIR}/docker-compose.jetson.yaml"
    fetch deploy/scripts/detect-jetson.sh "${INSTALL_DIR}/detect-jetson.sh"
    chmod +x "${INSTALL_DIR}/detect-jetson.sh"
    fetch deploy/nats.conf                "${INSTALL_DIR}/nats.conf"
    fetch deploy/scripts/fetch-models.sh  "${INSTALL_DIR}/fetch-models.sh"
    chmod +x "${INSTALL_DIR}/fetch-models.sh"
    fetch deploy/scripts/backup.sh        "${INSTALL_DIR}/backup.sh"
    chmod +x "${INSTALL_DIR}/backup.sh"
    fetch deploy/scripts/restore.sh       "${INSTALL_DIR}/restore.sh"
    chmod +x "${INSTALL_DIR}/restore.sh"
    fetch deploy/scripts/verify-install.sh "${INSTALL_DIR}/verify-install.sh"
    chmod +x "${INSTALL_DIR}/verify-install.sh"
    fetch deploy/scripts/verify-images.sh "${INSTALL_DIR}/verify-images.sh"
    chmod +x "${INSTALL_DIR}/verify-images.sh"
    install -d -m 0750 /var/backups/humanoid-robot
    for cfg in voice rag; do
        local dst="${CONFIG_DIR}/${cfg}.yaml"
        if [[ -e "${dst}" ]]; then
            echo "  keeping existing ${dst}"
        else
            fetch "deploy/config/${cfg}.yaml" "${dst}"
        fi
    done

    # Observability provisioning — Prometheus scrape + Grafana defaults
    # get bind-mounted from /etc/humanoid-robot/observability into the
    # metrics containers, so ship them alongside the service configs.
    install -d -m 0755 "${CONFIG_DIR}/observability/grafana/dashboards"
    install -d -m 0755 "${CONFIG_DIR}/observability/grafana/datasources"
    install -d -m 0755 "${CONFIG_DIR}/observability/rules"
    fetch deploy/observability/prometheus.yml \
        "${CONFIG_DIR}/observability/prometheus.yml"
    fetch deploy/observability/alertmanager.yml \
        "${CONFIG_DIR}/observability/alertmanager.yml"
    fetch deploy/observability/rules/humanoid-robot.yml \
        "${CONFIG_DIR}/observability/rules/humanoid-robot.yml"
    fetch deploy/observability/grafana/datasources/prometheus.yaml \
        "${CONFIG_DIR}/observability/grafana/datasources/prometheus.yaml"
    fetch deploy/observability/grafana/dashboards/provider.yaml \
        "${CONFIG_DIR}/observability/grafana/dashboards/provider.yaml"
    fetch deploy/observability/grafana/dashboards/platform.json \
        "${CONFIG_DIR}/observability/grafana/dashboards/platform.json"

    for env in cortex-core cortex-robot-adapter cortex-voice cortex-rag alertmanager; do
        local src="deploy/config/${env}.env.example"
        local dst="${CONFIG_DIR}/${env}.env"
        if [[ -e "${dst}" ]]; then
            echo "  keeping existing ${dst}"
        else
            fetch "${src}" "${dst}"
            chmod 0640 "${dst}"
        fi
    done

    local compose_files="docker-compose.yaml"
    if bash "${INSTALL_DIR}/detect-jetson.sh" > /dev/null 2>&1; then
        compose_files="docker-compose.yaml:docker-compose.jetson.yaml"
        echo
        echo "Detected Jetson — enabling GPU passthrough overlay in COMPOSE_FILE."
    fi

    cat >"${INSTALL_DIR}/.env" <<EOF
IMAGE_REGISTRY=ghcr.io
IMAGE_OWNER=amtilan
IMAGE_TAG=${IMAGE_TAG}
HR_ROBOT_ADAPTER__ADAPTER_NAME=mock
COMPOSE_FILE=${compose_files}
EOF
    chmod 0640 "${INSTALL_DIR}/.env"

    if [[ "${SKIP_VERIFY}" == "1" ]]; then
        echo
        echo "WARNING: --skip-verify passed — image signatures are NOT being checked." >&2
        echo "Only appropriate for local dev builds that were never published to GHCR." >&2
    else
        echo
        # Fail-closed. If verify-images.sh exits non-zero we abort BEFORE
        # `docker compose pull` so unsigned/tampered images never land in
        # the local image store.
        local rc=0
        IMAGE_TAG="${IMAGE_TAG}" IMAGE_REGISTRY=ghcr.io IMAGE_OWNER=amtilan \
            bash "${INSTALL_DIR}/verify-images.sh" || rc=$?
        case "${rc}" in
            0) ;;
            3)
                echo "cosign is required for a hardened install." >&2
                echo "Install it (URLs above) and re-run this script, or pass" >&2
                echo "--skip-verify if you accept the supply-chain risk." >&2
                exit 3
                ;;
            *)
                echo "Refusing to pull unverified images. Aborting." >&2
                exit "${rc}"
                ;;
        esac
    fi

    echo
    echo "Pulling images (IMAGE_TAG=${IMAGE_TAG})…"
    ( cd "${INSTALL_DIR}" && docker compose pull )

    cat <<EOF

Install complete. To start the platform:

  cd ${INSTALL_DIR}
  docker compose up -d
  bash ${INSTALL_DIR}/verify-install.sh   # smoke check the running stack

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
  IMAGE_TAG=vX.Y.Z bash ${INSTALL_DIR}/verify-images.sh
  docker compose pull && docker compose up -d

Re-verify signatures at any time:
  bash ${INSTALL_DIR}/verify-images.sh

Enable voice + RAG (~9.5 GB of models pulled from Hugging Face):
  sudo bash ${INSTALL_DIR}/fetch-models.sh
  docker compose --profile voice --profile rag up -d

Enable observability (Prometheus + Grafana on 127.0.0.1:{9090,3000}):
  docker compose --profile metrics up -d

Route alerts to Slack / Discord / ntfy / webhook:
  sudo \$EDITOR ${CONFIG_DIR}/alertmanager.env   # uncomment a block, set URL
  docker compose --profile metrics restart alertmanager

Nightly backup (audit DB + Qdrant knowledge collection):
  sudo cp deploy/systemd/humanoid-robot-backup.{service,timer} /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now humanoid-robot-backup.timer
  # Manual one-shot: sudo ${INSTALL_DIR}/backup.sh
  # Restore:         sudo ${INSTALL_DIR}/restore.sh /var/backups/humanoid-robot/<tarball>
EOF
}

main "$@"
