#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT_DIR}/deploy/helm/foreman-selfservice/chiklets"
mkdir -p "${DEST}"
find "${DEST}" -maxdepth 1 -type f -name '*.json' -delete
cp "${ROOT_DIR}"/chiklets/*.json "${DEST}/"
echo "Synced Chiklet JSON files into the Helm chart."
if [ -d "${ROOT_DIR}/chiklets/assets" ] && find "${ROOT_DIR}/chiklets/assets" -type f -print -quit | grep -q .; then
  echo "NOTE: bundled Helm mode packages JSON only; use chiklets.mode=pvc for binary/nested assets." >&2
fi
