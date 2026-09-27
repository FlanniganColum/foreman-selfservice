# Foreman Self-Service Portal

Production-oriented Flask portal for controlled Foreman + Ansible self-service automation.

## Included
- Microsoft Entra ID via MSAL authorization-code flow
- LDAP / Active Directory (LDAP/LDAPS)
- Local Argon2 password authentication for local/break-glass accounts
- JSON Schema-driven application **Chiklets**
- Role + server-group RBAC
- Two-stage server owner and Linux administrator approval with self-approval prevention
- Foreman API v2 job submission and periodic status reconciliation
- PostgreSQL, Redis, Celery worker/scheduler
- Audit events, original request snapshots, and tracked administrator overrides
- Nginx TLS 1.2/1.3 with local self-signed fallback
- Responsive light enterprise UI
- Docker Compose for development/testing plus Helm/Kubernetes production deployment

## Architecture

Development/testing:

`Browser -> Docker Nginx/TLS -> Gunicorn/Flask -> PostgreSQL + Redis -> Celery -> Foreman -> Ansible`

Production Kubernetes:

`Browser -> Ingress/TLS -> Service -> web Pods -> external PostgreSQL + chart Redis -> worker/scheduler -> Foreman -> Ansible`

This is a modular monolith plus independently scalable worker processes. It avoids premature microservice complexity while preserving clear module and runtime boundaries.

## Deployment modes

### Development / testing - Docker Compose

The existing Compose stack remains the local development and integration-test path:

```bash
cp .env.example .env
docker compose up -d --build
```

It includes PostgreSQL, Redis and Nginx for a self-contained environment.

### Production - Helm / Kubernetes

Use `deploy/helm/foreman-selfservice`. The production chart uses separate web, worker and singleton scheduler Deployments, an Ingress, a pre-install/pre-upgrade migration Job, Kubernetes security contexts, external PostgreSQL, and an optional bundled Redis StatefulSet (enabled by default).

Start with:

```bash
cp deploy/helm/examples/values-production.example.yaml values-production.yaml
```

Then follow [`docs/KUBERNETES.md`](docs/KUBERNETES.md). Plain Kubernetes YAML can be rendered from the same chart with `deploy/kubernetes/render.sh`, avoiding a second manifest source of truth.

## Quick start with mock Foreman
```bash
cp .env.example .env
# Change SECRET_KEY, POSTGRES_PASSWORD, DATABASE_URL password and BOOTSTRAP_ADMIN_PASSWORD
docker compose up -d --build
docker compose exec web flask --app wsgi:app portal bootstrap
docker compose exec web flask --app wsgi:app portal sync-hosts
```
Browse to `https://localhost`. Nginx creates a self-signed development certificate if none is mounted.

Sign in using the bootstrap local account. In **Administration**, assign users to **Demo Servers**, assign each server a technical and/or business owner, and give Linux reviewers the **Linux admin** role. Sample Chiklets then appear for entitled users. Chiklets requiring approval need an eligible server owner other than the requester.

## Two-stage approval

1. A technical or business owner assigned to the target server approves the original request. Either owner may give the one required owner approval. No job starts at this stage.
2. A user with the `linux_admin` role (or a global administrator) reviews the request, may override editable Chiklet fields, and gives final approval. Only then is the Foreman job queued.

The requester cannot approve either stage, and the owner approver cannot also give final approval. Original non-sensitive values remain visible in the request history; any non-sensitive overrides are shown alongside them. Sensitive overrides are saved as new Vault references and are never included in audit details. Fixed (`readOnly`) Chiklet fields cannot be overridden. New servers imported from Foreman need owner assignments in Administration to receive requests that require approval. Existing pending requests also require an owner assignment before progressing.

Each Chiklet can set `approval.mode` to `none` (queue immediately), `business` (the assigned business owner approves and queues), or `full` (server owner followed by a Linux administrator). Omitting it defaults to `full`. Self-service tasks can set `identity_binding` to supply the LDAP or Entra authenticated username as a fixed Foreman input. See [Chiklet form schema](docs/CHIKLETS.md) for configuration and password reset safeguards.

## TLS / HTTPS
If no certificate is supplied, the Nginx container automatically generates a persistent self-signed development certificate in `secrets/tls/`. For production, place the CA-issued chain in `secrets/tls/fullchain.pem` and matching private key in `secrets/tls/privkey.pem`. See [`docs/TLS.md`](docs/TLS.md) for installation, PFX conversion, validation and client trust instructions.

## Entra
Register `https://<portal-fqdn>/auth/entra/callback` as a web redirect URI. Set `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, and `ENTRA_CLIENT_SECRET`. Auto-provisioned users have no server entitlements until an administrator grants them.

## LDAP
Use LDAPS in production. Configure the LDAP URI, base DN, bind/search identity and filter. Auto-provisioned LDAP users also start without server access.

## Foreman
Set `FOREMAN_MOCK=false`, configure `FOREMAN_URL`, and use a least-privilege API identity. For a Foreman Personal Access Token, set both `FOREMAN_USERNAME` and `FOREMAN_API_TOKEN`; Foreman authenticates PATs as HTTP Basic username/token credentials. Leave TLS verification enabled. Job invocation/status code is isolated in `app/foreman/client.py` because Foreman API details can vary by version.

## Chiklets
Add JSON files under `chiklets/`. Each includes metadata, allowed server-group slugs, a Draft 2020-12 JSON Schema and a mapping from form field names to Foreman job-template inputs. The schema dynamically builds the end-user form: enums become dropdowns, booleans become toggles, numbers become numeric inputs, and defaults are editable unless `readOnly: true`. Submitted values are validated against the same schema and snapshotted at request time.

See `docs/CHIKLETS.md` for the complete schema/UI reference and examples.

## Tests
```bash
pip install -r requirements-dev.txt
pytest -q
```

Before real production use, complete the environment-specific validation in `docs/PRODUCTION.md` and `SECURITY.md`.
