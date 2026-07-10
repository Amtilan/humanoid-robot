#!/usr/bin/env bash
#
# Preview a release changelog locally — same commit-log filter the CI
# workflow uses. Run before triggering release.yaml if you want to
# eyeball what will land in the GitHub Release body.
#
# Usage:
#   bash deploy/scripts/preview-release.sh v1.0.0
#

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "usage: $0 <version> (e.g. v1.0.0)" >&2
    exit 1
fi

if [[ ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
    echo "invalid semver: '$VERSION' (expected vMAJOR.MINOR.PATCH[-prerelease])" >&2
    exit 1
fi

if git rev-parse -q --verify "refs/tags/${VERSION}" > /dev/null; then
    echo "warning: tag ${VERSION} already exists locally" >&2
fi

prev="$(git tag --sort=-v:refname | grep -E '^v[0-9]' | head -n1 || true)"

echo "# ${VERSION}"
echo
if [[ -n "$prev" ]]; then
    echo "## Changes since \`${prev}\`"
    range="${prev}..HEAD"
else
    echo "## Initial release"
    range=""
fi
echo

git log --reverse --pretty=format:"* %s (%h)" ${range} \
    | grep -Ev '^\* (Merge |Bump )' \
    || echo "* (no commits)"
echo
