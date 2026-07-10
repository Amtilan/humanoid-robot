#!/usr/bin/env bash
#
# Robot-side smoke check. Runs the same probes the CI compose-smoke
# workflow does — cortex-core readiness, mock/robot manifest, safety
# gate, diagnostics ticker, dashboard — but locally on the Jetson so
# the operator gets a "yes it's alive" signal after `docker compose up`.
#
# Usage:
#   bash /opt/humanoid-robot/verify-install.sh                     # base stack
#   bash /opt/humanoid-robot/verify-install.sh --with voice        # + voice
#   bash /opt/humanoid-robot/verify-install.sh --with voice --with rag --with metrics
#
# Exit codes:
#   0 all checks passed
#   1 at least one required check failed (see summary table)

set -u

CORE_URL="${CORE_URL:-http://127.0.0.1:8080}"
DASHBOARD_URL="${DASHBOARD_URL:-http://127.0.0.1:8081}"
QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
PROM_URL="${PROM_URL:-http://127.0.0.1:9090}"
GRAFANA_URL="${GRAFANA_URL:-http://127.0.0.1:3000}"
ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://127.0.0.1:9093}"

CORE_READY_TIMEOUT_S="${CORE_READY_TIMEOUT_S:-60}"
MANIFEST_TIMEOUT_S="${MANIFEST_TIMEOUT_S:-30}"
DIAGNOSTICS_TIMEOUT_S="${DIAGNOSTICS_TIMEOUT_S:-20}"

CHECKS_VOICE=0
CHECKS_RAG=0
CHECKS_METRICS=0

for arg in "$@"; do
    case "${arg}" in
        --with) : ;;
        voice)   CHECKS_VOICE=1 ;;
        rag)     CHECKS_RAG=1 ;;
        metrics) CHECKS_METRICS=1 ;;
        --with=voice|--with=rag|--with=metrics)
            case "${arg#--with=}" in
                voice)   CHECKS_VOICE=1 ;;
                rag)     CHECKS_RAG=1 ;;
                metrics) CHECKS_METRICS=1 ;;
            esac
            ;;
        --help|-h)
            grep -E '^# ' "$0" | sed 's/^# //'
            exit 0
            ;;
        *)
            echo "unknown arg: ${arg} (see --help)" >&2
            exit 2
            ;;
    esac
done

# --- report table --------------------------------------------------------

declare -A RESULT
declare -A DETAIL
ORDER=()

record() {
    local name="$1" ok="$2" detail="${3:-}"
    RESULT[${name}]="${ok}"
    DETAIL[${name}]="${detail}"
    ORDER+=("${name}")
}

summary() {
    echo
    echo "== verify summary =="
    printf "%-32s %-8s %s\n" "check" "status" "detail"
    printf -- "-%.0s" {1..80}
    echo
    local failed=0
    for name in "${ORDER[@]}"; do
        local status="${RESULT[$name]}"
        local mark
        case "${status}" in
            ok)   mark="PASS" ;;
            fail) mark="FAIL"; failed=1 ;;
            skip) mark="skip" ;;
            *)    mark="???" ;;
        esac
        printf "%-32s %-8s %s\n" "${name}" "${mark}" "${DETAIL[$name]}"
    done
    echo
    return "${failed}"
}

# --- probes --------------------------------------------------------------

probe_http_ok() {
    local name="$1" url="$2"
    local code
    code=$(curl -sf -o /dev/null -w "%{http_code}" "${url}" 2>/dev/null) || code="000"
    if [[ "${code}" == "200" ]]; then
        record "${name}" ok "http=200 ${url}"
    else
        record "${name}" fail "http=${code} ${url}"
    fi
}

wait_core_ready() {
    for _ in $(seq 1 "${CORE_READY_TIMEOUT_S}"); do
        local code
        code=$(curl -sf -o /dev/null -w "%{http_code}" \
            "${CORE_URL}/api/v1/system/health/ready" 2>/dev/null) || code="000"
        if [[ "${code}" == "200" ]]; then
            record cortex-core.ready ok "http=200 after wait"
            return 0
        fi
        sleep 1
    done
    record cortex-core.ready fail "still down after ${CORE_READY_TIMEOUT_S}s"
    return 1
}

check_manifest() {
    local seen=0
    for _ in $(seq 1 "${MANIFEST_TIMEOUT_S}"); do
        local body
        body=$(curl -sf "${CORE_URL}/api/v1/robot/manifests" 2>/dev/null || true)
        if [[ -n "${body}" && "${body}" != "[]" ]]; then
            local name
            name=$(echo "${body}" \
                | python3 -c 'import json,sys;data=json.load(sys.stdin);print(data[0]["adapter_name"] if data else "")')
            record robot-adapter.manifest ok "adapter=${name}"
            seen=1
            break
        fi
        sleep 1
    done
    if [[ "${seen}" -eq 0 ]]; then
        record robot-adapter.manifest fail \
            "no RobotAdapterReady in ${MANIFEST_TIMEOUT_S}s — check adapter logs"
    fi
}

check_diagnostics() {
    for _ in $(seq 1 "${DIAGNOSTICS_TIMEOUT_S}"); do
        local body
        body=$(curl -sf "${CORE_URL}/api/v1/diagnostics/host" 2>/dev/null || true)
        if echo "${body}" | grep -q '"cpu"'; then
            record diagnostics.ticker ok "cpu block seen"
            return 0
        fi
        sleep 1
    done
    record diagnostics.ticker fail \
        "no diagnostics.host response in ${DIAGNOSTICS_TIMEOUT_S}s"
}

check_safety() {
    local body
    body=$(curl -sf "${CORE_URL}/api/v1/safety/status" 2>/dev/null || true)
    if echo "${body}" | grep -q '"pending_command_count"'; then
        local engaged
        engaged=$(echo "${body}" \
            | python3 -c 'import json,sys;print(json.load(sys.stdin)["estop_engaged"])' 2>/dev/null || echo "?")
        record safety.gate ok "estop_engaged=${engaged}"
    else
        record safety.gate fail "unexpected /safety/status body"
    fi
}

check_dashboard_spa() {
    local body
    body=$(curl -sf "${DASHBOARD_URL}/" 2>/dev/null || true)
    if echo "${body}" | grep -q '<div id="root"></div>'; then
        record dashboard.spa ok "React mount div served"
    else
        record dashboard.spa fail "SPA index missing / nginx not routing"
    fi
}

# --- optional profile probes --------------------------------------------

check_qdrant() {
    if (( CHECKS_RAG )); then
        probe_http_ok qdrant.up "${QDRANT_URL}/collections"
    else
        record qdrant.up skip "not requested (--with rag)"
    fi
}

check_prometheus() {
    if (( CHECKS_METRICS )); then
        probe_http_ok prometheus.up "${PROM_URL}/-/ready"
        # Rule file loaded and parsed?
        local rules
        rules=$(curl -sf "${PROM_URL}/api/v1/rules" 2>/dev/null || true)
        if echo "${rules}" | grep -q '"CortexCoreDown"'; then
            record prometheus.rules ok "CortexCoreDown rule active"
        else
            record prometheus.rules fail "alert rules never loaded"
        fi
    else
        record prometheus.up skip "not requested (--with metrics)"
        record prometheus.rules skip "not requested (--with metrics)"
    fi
}

check_grafana() {
    if (( CHECKS_METRICS )); then
        probe_http_ok grafana.up "${GRAFANA_URL}/api/health"
    else
        record grafana.up skip "not requested (--with metrics)"
    fi
}

check_alertmanager() {
    if (( CHECKS_METRICS )); then
        probe_http_ok alertmanager.up "${ALERTMANAGER_URL}/-/ready"
    else
        record alertmanager.up skip "not requested (--with metrics)"
    fi
}

check_voice_process() {
    if (( CHECKS_VOICE )); then
        if docker ps --format '{{.Names}}' | grep -q '^deploy-voice-1$\|^humanoid-robot-voice-1$'; then
            record voice.container ok "container running"
            probe_jetson_runtime voice
        else
            record voice.container fail "voice container not up (docker compose --profile voice)"
        fi
    else
        record voice.container skip "not requested (--with voice)"
    fi
}

check_rag_process() {
    if (( CHECKS_RAG )); then
        if docker ps --format '{{.Names}}' | grep -q '^deploy-rag-1$\|^humanoid-robot-rag-1$'; then
            record rag.container ok "container running"
            probe_jetson_runtime rag
        else
            record rag.container fail "rag container not up (docker compose --profile rag)"
        fi
    else
        record rag.container skip "not requested (--with rag)"
    fi
}

# Verifies the Jetson overlay landed on the container's runtime when
# we're actually running on Jetson hardware. Skipped otherwise so
# CI on plain x86 doesn't fail.
probe_jetson_runtime() {
    local svc="$1"
    local check_name="${svc}.gpu"
    if ! command -v docker >/dev/null 2>&1; then
        record "${check_name}" skip "docker CLI missing"
        return
    fi
    if ! [[ -f /etc/nv_tegra_release || -f /proc/device-tree/compatible ]]; then
        record "${check_name}" skip "not on Jetson"
        return
    fi
    local cid
    cid=$(docker ps --filter "name=${svc}" --format '{{.ID}}' | head -n1 || true)
    if [[ -z "${cid}" ]]; then
        record "${check_name}" skip "container id unknown"
        return
    fi
    local runtime
    runtime=$(docker inspect -f '{{.HostConfig.Runtime}}' "${cid}" 2>/dev/null || true)
    if [[ "${runtime}" == "nvidia" ]]; then
        record "${check_name}" ok "runtime=nvidia"
    else
        record "${check_name}" fail "runtime=${runtime:-<unset>} (overlay missing?)"
    fi
}

# --- run -----------------------------------------------------------------

echo "verifying humanoid-robot stack at ${CORE_URL} …"

# NATS itself is validated by cortex-core's ability to bring up its
# bus subscribers — the compose healthcheck for nats is the source of
# truth. We deliberately don't probe :8222 from the host because the
# monitoring port isn't exposed by the default compose files.

check_nats_container() {
    if docker ps --format '{{.Names}}: {{.Status}}' | grep -E '(deploy|humanoid-robot)-nats-1' | grep -q '(healthy)'; then
        record nats.container ok "compose healthcheck passed"
    else
        record nats.container fail "nats container not marked healthy"
    fi
}

check_nats_container
wait_core_ready || true
if [[ "${RESULT[cortex-core.ready]:-}" == "ok" ]]; then
    check_manifest
    check_diagnostics
    check_safety
    check_dashboard_spa
else
    for name in robot-adapter.manifest diagnostics.ticker safety.gate dashboard.spa; do
        record "${name}" skip "core never became ready"
    done
fi
check_qdrant
check_prometheus
check_grafana
check_alertmanager
check_voice_process
check_rag_process

summary
exit $?
