#!/usr/bin/env bash
#
# Verify that every image tag we're about to run was signed by our
# GitHub Actions publish-images.yaml workflow.  Enforced by
# install-on-robot.sh before `docker compose pull` — fail-closed by
# default because a rotated / hijacked GHCR token is exactly the
# scenario cosign+OIDC is meant to catch.
#
# Verification uses keyless cosign (no local public key): we assert
# the signing certificate was issued by GitHub's Fulcio instance and
# that the SAN encodes an OIDC identity belonging to THIS repo's
# publish-images.yaml workflow.  If either check fails we exit
# non-zero, no matter which key someone might have on the box.
#
# Usage:
#   deploy/scripts/verify-images.sh                    # all images at IMAGE_TAG
#   deploy/scripts/verify-images.sh humanoid-robot-base:v1.0.0
#
# Env:
#   IMAGE_REGISTRY  (default: ghcr.io)
#   IMAGE_OWNER     (default: amtilan)
#   IMAGE_TAG       (default: main)
#   VERIFY_REPO     (default: Amtilan/humanoid-robot) — controls the
#                   certificate-identity regex.
#
# Exit codes:
#   0  every requested image verified against our workflow identity
#   3  cosign binary missing (installer catches this and reprompts)
#   4  at least one signature check failed → refuse to run those bits

set -euo pipefail

IMAGE_REGISTRY="${IMAGE_REGISTRY:-ghcr.io}"
IMAGE_OWNER="${IMAGE_OWNER:-amtilan}"
IMAGE_TAG="${IMAGE_TAG:-main}"
VERIFY_REPO="${VERIFY_REPO:-Amtilan/humanoid-robot}"

# Anchored regex so a workflow file in a fork with the same basename
# (e.g. Attacker/humanoid-robot/.github/…/publish-images.yaml) can't
# satisfy the check.
IDENTITY_REGEX="^https://github.com/${VERIFY_REPO}/.github/workflows/publish-images.yaml@"
OIDC_ISSUER="https://token.actions.githubusercontent.com"

DEFAULT_IMAGES=(
    "humanoid-robot-base"
    "humanoid-robot-dashboard"
)

if [[ $# -gt 0 ]]; then
    TARGETS=("$@")
else
    TARGETS=()
    for name in "${DEFAULT_IMAGES[@]}"; do
        TARGETS+=("${IMAGE_REGISTRY}/${IMAGE_OWNER}/${name}:${IMAGE_TAG}")
    done
fi

if ! command -v cosign >/dev/null 2>&1; then
    cat >&2 <<'EOF'
cosign not found. Install it before running this script:

  # x86_64
  curl -sSL -o /usr/local/bin/cosign \
    https://github.com/sigstore/cosign/releases/latest/download/cosign-linux-amd64
  # arm64 / Jetson
  curl -sSL -o /usr/local/bin/cosign \
    https://github.com/sigstore/cosign/releases/latest/download/cosign-linux-arm64
  chmod +x /usr/local/bin/cosign

Or bypass verification (you own the risk) by passing --skip-verify
to install-on-robot.sh.
EOF
    exit 3
fi

echo "Verifying image signatures issued by ${VERIFY_REPO}'s publish-images.yaml…"
echo "  OIDC issuer:  ${OIDC_ISSUER}"
echo "  identity:     ${IDENTITY_REGEX}"
echo

failed=0
for ref in "${TARGETS[@]}"; do
    printf "  %-70s " "${ref}"
    # --output=text keeps the noise tight; we only care about pass/fail.
    if cosign verify "${ref}" \
        --certificate-identity-regexp "${IDENTITY_REGEX}" \
        --certificate-oidc-issuer "${OIDC_ISSUER}" \
        --output=text >/dev/null 2>&1; then
        echo "OK"
    else
        echo "FAIL"
        failed=$((failed + 1))
    fi
done

if [[ ${failed} -gt 0 ]]; then
    echo
    echo "${failed} image(s) failed signature verification." >&2
    echo "Refusing to proceed. If you understand the risk (e.g. running a" >&2
    echo "local dev build that was never pushed), rerun the installer with" >&2
    echo "--skip-verify." >&2
    exit 4
fi

echo
echo "All ${#TARGETS[@]} image(s) verified."
