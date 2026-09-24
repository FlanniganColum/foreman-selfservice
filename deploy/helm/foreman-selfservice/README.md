# Foreman Self-Service Helm chart

This chart is the production deployment path for the Foreman Self-Service
Portal. Docker Compose remains the development/test path.

## Production assumptions

- Kubernetes cluster with a working Ingress controller.
- External PostgreSQL and Redis services.
- Application image already pushed to a registry reachable by the cluster.
- A Kubernetes Secret created before installation with application credentials.
- Optional ConfigMap containing the corporate CA that signs Foreman's TLS cert.
- TLS certificate managed by the Ingress platform or provided as a TLS Secret.

The chart intentionally does not deploy PostgreSQL or Redis. Database HA,
backup/PITR and Redis availability should be operated independently from the
application release.

## Install

```bash
kubectl create namespace foreman-selfservice
kubectl -n foreman-selfservice apply -f ../examples/secret.example.yaml
kubectl -n foreman-selfservice apply -f ../examples/foreman-ca-configmap.example.yaml

helm upgrade --install foreman-selfservice . \
  -n foreman-selfservice \
  -f ../examples/values-production.example.yaml \
  --wait \
  --timeout 10m
```

Replace the example Secret/CA data before applying them.

## Workloads

- `web`: scalable Gunicorn/Flask Deployment, 2 replicas by default.
- `worker`: independently scalable Celery worker Deployment.
- `scheduler`: singleton Celery Beat Deployment using `Recreate` strategy.
- `migration`: pre-install/pre-upgrade hook Job running `flask db upgrade`.
- optional `bootstrap-admin`: post-install hook Job.

## Chiklets

`chiklets.mode` supports:

- `bundled`: chart-owned ConfigMap containing the shipped JSON Chiklets.
- `existingConfigMap`: operator-managed ConfigMap.
- `pvc`: existing shared PVC; best option for live JSON plus binary image assets.
- `image`: use Chiklets baked into the container image.

Do not mount ConfigMap Chiklets with `subPath`; Kubernetes does not propagate
ConfigMap updates into subPath mounts.

## Secrets

`secrets.existingSecret` is required. At minimum it should provide:

- `SECRET_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`

Add authentication and Foreman credentials required by your enabled providers.
See `../examples/secret.example.yaml`.

## Database migrations

The migration Job executes before install/upgrade resources are changed. The
Secret therefore has to exist before the first `helm install`.

Inspect a failed migration before retrying:

```bash
kubectl -n foreman-selfservice get jobs
kubectl -n foreman-selfservice logs job/foreman-selfservice-migrate
```

The failed hook Job is intentionally retained; successful migration hooks are
deleted.

## Break-glass administrator

For a first install only, set:

```yaml
bootstrapAdmin:
  enabled: true
```

and provide the `BOOTSTRAP_ADMIN_*` keys in the existing Secret. Disable the
hook again for normal upgrades.

Alternatively run the command manually:

```bash
kubectl -n foreman-selfservice exec deployment/foreman-selfservice-web -- \
  flask --app wsgi:app portal bootstrap
```

## Scaling

Scale web and workers independently:

```bash
helm upgrade foreman-selfservice . -n foreman-selfservice \
  --reuse-values \
  --set web.replicaCount=4 \
  --set worker.replicaCount=4
```

Do not scale the scheduler above one replica. The chart fixes it at one replica
to avoid duplicate Celery Beat scheduling.

## Verification

```bash
kubectl -n foreman-selfservice get pods
kubectl -n foreman-selfservice rollout status deployment/foreman-selfservice-web
helm test foreman-selfservice -n foreman-selfservice
```
