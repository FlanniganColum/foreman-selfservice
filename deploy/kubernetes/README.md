# Plain Kubernetes deployment

Helm is the canonical deployment definition. These scripts render that chart to
plain Kubernetes YAML so the manifests do not have to be maintained twice.

## Render only

```bash
VALUES=deploy/helm/examples/values-production.example.yaml \
NAMESPACE=foreman-selfservice \
deploy/kubernetes/render.sh
```

This creates:

- `rendered/00-migration-job.yaml`
- `rendered/10-application.yaml`

Run the migration first, wait for completion, then apply the application YAML.

## Apply with kubectl

Create the production Secret and optional Foreman CA ConfigMap first, then:

```bash
VALUES=deploy/helm/examples/values-production.example.yaml \
NAMESPACE=foreman-selfservice \
deploy/kubernetes/apply.sh
```

This mode intentionally does not create a Helm release. For normal production
operations, upgrades and rollbacks, use Helm instead.
