#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHART_DIR="${ROOT_DIR}/deploy/helm/foreman-selfservice"
RELEASE="${RELEASE:-foreman-selfservice}"
NAMESPACE="${NAMESPACE:-foreman-selfservice}"
VALUES="${VALUES:-${ROOT_DIR}/deploy/helm/examples/values-production.example.yaml}"
OUTPUT_DIR="${OUTPUT_DIR:-${ROOT_DIR}/deploy/kubernetes/rendered}"

command -v helm >/dev/null || { echo "helm is required" >&2; exit 1; }
mkdir -p "${OUTPUT_DIR}"

# Render the migration separately so plain-kubectl deployments can run and wait
# for it before applying the long-running workloads.
helm template "${RELEASE}" "${CHART_DIR}" \
  --namespace "${NAMESPACE}" \
  --values "${VALUES}" \
  --show-only templates/migration-job.yaml \
  > "${OUTPUT_DIR}/00-migration-job.yaml"

# Render ordinary resources without Helm hooks or tests.
helm template "${RELEASE}" "${CHART_DIR}" \
  --namespace "${NAMESPACE}" \
  --values "${VALUES}" \
  --no-hooks \
  --skip-tests \
  > "${OUTPUT_DIR}/10-application.yaml"

printf 'Rendered:\n  %s\n  %s\n' \
  "${OUTPUT_DIR}/00-migration-job.yaml" \
  "${OUTPUT_DIR}/10-application.yaml"
