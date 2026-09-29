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
- Assign a technical and/or business owner to each server, and grant final reviewers the Linux admin role.
- For Chiklets configured for full approval, verify an owner cannot approve their own request and the Linux reviewer differs from the owner approver. For business approval, verify only the assigned business owner can approve and cannot override variables. Review each approval-free Chiklet's JSON and Foreman job template before enabling it.
- Verify administrator overrides stay within the saved Chiklet schema and sensitive overrides remain encrypted in the portal database, absent from audits and request history, and are sent to Foreman only as job inputs after approval. Confirm Foreman job-input retention and output controls in your environment.
- Test success/failure/cancellation status reconciliation against your Foreman version.
- Back up and restore PostgreSQL; test rollback procedures.
- Run dependency/container vulnerability scans and a penetration test before go-live.
