# Production deployment checklist

For Kubernetes production deployments, use the Helm chart and complete
[`docs/KUBERNETES.md`](KUBERNETES.md). Docker Compose is retained for
development and integration testing.

- Use enterprise-issued TLS certificates and a production DNS name.
- Prefer managed/HA PostgreSQL and Redis for critical environments.
- Run multiple web and worker replicas; run one logical Celery Beat scheduler.
- Apply `flask db upgrade` as a controlled deployment step.
- Use a confidential Entra web application and exact redirect URIs; enforce MFA/Conditional Access in Entra.
- Use LDAPS with certificate verification and a read-only directory search identity.
- Use a dedicated least-privilege Foreman service account; constrain its Foreman permissions as a second boundary.
- Validate every Chiklet against the actual Foreman job-template input contract in non-production.
- Centralise Nginx/Gunicorn/Flask/Celery logs and audit events.
- Alert on readiness failures, stuck requests, worker absence, repeated auth failures and Foreman API errors.
- Verify unauthorized users cannot enumerate or submit to protected servers.
- Verify approvers are restricted to assigned groups and cannot self-approve.
- Test success/failure/cancellation status reconciliation against your Foreman version.
- Back up and restore PostgreSQL; test rollback procedures.
- Run dependency/container vulnerability scans and a penetration test before go-live.
