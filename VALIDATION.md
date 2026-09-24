# Build validation record

Validation performed in the artifact-generation environment for v1.1.0:

- Python source: `compileall` passed for the application source.
- Chiklet JSON parsing: passed for every root Chiklet and every bundled Helm copy.
- Docker Compose YAML parsing: passed; the Compose file itself is unchanged from the supplied baseline.
- Helm `Chart.yaml`, `values.yaml` and example YAML parsing: passed.
- `values.schema.json`: valid JSON; default and production-example merged values validate against the schema.
- Helm Go-template syntax: every template parsed successfully with Go `text/template` plus Helm-compatible function stubs.
- Default chart rendering: structurally rendered and parsed as valid YAML for ConfigMaps, web/worker/scheduler Deployments, Service, Ingress, migration Job, PDB, ServiceAccount and test Pod.
- Alternate chart rendering: structurally rendered and parsed as valid YAML with PVC Chiklets, Foreman CA, private-registry pull secret, bootstrap Job and NetworkPolicy enabled.
- Kubernetes helper scripts: `bash -n` passed.
- Helm Chiklet JSON copies are byte-identical to the root Chiklet JSON files.
- Application Python source, `docker-compose.yml`, `wsgi.py` and Celery application code are unchanged from the supplied baseline.
- Docker image runtime user was changed only to a deterministic numeric UID/GID 10001 for Kubernetes `runAsNonRoot` enforcement.

## Runtime/tooling limitations

The artifact-generation environment does not include a Docker daemon, a
Kubernetes cluster, or the Helm CLI. Outbound package downloads are blocked.
Therefore the following could not be executed here:

- `docker build` / `docker compose up`;
- the full pytest suite (the environment does not have the application Python dependencies installed);
- `helm lint` / `helm template` using the real Helm binary;
- Kubernetes API server-side validation.

The chart received static Go-template parsing plus rendered-YAML structural
validation as described above. Before production installation, CI/non-production
should run:

```bash
python -m pytest -q
helm lint deploy/helm/foreman-selfservice -f values-production.yaml
helm template foreman-selfservice deploy/helm/foreman-selfservice \
  -n foreman-selfservice -f values-production.yaml >/tmp/portal.yaml
kubectl apply --dry-run=server -f /tmp/portal.yaml
```

Then exercise real Entra/LDAP/Foreman integrations and complete
`docs/PRODUCTION.md` and `docs/KUBERNETES.md`.
