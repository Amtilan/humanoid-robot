#!/usr/bin/env bash
#
# Prints "yes" and exits 0 on a Jetson (any JetPack release), "no"
# and exits 1 elsewhere. Used by install-on-robot.sh to decide
# whether to enable the docker-compose.jetson.yaml overlay.
#
# Detection is a two-track OR — either identifier is enough:
#
#   1. /etc/nv_tegra_release — canonical for JetPack. Present on
#      every Jetson since Nano / TX2, absent everywhere else.
#   2. /proc/device-tree/compatible — mentions "nvidia,tegra*" on
#      Jetson. Survives even if a custom rootfs skipped the
#      nv_tegra_release file.

set -eu

if [[ -f /etc/nv_tegra_release ]]; then
    echo yes
    exit 0
fi

if [[ -f /proc/device-tree/compatible ]] \
        && grep -aq 'nvidia,tegra' /proc/device-tree/compatible; then
    echo yes
    exit 0
fi

echo no
exit 1
