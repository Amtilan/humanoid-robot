#!/usr/bin/env bash
#
# Turn the loopback-only dashboard/API into a static LAN endpoint.
#
# Enables the bearer token (the API can dispatch robot commands, so it
# must NOT be open once it leaves loopback) and rebinds core + dashboard
# to all interfaces via HR_BIND_ADDR. Then recreates just those two
# containers — the robot-adapter is left untouched.
#
# After this, everything is reachable through ONE url:
#   http://<robot-ip>:8081   (dashboard; nginx proxies /api + the WS
#                             event stream to core, so the UI, the REST
#                             API and live events all go through it)
#   http://<robot-ip>:8080   (core API directly, same token)
#
#   sudo bash expose.sh                 # generate a fresh token
#   sudo HR_AUTH__TOKEN=... bash expose.sh   # reuse a known token
#
# Revert to loopback-only + no auth:
#   sudo bash expose.sh --off

set -euo pipefail
DIR="${INSTALL_DIR:-/opt/humanoid-robot}"
ENVF="${DIR}/.env"
touch "${ENVF}"

_set() {  # _set KEY VALUE  (idempotent upsert in .env)
    local k="$1" v="$2"
    if grep -q "^${k}=" "${ENVF}"; then
        sed -i "s|^${k}=.*|${k}=${v}|" "${ENVF}"
    else
        echo "${k}=${v}" >> "${ENVF}"
    fi
}

if [[ "${1:-}" == "--off" ]]; then
    _set HR_BIND_ADDR 127.0.0.1
    _set HR_AUTH__TOKEN ""
    ( cd "${DIR}" && docker compose up -d core dashboard )
    echo "reverted to loopback-only, auth disabled."
    exit 0
fi

# 192 bits of entropy, url/-shell-safe.
TOKEN="${HR_AUTH__TOKEN:-$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | cut -c1-32)}"

_set HR_BIND_ADDR 0.0.0.0   # pragma: allowlist secret
_set HR_AUTH__TOKEN "${TOKEN}"

( cd "${DIR}" && docker compose up -d core dashboard )

IP="$(ip -4 addr show wlan0 2>/dev/null | sed -n 's/.*inet \([0-9.]*\).*/\1/p' | head -1)"
IP="${IP:-<robot-ip>}"
cat <<OUT

======================================================================
 STATIC ROBOT ENDPOINT (LAN)
======================================================================
 Dashboard : http://${IP}:8081
 API       : http://${IP}:8080
 Token     : ${TOKEN}

 Open the dashboard, it will prompt for the token (stored in your
 browser). For direct API calls:
   curl -H "Authorization: Bearer ${TOKEN}" http://${IP}:8080/api/v1/robot/manifests

 NOTE: ${IP} is a DHCP address. For a truly stable link, add a DHCP
 reservation for the robot on your router, or put it on Tailscale.
======================================================================
OUT
