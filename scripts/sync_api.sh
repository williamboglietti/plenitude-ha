#!/usr/bin/env bash
# Sync the API client + shared models from the custom integration into the add-on.
# Run after any edit to custom_components/plenitude/api/, cost.py, or models.py.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${REPO_ROOT}/custom_components/plenitude"
DST="${REPO_ROOT}/addon/plenitude2mqtt/service"

# shellcheck source=_lib.sh
. "${REPO_ROOT}/scripts/_lib.sh"

# Copy api/ verbatim
rm -rf "${DST}/api"
mkdir -p "${DST}/api"
cp "${SRC}/api/"*.py "${DST}/api/"

# Copy cost.py and models.py verbatim
cp "${SRC}/cost.py" "${DST}/cost.py"
cp "${SRC}/models.py" "${DST}/models.py"

# Auto-generate a minimal const.py in the add-on (mirror of the keys api/ needs):
gen_const_py > "${DST}/const.py"

echo "✓ Synced api/, cost.py, models.py from custom_components/plenitude/ to addon/plenitude2mqtt/service/"
