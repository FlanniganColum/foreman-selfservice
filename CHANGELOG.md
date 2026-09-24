# Changelog

## 1.1.0

- Added a production Helm/Kubernetes deployment while retaining Docker Compose for development and testing.
- Added separate web, worker and singleton scheduler Deployments, ClusterIP Service and configurable Ingress/TLS.
- Added pre-install/pre-upgrade database migration Job so schema upgrades do not race across web replicas.
- Added optional first-install break-glass administrator bootstrap Job.
- Added non-root/read-only Pod security defaults, dropped capabilities, RuntimeDefault seccomp and disabled service-account token mounts.
- Added web PodDisruptionBudget, resource requests/limits, health probes and configurable placement controls.
- Added bundled/existing-ConfigMap/PVC/image Chiklet content modes.
- Added plain-Kubernetes render/apply scripts generated from the Helm source of truth.
- Standardized the container runtime account on UID/GID 10001 for predictable Kubernetes `runAsNonRoot` behavior.
- Added Kubernetes production deployment and operations documentation.

## 1.0.5

- Made the Chiklet JSON Schema the authoritative source for end-user deployment customisation.
- Added generic GUI rendering for dropdowns/enums, booleans, numeric fields, multi-selects, text areas, dates and date/time fields.
- Defaults remain editable unless a field is explicitly marked `readOnly: true`.
- Added `x-ui` presentation hints for form groups, ordering, widths, placeholders, help text and enum display labels.
- Enforced read-only values server-side so browser tampering cannot override policy-owned configuration.
- Added validation that every `foreman.input_map` source references a real `form_schema.properties` field.
- Invalid form submissions are re-rendered with the user's valid selections preserved.
- Added Chiklet schema authoring documentation and regression tests for schema-driven forms and tamper resistance.

## 1.0.4

- Expanded the request Execution area into a full-width analysis workspace.
- Added a large, resizable Foreman output console plus full-screen and copy-output controls.
- Added automatic Foreman output refresh while jobs are queued/running without forcing the analyst scroll position.
- Execution status now refreshes every 4 seconds in the browser and all progress steps update live.
- Reduced the default background Foreman reconciliation interval from 15 seconds to 5 seconds; configurable with `FOREMAN_RECONCILE_INTERVAL_SECONDS`.
- Live refresh stops automatically after a terminal request state while retaining manual output refresh.

## 1.0.3

- Added Foreman compatibility fallback when `GET /api/job_invocations/:id/hosts` is unavailable (404), using hosts embedded in the job-invocation response.
- Preserves terminal Foreman job state even when host-detail enrichment fails.
- Uses structured Foreman failed-host counts as a defensive signal when mapping terminal execution state.
- Reuses cached/fallback target host data when retrieving Foreman output.
- Automatically loads Foreman output on failed or cancelled requests in the request detail view.
- Added regression tests for older Foreman host-list compatibility and failure-state mapping.

## 1.0.2

- Added `allowed_server_groups: ["*"]` wildcard support without weakening per-user server-group RBAC.
- Centralised target-server authorization so catalogue filtering and request submission use the same server-side rule.
- Added structured Chiklet image/text icons while preserving legacy string/emoji icons.
- Added authenticated hot-loading of assets from `chiklets/assets/` with supported image-type validation and no-cache responses.
- Updated Chiklet authoring documentation with wildcard, asset and MSSQL ODBC examples.

## 1.0.1

- Fixed Celery 5.5 startup failure caused by calling the non-existent `Celery.config_from_mapping` method.
- Celery is now configured through `celery.conf.update(...)` with broker/backend supplied to the application constructor.
- Explicitly registers `app.jobs.tasks` so workers recognise execution, recovery and reconciliation tasks at startup.
- Hardened the readiness probe to use SQLAlchemy `text()` directly.
- Added detailed TLS/self-signed/enterprise certificate installation and validation documentation.

## 1.0.0

- Initial enterprise-oriented Foreman Self-Service Portal build.
- Entra ID, LDAP/AD and local authentication.
- Role and server-group RBAC.
- JSON Schema-driven Chiklets.
- Mandatory approval with separation of duties.
- Foreman API v2 submission, retry/recovery, live status and output retrieval.
- PostgreSQL, Redis, Celery and Nginx/TLS container stack.
- Audit search/export and request history.
- Generated light-theme branding assets.
