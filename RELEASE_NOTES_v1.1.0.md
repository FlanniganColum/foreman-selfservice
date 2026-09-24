# Foreman Self-Service Portal v1.1.0

This release adds a production Kubernetes deployment path while preserving the
existing Docker Compose workflow for development and integration testing.

## Deployment model

- Development/test: `docker compose` with local PostgreSQL, Redis and Nginx.
- Production: Helm/Kubernetes with external PostgreSQL and Redis, Ingress TLS,
  scalable web/worker Deployments and a singleton Celery Beat scheduler.

## Kubernetes highlights

- pre-install/pre-upgrade database migration Job;
- optional first-install local administrator bootstrap Job;
- two web replicas by default with PodDisruptionBudget;
- independently scalable workers;
- scheduler fixed at one replica with `Recreate` strategy;
- non-root UID/GID 10001, read-only root filesystem, dropped capabilities and
  RuntimeDefault seccomp;
- no service-account token mounted into application Pods;
- bundled, existing ConfigMap, existing PVC or image-backed Chiklet modes;
- optional Foreman corporate CA mount;
- plain Kubernetes render/apply scripts generated from the Helm source of truth.

See `docs/KUBERNETES.md` for deployment and operations instructions.
