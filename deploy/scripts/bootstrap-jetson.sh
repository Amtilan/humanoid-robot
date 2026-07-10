#!/usr/bin/env bash
#
# One-shot bootstrap for a fresh Jetson Orin NX:
#   sudo bash deploy/scripts/bootstrap-jetson.sh
#
# Idempotent: safe to re-run. Creates the humanoid-robot user, installs
# systemd units + reference env files, sets up state dirs, but does NOT
# start the services (you review /etc/humanoid-robot/*.env first).

set -euo pipefail

SRV_USER="humanoid-robot"
SRV_HOME="/opt/humanoid-robot"
CONFIG_DIR="/etc/humanoid-robot"
STATE_DIR="/var/lib/humanoid-robot"
LOG_DIR="/var/log/humanoid-robot"

require_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "must run as root (use sudo)" >&2
        exit 1
    fi
}

ensure_user() {
    if id "$SRV_USER" >/dev/null 2>&1; then
        return
    fi
    useradd --system --home-dir "$SRV_HOME" --shell /usr/sbin/nologin "$SRV_USER"
}

ensure_dirs() {
    install -d -o "$SRV_USER" -g "$SRV_USER" -m 0750 "$SRV_HOME"
    install -d -o "$SRV_USER" -g "$SRV_USER" -m 0750 "$STATE_DIR" "$STATE_DIR/models" "$STATE_DIR/rag"
    install -d -o "$SRV_USER" -g "$SRV_USER" -m 0750 "$LOG_DIR"
    install -d -m 0755 "$CONFIG_DIR"
}

install_env_examples() {
    # .env files (cortex-core, cortex-robot-adapter) — copy .example to
    # non-.example so admins can uncomment lines.
    for src in deploy/config/*.env.example; do
        [[ -e "$src" ]] || continue
        local name
        name="$(basename "$src" .example)"
        local dest="$CONFIG_DIR/$name"
        if [[ -e "$dest" ]]; then
            echo "keeping existing $dest"
        else
            install -m 0640 -o root -g "$SRV_USER" "$src" "$dest"
            echo "installed $dest (edit before enabling the unit)"
        fi
    done

    # YAML configs (cortex-voice, cortex-rag, cortex-core optional) —
    # copy verbatim if not already present.
    for src in deploy/config/voice.yaml deploy/config/rag.yaml deploy/config/base.yaml deploy/config/ingest.yaml; do
        [[ -e "$src" ]] || continue
        local dest="$CONFIG_DIR/$(basename "$src")"
        if [[ -e "$dest" ]]; then
            echo "keeping existing $dest"
        else
            install -m 0640 -o root -g "$SRV_USER" "$src" "$dest"
            echo "installed $dest (edit before enabling the unit)"
        fi
    done
}

install_units() {
    install -m 0644 deploy/systemd/*.service deploy/systemd/*.target /etc/systemd/system/
    if compgen -G "deploy/systemd/*.timer" > /dev/null; then
        install -m 0644 deploy/systemd/*.timer /etc/systemd/system/
    fi
    systemctl daemon-reload
}

install_nats() {
    if command -v nats-server >/dev/null 2>&1; then
        return
    fi
    echo "NOTE: nats-server not installed — see"
    echo "  https://docs.nats.io/running-a-nats-service/introduction/installation"
    echo "and enable it before starting humanoid-robot.target."
}

check_uv() {
    if [[ ! -x "$SRV_HOME/.venv/bin/uv" && ! -x "$(command -v uv 2>/dev/null || true)" ]]; then
        echo "NOTE: uv not found; install into $SRV_HOME/.venv or system PATH."
        echo "  See https://docs.astral.sh/uv/ then run 'uv sync --all-packages' from $SRV_HOME."
    fi
}

main() {
    require_root
    ensure_user
    ensure_dirs
    install_env_examples
    install_units
    install_nats
    check_uv
    cat <<'EOF'

Bootstrap complete. Next:

  1. Clone the release into /opt/humanoid-robot (as humanoid-robot user),
     then run:  cd /opt/humanoid-robot && uv sync --all-packages --no-dev
  2. Edit /etc/humanoid-robot/*.env  (mostly commented-out example values).
  3. Enable the platform:
       sudo systemctl enable --now humanoid-robot.target
  4. Follow logs:
       journalctl -u cortex-core -u cortex-robot-adapter -u cortex-voice -u cortex-rag -f

EOF
}

main "$@"
