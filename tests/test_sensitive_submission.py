import json
from pathlib import Path
from unittest.mock import Mock

from conftest import login
from app.extensions import db
from app.models import DeploymentRequest, Server


def secret_chiklet(app):
    data = json.loads(Path("chiklets/deploy-web-application.json").read_text())
    data["id"] = "sensitive-test"
    data["form_schema"]["properties"]["secret"] = {
        "type": "string", "title": "Password", "minLength": 8,
        "x-sensitive": True, "x-ui": {"widget": "password"},
    }
    data["form_schema"]["required"].append("secret")
    data["foreman"]["input_map"]["secret_ref"] = "secret"
    Path(app.config["CHIKLET_DIRECTORY"], "sensitive-test.json").write_text(json.dumps(data))
    return data


def test_secret_is_only_written_to_vault_and_reference_is_sent_to_foreman(app, client, monkeypatch):
    from app.foreman.client import ForemanClient
    secret_chiklet(app)
    app.config.update(VAULT_ADDR="https://vault.example.com", VAULT_TOKEN="test-token",
                      VAULT_KV_MOUNT="portal", VAULT_KV_PREFIX="requests")
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Mock(raise_for_status=Mock())
    monkeypatch.setattr("app.secrets.requests.post", post)
    login(client, "alice")
    with app.app_context():
        server_id = db.session.scalar(db.select(Server).where(Server.name == "demo01")).id
    value = "very-private-password"
    response = client.post("/requests/submit/sensitive-test", data={"server_id": server_id,
        "field__secret": value, "field__application": "payments-api", "field__version": "1.0"})
    assert response.status_code == 302
    with app.app_context():
        item = db.session.scalar(db.select(DeploymentRequest).where(DeploymentRequest.chiklet_id == "sensitive-test"))
        ref = item.form_data["secret"]
        assert ref == f"vault-kv2://portal/requests/{item.id}#secret"
        assert value not in json.dumps(item.form_data)
        assert value not in json.dumps(item.config_snapshot)
        assert value not in client.get(f"/requests/{item.id}").get_data(as_text=True)
        foreman = ForemanClient()
        foreman.mock = False
        foreman.resolve_template_id = lambda _: "42"
        payload = {}
        foreman._request = lambda method, path, **kw: payload.update(kw["json"]) or {"id": 1}
        foreman.create_job(item.config_snapshot, item.target_snapshot, item.form_data)
        assert payload["job_invocation"]["inputs"]["secret_ref"] == ref
        assert value not in json.dumps(payload)
    assert calls[0][1]["json"] == {"data": {"secret": value}}
    assert value not in calls[0][0]


def test_invalid_secret_is_not_echoed_or_sent_to_vault(app, client, monkeypatch):
    secret_chiklet(app)
    post = Mock()
    monkeypatch.setattr("app.secrets.requests.post", post)
    login(client, "alice")
    with app.app_context():
        server_id = db.session.scalar(db.select(Server).where(Server.name == "demo01")).id
    response = client.post("/requests/submit/sensitive-test", data={"server_id": server_id,
        "field__secret": "short", "field__application": "payments-api", "field__version": "1.0"})
    assert response.status_code == 400
    assert b"short" not in response.data
    post.assert_not_called()


def test_missing_vault_configuration_fails_closed(app, client):
    secret_chiklet(app)
    app.config.update(VAULT_ADDR="", VAULT_TOKEN="")
    login(client, "alice")
    with app.app_context():
        server_id = db.session.scalar(db.select(Server).where(Server.name == "demo01")).id
    response = client.post("/requests/submit/sensitive-test", data={"server_id": server_id,
        "field__secret": "some-secret-password", "field__application": "payments-api", "field__version": "1.0"})
    assert response.status_code == 503
    assert b"some-secret-password" not in response.data
    with app.app_context():
        assert db.session.scalar(db.select(DeploymentRequest).where(DeploymentRequest.chiklet_id == "sensitive-test")) is None
