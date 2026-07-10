#!/usr/bin/env bash
#
# Build the Unitree G1 adapter image natively on the robot (arm64),
# avoiding QEMU emulation of the CycloneDDS C build.
#
# The build FROM's the already-pulled humanoid-robot-base, then fetches
# CycloneDDS + unitree_sdk2_python from GitHub/PyPI — so it needs egress.
# On the G1 the eth10 DDS route shadows the internet route; pass
# --fix-egress to add a reversible wlan0 default for the build, or fix
# routing yourself first.
#
#   sudo bash build-unitree-adapter.sh --fix-egress
#
# Result: a local image tag `humanoid-robot-adapter-unitree:local` that
# docker-compose.unitree.yaml can reference (set IMAGE_TAG=local and
# IMAGE_REGISTRY/IMAGE_OWNER to match, or retag/push to GHCR).

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/humanoid-robot}"
DOCKERFILE="${DOCKERFILE:-${INSTALL_DIR}/adapter-unitree.Dockerfile}"
BASE_IMAGE="${BASE_IMAGE:-ghcr.io/amtilan/humanoid-robot-base:main}"
TAG="${TAG:-humanoid-robot-adapter-unitree:local}"

FIX_EGRESS=0
[[ "${1:-}" == "--fix-egress" ]] && FIX_EGRESS=1

_EGRESS_ROUTE=""
_online() {
    resolvectl flush-caches >/dev/null 2>&1 || true
    local code
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 \
        https://github.com 2>/dev/null || echo 000)
    [[ "${code}" != "000" ]]
}
revert_egress() {
    [[ -n "${_EGRESS_ROUTE}" ]] || return 0
    # shellcheck disable=SC2086
    ip route del ${_EGRESS_ROUTE} 2>/dev/null && echo "reverted temporary egress route."
    _EGRESS_ROUTE=""
}
fix_egress() {
    local best_gw="" best_dev="" top_dev
    while read -r gw dev; do
        [[ -n "${gw}" && -n "${dev}" ]] || continue
        if timeout 6 ping -c1 -W2 -I "${dev}" 8.8.8.8 >/dev/null 2>&1; then  # pragma: allowlist secret
            best_gw="${gw}"; best_dev="${dev}"; break
        fi
    done < <(ip -o route show default | sed -n 's/.*via \([0-9.]*\) dev \([^ ]*\).*/\1 \2/p')
    top_dev=$(ip -o route show default | sed -n '1s/.*dev \([^ ]*\).*/\1/p')
    [[ -n "${best_dev}" ]] || { _online && return 0; echo "no online iface" >&2; return 1; }
    if [[ "${best_dev}" == "${top_dev}" ]] && _online; then return 0; fi
    echo "forcing metric-50 default via ${best_dev}…"
    ip route add default via "${best_gw}" dev "${best_dev}" metric 50 2>/dev/null || true
    _EGRESS_ROUTE="default via ${best_gw} dev ${best_dev} metric 50"
    local i
    for i in 1 2 3 4 5; do _online && return 0; sleep 2; done
    revert_egress; return 1
}

if [[ "${FIX_EGRESS}" == "1" ]]; then
    trap revert_egress EXIT
    fix_egress || { echo "egress fix failed" >&2; exit 1; }
fi

echo "building ${TAG} from ${DOCKERFILE} (BASE_IMAGE=${BASE_IMAGE})…"
docker build \
    --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
    -f "${DOCKERFILE}" \
    -t "${TAG}" \
    "${INSTALL_DIR}"

if [[ "${FIX_EGRESS}" == "1" ]]; then
    revert_egress
    trap - EXIT
fi

echo "built ${TAG}"
