# Architecture

## Runtime components

- **nginx** — TLS termination, HTTP->HTTPS redirect, security headers and login-rate guard.
- **web** — Gunicorn + Flask application serving the light UI and authenticated APIs.
- **worker** — Celery worker responsible for Foreman submissions and asynchronous work.
- **scheduler** — Celery Beat process that reconciles active Foreman jobs and recovers approved requests that were not submitted after a transient queue failure.
- **postgres** — system of record for identities, resource entitlements, requests, approvals, execution state and audit events.
- **redis** — server-side Flask sessions, rate-limit state, Celery broker/result backend and distributed execution lock.

## Trust boundaries

The browser never receives Foreman, LDAP bind or Entra client credentials. It submits only to the portal. Server authorization is checked again at request submission, status retrieval and output retrieval.

## Identity and RBAC

Authentication provider and authorization are independent. Entra, LDAP and local accounts resolve to a portal `User`. Application role controls capabilities; `ServerGroup` memberships control resources. Approver server groups are separate from target server groups.

## Change workflow

`PENDING_APPROVAL -> APPROVED -> QUEUED -> RUNNING -> SUCCEEDED|FAILED|CANCELLED`

Rejected requests terminate at `REJECTED`. A submitted request stores the Chiklet definition, values and target snapshot so later configuration changes cannot silently alter an approval.

## External-side-effect reliability

Foreman execution is protected with a Redis per-request lock. A request number is embedded in the Foreman job description as a correlation identifier. On a retry, the worker attempts to recover an already-created Foreman job before creating another. A periodic recovery task re-queues approved requests that have no Foreman job ID.
