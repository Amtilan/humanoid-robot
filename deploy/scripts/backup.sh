#!/usr/bin/env bash
#
# Snapshot the humanoid-robot durable state into a single dated tarball
# under /var/backups/humanoid-robot/.  Safe to run against a live stack:
# uses SQLite's online `.backup` command for the audit DB and Qdrant's
# HTTP snapshot API for the vector index (no bind-mount copy).
#
# Usage:
#   sudo bash deploy/scripts/backup.sh
#   sudo BACKUP_DIR=/mnt/backups bash deploy/scripts/backup.sh
#   sudo bash deploy/scripts/backup.sh --core-only
#
# Retention: keeps the newest `BACKUP_RETAIN` (default 14) tarballs and
# deletes older ones.  Set BACKUP_RETAIN=0 to disable pruning.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/humanoid-robot}"
STATE_DIR="${STATE_DIR:-/var/lib/humanoid-robot}"
BACKUP_RETAIN="${BACKUP_RETAIN:-14}"
QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
QDRANT_COLLECTION="${QDRANT_COLLECTION:-knowledge}"

INCLUDE_CORE=1
INCLUDE_QDRANT=1

for arg in "$@"; do
    case "$arg" in
        --core-only)    INCLUDE_QDRANT=0 ;;
        --qdrant-only)  INCLUDE_CORE=0   ;;
        *) echo "unknown arg: $arg" >&2 && exit 1 ;;
    esac
done

need_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "must run as root (use sudo)" >&2
        exit 1
    fi
}

timestamp() {
    date -u +%Y%m%dT%H%M%SZ
}

ensure_dirs() {
    install -d -m 0750 "${BACKUP_DIR}"
}

snapshot_audit_db() {
    local db="${STATE_DIR}/safety_audit.sqlite"
    if [[ ! -f "${db}" ]]; then
        echo "  no audit DB at ${db}, skipping"
        return
    fi
    local dst="$1"
    # Online snapshot — safe while cortex-core has the db open, since
    # SQLite serialises via the WAL.
    sqlite3 "${db}" ".backup '${dst}/safety_audit.sqlite'"
    echo "  audit DB → ${dst}/safety_audit.sqlite ($(du -h "${dst}/safety_audit.sqlite" | cut -f1))"
}

snapshot_qdrant_collection() {
    local dst="$1"
    local trigger="${QDRANT_URL}/collections/${QDRANT_COLLECTION}/snapshots"
    echo "  creating qdrant snapshot for ${QDRANT_COLLECTION}"
    local http
    http=$(curl -sf -X POST -o /tmp/qdrant-snapshot.json -w "%{http_code}" "${trigger}") || {
        echo "  WARNING: qdrant snapshot request failed (http=${http}); is Qdrant running?" >&2
        return
    }
    local name
    name=$(python3 -c 'import json,sys;d=json.load(open("/tmp/qdrant-snapshot.json"));print(d["result"]["name"])')
    curl -sf -o "${dst}/${name}" "${trigger}/${name}"
    echo "  qdrant snapshot → ${dst}/${name} ($(du -h "${dst}/${name}" | cut -f1))"
    # Best-effort cleanup on the qdrant side so its data volume doesn't grow.
    curl -sf -X DELETE "${trigger}/${name}" > /dev/null || true
}

prune() {
    if [[ "${BACKUP_RETAIN}" -le 0 ]]; then
        return
    fi
    mapfile -t stale < <(
        ls -1t "${BACKUP_DIR}"/humanoid-robot-*.tar.gz 2>/dev/null \
            | tail -n +$((BACKUP_RETAIN + 1))
    )
    for f in "${stale[@]}"; do
        echo "  prune ${f}"
        rm -f -- "${f}"
    done
}

main() {
    need_root
    ensure_dirs

    local stamp
    stamp="$(timestamp)"
    local staging
    staging="$(mktemp -d)"
    trap 'rm -rf "${staging}"' EXIT

    echo "== humanoid-robot backup ${stamp} =="
    (( INCLUDE_CORE )) && snapshot_audit_db "${staging}"
    (( INCLUDE_QDRANT )) && snapshot_qdrant_collection "${staging}"

    if ! ls "${staging}"/* >/dev/null 2>&1; then
        echo "no artefacts collected — refusing to write an empty tarball" >&2
        exit 1
    fi

    local out="${BACKUP_DIR}/humanoid-robot-${stamp}.tar.gz"
    tar -C "${staging}" -czf "${out}" .
    chown root:root "${out}"
    chmod 0640 "${out}"

    echo
    echo "wrote ${out} ($(du -h "${out}" | cut -f1))"
    prune

    ls -1t "${BACKUP_DIR}"/humanoid-robot-*.tar.gz 2>/dev/null | head -20
}

main "$@"
