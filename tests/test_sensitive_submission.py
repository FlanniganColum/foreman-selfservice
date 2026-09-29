import json
from pathlib import Path

from conftest import login
from app.extensions import db
from app.models import AuditEvent, DeploymentRequest, Server
from app.sensitive import PREFIX, SensitiveDataError, protect_fields, reveal_fields


def secret_chiklet(app):
    data = json.loads(Path("chiklets/deploy-web-application.json").read_text())
    data["id"] = "sensitive-test"
    data["form_schema"]["properties"]["secret"] = {
        "type": "string", "title": "Password", "minLength": 8,
        "x-sensitive": True, "x-ui": {"widget": "password"},
    }
    data["form_schema"]["required"].append("secret")
    data["foreman"]["input_map"]["password"] = "secret"
    Path(app.config["CHIKLET_DIRECTORY"], "sensitive-test.json").write_text(json.dumps(data))
    return data


def test_secret_is_encrypted_in_portal_and_sent_in_foreman_api_input(app, client):
    from app.foreman.client import ForemanClient
    secret_chiklet(app)
    login(client, "alice")
    with app.app_context():
        server_id = db.session.scalar(db.select(Server).where(Server.name == "demo01")).id
    value = "very-private-password"
    response = client.post("/requests/submit/sensitive-test", data={"server_id": server_id,
        "field__secret": value, "field__application": "payments-api", "field__version": "1.0"})
    assert response.status_code == 302
    with app.app_context():
        item = db.session.scalar(db.select(DeploymentRequest).where(DeploymentRequest.chiklet_id == "sensitive-test"))
        assert item.form_data["secret"].startswith(PREFIX)
        assert value not in json.dumps(item.form_data)
        assert value not in json.dumps(item.submitted_form_data)
        assert value not in client.get(f"/requests/{item.id}").get_data(as_text=True)
        assert all(value not in json.dumps(event.details) for event in db.session.scalars(db.select(AuditEvent)))
        foreman = ForemanClient()
        foreman.mock = False
        foreman.resolve_template_id = lambda _: "42"
        payload = {}
        foreman._request = lambda method, path, **kw: payload.update(kw["json"]) or {"id": 1}
        foreman.create_job(item.config_snapshot, item.target_snapshot, item.form_data)
        assert payload["job_invocation"]["inputs"]["password"] == value


def test_invalid_secret_is_not_echoed_or_queued(app, client):
    secret_chiklet(app)
    login(client, "alice")
    with app.app_context():
        server_id = db.session.scalar(db.select(Server).where(Server.name == "demo01")).id
    response = client.post("/requests/submit/sensitive-test", data={"server_id": server_id,
        "field__secret": "short", "field__application": "payments-api", "field__version": "1.0"})
    assert response.status_code == 400
    assert b"short" not in response.data
    with app.app_context():
        assert db.session.scalar(db.select(DeploymentRequest).where(DeploymentRequest.chiklet_id == "sensitive-test")) is None


def test_sensitive_inputs_require_verified_https(app):
    from app.foreman.client import ForemanClient, ForemanError
    config = secret_chiklet(app)
    with app.app_context():
        foreman = ForemanClient()
        foreman.mock = False
        foreman.verify = False
        try:
            foreman.create_job(config, {"name": "demo01"}, {"secret": "enc-v1:unreadable"})
        except ForemanError as exc:
            assert "verified HTTPS" in str(exc)
        else:
            raise AssertionError("Sensitive input was sent without verified TLS")


def test_weak_key_fails_closed_for_sensitive_fields(app, client):
    secret_chiklet(app)
    app.config["SECRET_KEY"] = "CHANGE-ME"
    login(client, "alice")
    with app.app_context():
        server_id = db.session.scalar(db.select(Server).where(Server.name == "demo01")).id
    response = client.post("/requests/submit/sensitive-test", data={"server_id": server_id,
        "field__secret": "some-secret-password", "field__application": "payments-api", "field__version": "1.0"})
    assert response.status_code == 503
    assert b"some-secret-password" not in response.data
    with app.app_context():
        assert db.session.scalar(db.select(DeploymentRequest).where(DeploymentRequest.chiklet_id == "sensitive-test")) is None


def test_ciphertext_cannot_be_decrypted_with_a_different_key():
    first = "first sufficiently long application key 2026"
    second = "second sufficiently long application key 2026"
    protected = protect_fields({"password": "private-value"}, {"password"}, first)
    assert reveal_fields(protected, {"password"}, first)["password"] == "private-value"
    try:
        reveal_fields(protected, {"password"}, second)
    except SensitiveDataError:
        pass
    else:
        raise AssertionError("A different key decrypted a sensitive input")
