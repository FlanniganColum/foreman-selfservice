# Kubernetes / Helm production deployment

Docker Compose is the supported development and integration-test environment.
The Helm chart under `deploy/helm/foreman-selfservice` is the production
Kubernetes deployment definition.

Use a currently supported Kubernetes release and Helm 4 for new production deployments. The chart uses standard stable Kubernetes APIs and a Helm v2 chart format.

## Architecture

```text
Browser
  |
Ingress / TLS
  |
ClusterIP Service
  |
+--------------------+
| web Deployment x2+ |
+--------------------+
     |          |
     |          +------> Redis (external)
     +-----------------> PostgreSQL (external)
     |
     +-----------------> Foreman API

worker Deployment xN ---> Redis/PostgreSQL/Foreman
scheduler x1 -----------> Redis/PostgreSQL
```

The Kubernetes deployment deliberately removes the Compose Nginx, PostgreSQL
and Redis containers. Ingress owns TLS and PostgreSQL/Redis are production
infrastructure dependencies.

## 1. Build and publish the application image

Use the same Dockerfile used by Compose:

```bash
docker build -t registry.example.com/platform/foreman-selfservice:1.1.0 .
docker push registry.example.com/platform/foreman-selfservice:1.1.0
```

For production, record the registry digest and set `image.digest` so the
release is immutable even if a tag is moved.

## 2. Prepare PostgreSQL

Create the portal database/user and configure TLS according to your database
platform. The application Secret receives a SQLAlchemy URL, for example:

```text
postgresql+psycopg://portal:password@postgres.example.com:5432/portal?sslmode=require
```

Do not run `flask db upgrade` manually as part of every Pod start. The chart
runs a one-shot migration Job before install and before upgrades.

## 3. Prepare Redis

Provide Redis URLs for:

```text
REDIS_URL             -> web sessions / rate limiting
CELERY_BROKER_URL     -> Celery broker
CELERY_RESULT_BACKEND -> Celery backend
```

The example uses database numbers 0, 1 and 2. A managed Redis platform can use
separate instances/endpoints instead.

## 4. Create namespace and Secret

```bash
kubectl create namespace foreman-selfservice
cp deploy/helm/examples/secret.example.yaml /secure/location/portal-secret.yaml
# Edit it outside source control.
kubectl -n foreman-selfservice apply -f /secure/location/portal-secret.yaml
```

Prefer an enterprise secret operator (External Secrets, Vault integration,
Sealed Secrets or equivalent) instead of committing Secret YAML containing real
credentials.

The migration hook depends on this Secret, so it must exist before the first
Helm installation.

## 5. Foreman CA

When Foreman uses an internal CA:

```bash
kubectl -n foreman-selfservice create configmap foreman-ca \
  --from-file=foreman-ca.pem=/path/to/corporate-ca.pem
```

Then set:

```yaml
foremanCa:
  existingConfigMap: foreman-ca
  key: foreman-ca.pem
```

Keep `config.foreman.verifyTls: true`.

## 6. Configure production values

Start with:

```bash
cp deploy/helm/examples/values-production.example.yaml values-production.yaml
```

At minimum change:

- image repository/tag/digest
- portal FQDN
- Entra/LDAP settings in use
- Foreman URL and username
- Ingress class and TLS Secret/annotations
- optional CA ConfigMap

Do not place passwords/tokens in the values file.

## 7. Install

```bash
helm upgrade --install foreman-selfservice \
  deploy/helm/foreman-selfservice \
  --namespace foreman-selfservice \
  --create-namespace \
  --values values-production.yaml \
  --wait \
  --timeout 10m
```

The sequence is:

1. migration hook runs `flask --app wsgi:app db upgrade`;
2. migration must complete successfully;
3. web/worker/scheduler resources are installed or upgraded;
4. optional first-install bootstrap hook runs when enabled.

## 8. Bootstrap an administrator

The preferred production authentication path is Entra/LDAP, but a local
break-glass administrator can be created once.

Option A: first-install hook:

```yaml
bootstrapAdmin:
  enabled: true
```

with `BOOTSTRAP_ADMIN_*` present in the application Secret.

Option B: manual command:

```bash
kubectl -n foreman-selfservice exec deployment/foreman-selfservice-web -- \
  flask --app wsgi:app portal bootstrap
```

The bootstrap password must still satisfy the application's minimum length.

## 9. Chiklets

### Bundled ConfigMap

Default:

```yaml
chiklets:
  mode: bundled
```

The chart packages its JSON Chiklets into a ConfigMap and mounts the entire
directory. Kubernetes eventually projects ConfigMap changes into the mounted
volume, allowing the application's Chiklet reload behavior to observe changes.

### Existing ConfigMap

```yaml
chiklets:
  mode: existingConfigMap
  existingConfigMap: foreman-selfservice-chiklets
```

### Existing PVC

Recommended if Chiklets include binary assets or are updated by an external
content-management/GitOps process:

```yaml
chiklets:
  mode: pvc
  existingClaim: foreman-selfservice-chiklets
```

For multiple web/worker Pods on different nodes, use storage with the access
mode required by your environment (typically RWX for a shared live content
volume).

### Image

```yaml
chiklets:
  mode: image
```

This uses `/app/chiklets` from the immutable application image.

## 10. TLS / Ingress

Kubernetes does not run the Compose Nginx container. TLS is terminated by the
cluster ingress implementation:

```yaml
ingress:
  enabled: true
  className: nginx
  host: selfservice.example.com
  tls:
    enabled: true
    secretName: foreman-selfservice-tls
```

Set the Entra redirect URI to the same HTTPS host.

## 11. Security model

The chart defaults to:

- non-root UID/GID 10001;
- `allowPrivilegeEscalation: false`;
- all Linux capabilities dropped;
- read-only container root filesystem;
- `RuntimeDefault` seccomp;
- no mounted Kubernetes API token;
- writable `emptyDir` only for `/tmp` and Celery Beat runtime state;
- external credentials through an existing Secret;
- verified TLS to Foreman by default.

`networkPolicy.enabled` adds a baseline ingress policy. Full egress restriction
is intentionally environment-specific because the application may need DNS,
PostgreSQL, Redis, Foreman, LDAP/AD and Microsoft Entra destinations.

## 12. Operations

Status:

```bash
kubectl -n foreman-selfservice get deploy,pods,svc,ingress
```

Logs:

```bash
kubectl -n foreman-selfservice logs deployment/foreman-selfservice-web --tail=200
kubectl -n foreman-selfservice logs deployment/foreman-selfservice-worker --tail=200
kubectl -n foreman-selfservice logs deployment/foreman-selfservice-scheduler --tail=200
```

Scale:

```bash
helm upgrade foreman-selfservice deploy/helm/foreman-selfservice \
  -n foreman-selfservice \
  --reuse-values \
  --set web.replicaCount=4 \
  --set worker.replicaCount=4
```

Never scale Celery Beat. The scheduler is intentionally fixed at one replica.
It queues Foreman host inventory sync every 15 minutes by default; configure
`config.foreman.hostSyncIntervalSeconds` in Helm values to change this interval.

Upgrade:

```bash
helm upgrade foreman-selfservice deploy/helm/foreman-selfservice \
  -n foreman-selfservice \
  -f values-production.yaml \
  --wait --timeout 10m
```

Rollback:

```bash
helm history foreman-selfservice -n foreman-selfservice
helm rollback foreman-selfservice <REVISION> -n foreman-selfservice --wait
```

Application/database rollback compatibility must be considered before rolling
back across a schema migration.

## 13. Plain Kubernetes YAML

Helm remains the single source of deployment templates. To produce static YAML:

```bash
VALUES=values-production.yaml deploy/kubernetes/render.sh
```

For a non-Helm deployment:

```bash
VALUES=values-production.yaml deploy/kubernetes/apply.sh
```

The script applies and waits for the migration Job before applying the ordinary
resources. This keeps the ordering semantics that Helm provides without
maintaining a second set of manifests.

## 14. Validation before go-live

- `helm lint deploy/helm/foreman-selfservice -f values-production.yaml`
- `helm template ...` succeeds.
- migration hook completes.
- web has at least two Ready replicas.
- worker and scheduler are running.
- `/health/live` and `/health/ready` return HTTP 200 through the Ingress.
- Foreman CA validation succeeds without disabling TLS verification.
- Entra and/or LDAP login works.
- break-glass login is tested and secured.
- job submission, approval, execution, failure, cancellation and output refresh
  are tested against production-like Foreman.
- PostgreSQL backup/restore and Redis recovery procedures are documented.
