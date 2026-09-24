import pytest

from app.foreman.client import ForemanClient, ForemanError
from app.jobs.tasks import _map_foreman_state


def test_get_hosts_falls_back_to_targeting_hosts_on_404(app):
    with app.app_context():
        client = ForemanClient()
        client.mock = False
        calls = []

        def fake_request(method, path, **kwargs):
            calls.append(path)
            if path.endswith("/hosts"):
                raise ForemanError("not found", status_code=404, method=method, path=path)
            return {"targeting": {"hosts": [{"id": 42, "name": "demo01"}]}}

        client._request = fake_request
        hosts = client.get_hosts("247")
        assert hosts == [{"id": 42, "name": "demo01"}]
        assert calls == ["/api/job_invocations/247/hosts", "/api/job_invocations/247"]


def test_get_hosts_does_not_hide_non_404_foreman_errors(app):
    with app.app_context():
        client = ForemanClient()
        client.mock = False

        def fake_request(method, path, **kwargs):
            raise ForemanError("forbidden", status_code=403, method=method, path=path)

        client._request = fake_request
        with pytest.raises(ForemanError) as exc:
            client.get_hosts("247")
        assert exc.value.status_code == 403


def test_foreman_failed_label_maps_to_failed():
    status, label = _map_foreman_state({"status_label": "failed", "failed": 1, "pending": 0})
    assert status == "failed"
    assert label == "failed"


def test_structured_failed_host_count_overrides_success_label():
    status, label = _map_foreman_state({"status_label": "succeeded", "failed": 1, "pending": 0, "running": 0})
    assert status == "failed"
    assert label == "succeeded"
