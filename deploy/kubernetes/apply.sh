#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELEASE="${RELEASE:-foreman-selfservice}"
NAMESPACE="${NAMESPACE:-foreman-selfservice}"
VALUES="${VALUES:-${ROOT_DIR}/deploy/helm/examples/values-production.example.yaml}"
OUTPUT_DIR="${OUTPUT_DIR:-${ROOT_DIR}/deploy/kubernetes/rendered}"

command -v helm >/dev/null || { echo "helm is required for rendering" >&2; exit 1; }
command -v kubectl >/dev/null || { echo "kubectl is required" >&2; exit 1; }

kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}"

RELEASE="${RELEASE}" NAMESPACE="${NAMESPACE}" VALUES="${VALUES}" OUTPUT_DIR="${OUTPUT_DIR}" \
  "${ROOT_DIR}/deploy/kubernetes/render.sh"

# Existing production Secret/CA objects must already exist.
# Remove the previous one-shot Job so its immutable Pod template can change.
kubectl -n "${NAMESPACE}" delete job -l \
  "app.kubernetes.io/instance=${RELEASE},app.kubernetes.io/component=migration" \
  --ignore-not-found=true --wait=true

kubectl -n "${NAMESPACE}" apply -f "${OUTPUT_DIR}/00-migration-job.yaml"
kubectl -n "${NAMESPACE}" wait --for=condition=complete job \
  -l "app.kubernetes.io/instance=${RELEASE},app.kubernetes.io/component=migration" \
  --timeout=5m

kubectl -n "${NAMESPACE}" apply -f "${OUTPUT_DIR}/10-application.yaml"
