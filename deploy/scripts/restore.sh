#!/usr/bin/env bash
#
# Restore a humanoid-robot backup tarball (as produced by backup.sh).
# Always stops cortex-core + qdrant first so the SQLite / Qdrant
# writers don't race against the restore, restores the artefacts,
# then leaves the stack down — the operator restarts intentionally
# once they've verified the restore looks sane.
#
# Usage:
#   sudo bash deploy/scripts/restore.sh /var/backups/humanoid-robot/humanoid-robot-...tar.gz

set -euo pipefail

STATE_DIR="${STATE_DIR:-/var/lib/humanoid-robot}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/humanoid-robot}"
QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
QDRANT_COLLECTION="${QDRANT_COLLECTION:-knowledge}"

if [[ $# -ne 1 ]]; then
    echo "usage: $0 <backup.tar.gz>" >&2
    exit 1
fi

TARBALL="$1"

need_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "must run as root (use sudo)" >&2
        exit 1
    fi
}

verify_tarball() {
    if [[ ! -f "${TARBALL}" ]]; then
        echo "no such file: ${TARBALL}" >&2
        exit 1
    fi
    if ! tar -tzf "${TARBALL}" > /dev/null; then
        echo "tarball is not a valid gzip archive" >&2
        exit 1
    fi
}

stop_stack() {
    echo "stopping cortex-core + qdrant (if running)…"
    ( cd "${COMPOSE_DIR}" && docker compose stop core qdrant 2>/dev/null || true )
}

restore_audit_db() {
    local staging="$1"
    local src="${staging}/safety_audit.sqlite"
    if [[ ! -f "${src}" ]]; then
        echo "  no audit DB in tarball, skipping"
        return
    fi
    local dst="${STATE_DIR}/safety_audit.sqlite"
    if [[ -f "${dst}" ]]; then
        cp "${dst}" "${dst}.pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"
    fi
    install -m 0640 -o root -g root "${src}" "${dst}"
    echo "  audit DB → ${dst}"
}

restore_qdrant_snapshot() {
    local staging="$1"
    local snapshot
    snapshot=$(ls "${staging}"/*.snapshot 2>/dev/null | head -n1 || true)
    if [[ -z "${snapshot}" ]]; then
        echo "  no qdrant snapshot in tarball, skipping"
        return
    fi
    echo "  restoring qdrant snapshot $(basename "${snapshot}")"
    ( cd "${COMPOSE_DIR}" && docker compose --profile rag up -d qdrant )
    # Wait for Qdrant to be reachable so the upload doesn't race the boot.
    for i in $(seq 1 30); do
        if curl -sf "${QDRANT_URL}/collections" > /dev/null; then
            break
        fi
        sleep 1
    done
    curl -sf -X POST -F "snapshot=@${snapshot}" \
        "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/snapshots/upload?priority=snapshot" \
        > /tmp/qdrant-restore.json
    echo "  qdrant restore response:"
    cat /tmp/qdrant-restore.json
    echo
}

main() {
    need_root
    verify_tarball

    local staging
    staging="$(mktemp -d)"
    trap 'rm -rf "${staging}"' EXIT
    tar -xzf "${TARBALL}" -C "${staging}"

    echo "== humanoid-robot restore from $(basename "${TARBALL}") =="
    ls -la "${staging}"

    stop_stack
    restore_audit_db "${staging}"
    restore_qdrant_snapshot "${staging}"

    cat <<EOF

Restore complete. Verify then bring the stack back:

  cd ${COMPOSE_DIR}
  docker compose up -d
  # or with vector search:
  docker compose --profile rag up -d

Previous audit DB (if any) is backed up alongside the current one as
${STATE_DIR}/safety_audit.sqlite.pre-restore-*.
EOF
}

main "$@"
