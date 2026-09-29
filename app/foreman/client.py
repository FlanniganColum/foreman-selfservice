import requests
from flask import current_app
from ..catalog.service import sensitive_fields
from ..sensitive import reveal_fields


class ForemanError(RuntimeError):
    def __init__(self, message, *, status_code=None, method=None, path=None, response_text=None):
        super().__init__(message)
        self.status_code = status_code
        self.method = method
        self.path = path
        self.response_text = response_text


def _escape(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


class ForemanClient:
    def __init__(self):
        cfg = current_app.config
        self.base = cfg["FOREMAN_URL"].rstrip("/")
        self.timeout = cfg["FOREMAN_TIMEOUT_SECONDS"]
        self.verify = cfg["FOREMAN_CA_BUNDLE"] or cfg["FOREMAN_VERIFY_TLS"]
        self.mock = cfg["FOREMAN_MOCK"]
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        if cfg["FOREMAN_API_TOKEN"]:
            if not cfg["FOREMAN_USERNAME"]:
                raise ForemanError("FOREMAN_USERNAME is required when using a Foreman Personal Access Token")
            self.session.auth = (cfg["FOREMAN_USERNAME"], cfg["FOREMAN_API_TOKEN"])
        elif cfg["FOREMAN_USERNAME"]:
            self.session.auth = (cfg["FOREMAN_USERNAME"], cfg["FOREMAN_PASSWORD"])

    def _request(self, method, path, **kwargs):
        r = self.session.request(
            method,
            f"{self.base}{path}",
            timeout=self.timeout,
            verify=self.verify,
            **kwargs,
        )
        if not r.ok:
            response_text = r.text[:1000]
            raise ForemanError(
                f"Foreman {method} {path} returned {r.status_code}: {response_text}",
                status_code=r.status_code,
                method=method,
                path=path,
                response_text=response_text,
            )
        return r.json() if r.content else {}

    def resolve_template_id(self, cfg):
        if cfg.get("job_template_id"):
            return str(cfg["job_template_id"])
        data = self._request(
            "GET",
            "/api/job_templates",
            params={"search": f'name="{_escape(cfg["job_template_name"])}"', "per_page": "all"},
        )
        matches = data.get("results", [])
        if not matches:
            raise ForemanError(f"Foreman job template not found: {cfg['job_template_name']}")
        return str(matches[0]["id"])

    def find_job_by_correlation(self, correlation_id):
        if self.mock:
            return None
        data = self._request(
            "GET",
            "/api/job_invocations",
            params={
                "search": f'description ~ "{_escape(correlation_id)}"',
                "order": "id DESC",
                "per_page": "1",
            },
        )
        results = data.get("results", [])
        return results[0] if results else None

    def create_job(self, config_snapshot, target_snapshot, form_data, correlation_id=None):
        if self.mock:
            import secrets

            return {"id": f"mock-{secrets.token_hex(4)}", "status_label": "queued"}
        secret_names = sensitive_fields(config_snapshot)
        if secret_names and (not self.base.startswith("https://") or not self.verify):
            raise ForemanError("Sensitive job inputs require verified HTTPS to Foreman")
        fcfg = config_snapshot["foreman"]
        template_id = self.resolve_template_id(fcfg)
        values = reveal_fields(form_data, secret_names, current_app.config["SECRET_KEY"])
        inputs = {}
        for foreman_name, source_name in fcfg.get("input_map", {}).items():
            if source_name in values:
                inputs[foreman_name] = values[source_name]
        description = f"Self-Service {{job_category}} - {target_snapshot['name']}"
        if correlation_id:
            description += f" | {correlation_id}"
        payload = {
            "job_invocation": {
                "job_template_id": template_id,
                "targeting_type": "static_query",
                "search_query": f'name="{_escape(target_snapshot["name"])}"',
                "inputs": inputs,
                "description_format": description,
            }
        }
        return self._request("POST", "/api/job_invocations", json=payload)

    def get_job(self, job_id):
        if self.mock:
            return {
                "id": job_id,
                "status_label": "succeeded",
                "status": 0,
                "succeeded": 1,
                "failed": 0,
                "pending": 0,
            }
        return self._request("GET", f"/api/job_invocations/{job_id}", params={"host_status": "true"})

    @staticmethod
    def _hosts_from_job_state(state):
        """Return hosts embedded in a job invocation response, if present.

        Older Foreman/Remote Execution combinations may not implement
        GET /api/job_invocations/:id/hosts, while still returning the targeted
        host list in GET /api/job_invocations/:id?host_status=true.
        """
        if not isinstance(state, dict):
            return []
        targeting = state.get("targeting") or {}
        hosts = targeting.get("hosts") or state.get("hosts") or []
        if isinstance(hosts, dict):
            hosts = hosts.get("results") or []
        return hosts if isinstance(hosts, list) else []

    def get_hosts(self, job_id, state=None):
        if self.mock:
            return []
        try:
            data = self._request(
                "GET",
                f"/api/job_invocations/{job_id}/hosts",
                params={"per_page": "all"},
            )
            return data.get("results", [])
        except ForemanError as exc:
            if exc.status_code != 404:
                raise
            # Compatibility fallback for Foreman versions where the dedicated
            # host-list endpoint is unavailable.
            state = state or self.get_job(job_id)
            return self._hosts_from_job_state(state)

    def get_host_output(self, job_id, host_id):
        if self.mock:
            return "Mock execution completed successfully."
        return self._request("GET", f"/api/job_invocations/{job_id}/hosts/{host_id}")
