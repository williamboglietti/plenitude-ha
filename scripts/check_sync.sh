#!/usr/bin/env bash
# Verify the add-on's API client copy is byte-identical to the custom integration's.
# Used by CI to prevent drift.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${REPO_ROOT}/custom_components/plenitude"
DST="${REPO_ROOT}/addon/plenitude2mqtt/service"

fail=0

for f in api/kraken.py api/portal.py api/rsc_parser.py api/__init__.py cost.py models.py; do
    if ! diff -q "${SRC}/${f}" "${DST}/${f}" > /dev/null; then
        echo "✗ ${f} differs between custom_components/ and addon/"
        diff "${SRC}/${f}" "${DST}/${f}" || true
        fail=1
    fi
done

if [ ${fail} -eq 0 ]; then
    echo "✓ All shared files are in sync."
else
    echo ""
    echo "Run: scripts/sync_api.sh"
    exit 1
fi
