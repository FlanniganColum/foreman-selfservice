import json
from pathlib import Path
from unittest.mock import Mock

from conftest import login
from app.extensions import db
from app.models import Approval, AuditEvent, DeploymentRequest, JobExecution, Server, User


def submit(client, app, chiklet="deploy-web-application", **fields):
    with app.app_context():
        server_id = db.session.scalar(db.select(Server).where(Server.name == "demo01")).id
    login(client, "alice")
    data = {"server_id": server_id, "field__application": "payments-api",
            "field__version": "1.2.3", "field__environment": "UAT"}
    data.update(fields)
    response = client.post(f"/requests/submit/{chiklet}", data=data)
    assert response.status_code == 302
    with app.app_context():
        return db.session.scalar(db.select(DeploymentRequest).where(
            DeploymentRequest.chiklet_id == chiklet)).id


def test_owner_then_linux_approval_and_validated_override(app, client, monkeypatch):
    delay = Mock()
    monkeypatch.setattr("app.jobs.tasks.execute_request.delay", delay)
    chiklet_path = Path(app.config["CHIKLET_DIRECTORY"], "deploy-web-application.json")
    chiklet = json.loads(chiklet_path.read_text())
    chiklet["form_schema"]["properties"]["approved_repository"] = {
        "type": "string", "readOnly": True, "default": "approved"}
    chiklet_path.write_text(json.dumps(chiklet))
    request_id = submit(client, app)
    with app.app_context():
        item = db.session.get(DeploymentRequest, request_id)
        assert item.status == "pending_approval"
        assert item.execution is None
    login(client, "linuxadmin")
    assert client.post(f"/approvals/{request_id}/approve").status_code == 403
    login(client, "approver")
    assert client.get(f"/approvals/{request_id}/review").status_code == 200
    assert client.post(f"/approvals/{request_id}/approve").status_code == 302
    with app.app_context():
        item = db.session.get(DeploymentRequest, request_id)
        assert item.status == "pending_linux_approval"
        assert item.execution is None
        assert [(a.stage, a.decision) for a in item.approvals] == [("owner", "approved")]
    delay.assert_not_called()
    assert client.post(f"/approvals/{request_id}/approve").status_code == 403
    login(client, "root")
    assert client.post(f"/approvals/{request_id}/approve", data={
        "override_fields": ["approved_repository"], "field__approved_repository": "untrusted"}).status_code == 400
    login(client, "linuxadmin")
    assert client.post(f"/approvals/{request_id}/approve", data={
        "override_fields": ["version"], "field__version": ""}).status_code == 303
    with app.app_context():
        assert db.session.get(DeploymentRequest, request_id).status == "pending_linux_approval"
    assert client.post(f"/approvals/{request_id}/approve", data={
        "override_fields": ["version", "environment"], "field__version": "2.0.0",
        "field__environment": "Production", "comment": "Reviewed for production"}).status_code == 302
    with app.app_context():
        item = db.session.get(DeploymentRequest, request_id)
        assert item.status == "approved"
        assert item.form_data["version"] == "2.0.0"
        assert item.submitted_form_data["version"] == "1.2.3"
        assert item.execution.status == "queued"
        assert [(a.stage, a.decision) for a in item.approvals] == [
            ("owner", "approved"), ("linux", "approved")]
        event = db.session.scalar(db.select(AuditEvent).where(
            AuditEvent.event_type == "REQUEST_LINUX_APPROVED"))
        assert event.details["overridden_fields"] == ["environment", "version"]
        assert "2.0.0" not in json.dumps(event.details)
    delay.assert_called_once_with(request_id)
    assert client.post(f"/approvals/{request_id}/approve").status_code in {403, 409}


def test_owner_assigned_to_server_is_required_and_snapshotted(app, client):
    with app.app_context():
        server = db.session.scalar(db.select(Server).where(Server.name == "demo01"))
        server.technical_owner_id = None
        db.session.commit()
    login(client, "alice")
    with app.app_context():
        sid = db.session.scalar(db.select(Server).where(Server.name == "demo01")).id
    response = client.post("/requests/submit/deploy-web-application", data={
        "server_id": sid, "field__application": "payments-api", "field__version": "1.2.3"})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(DeploymentRequest)) is None
        server = db.session.get(Server, sid)
        server.technical_owner_id = db.session.scalar(db.select(User).where(User.username == "approver")).id
        db.session.commit()
    request_id = submit(client, app)
    with app.app_context():
        server = db.session.get(Server, sid)
        server.technical_owner_id = db.session.scalar(db.select(User).where(User.username == "linuxadmin")).id
        db.session.commit()
    login(client, "approver")
    assert client.post(f"/approvals/{request_id}/approve").status_code == 302


def test_linux_rejection_never_queues_job(app, client, monkeypatch):
    delay = Mock()
    monkeypatch.setattr("app.jobs.tasks.execute_request.delay", delay)
    request_id = submit(client, app)
    login(client, "approver")
    client.post(f"/approvals/{request_id}/approve")
    login(client, "linuxadmin")
    assert client.post(f"/approvals/{request_id}/reject", data={"comment": "Needs correction"}).status_code == 302
    with app.app_context():
        item = db.session.get(DeploymentRequest, request_id)
        assert item.status == "rejected"
        assert item.execution is None
        assert item.approvals[-1].stage == "linux"
    delay.assert_not_called()


def test_business_owner_without_approver_role_can_review_and_admin_can_assign(app, client):
    with app.app_context():
        user = User(username="business", role="user", display_name="Business Owner")
        from app.auth.services import set_local_password
        set_local_password(user, "correct horse battery staple")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        server_id = db.session.scalar(db.select(Server).where(Server.name == "demo01")).id
        linux_id = db.session.scalar(db.select(User).where(User.username == "linuxadmin")).id
    login(client, "root")
    page = client.get("/admin/servers")
    assert page.status_code == 200
    assert b"Business owner" in page.data
    assert client.post(f"/admin/servers/{server_id}/owners", data={
        "technical_owner_id": linux_id, "business_owner_id": user_id}).status_code == 302
    request_id = submit(client, app)
    login(client, "business")
    assert client.get("/approvals/").status_code == 200
    assert client.get(f"/requests/{request_id}").status_code == 200
    assert client.post(f"/approvals/{request_id}/approve").status_code == 302
    login(client, "linuxadmin")
    assert client.get(f"/approvals/{request_id}/review").status_code == 200


def test_same_linux_admin_cannot_approve_both_stages(app, client, monkeypatch):
    monkeypatch.setattr("app.jobs.tasks.execute_request.delay", Mock())
    with app.app_context():
        server = db.session.scalar(db.select(Server).where(Server.name == "demo01"))
        server.technical_owner_id = db.session.scalar(db.select(User).where(User.username == "linuxadmin")).id
        db.session.commit()
    request_id = submit(client, app)
    login(client, "linuxadmin")
    assert client.post(f"/approvals/{request_id}/approve").status_code == 302
    assert client.post(f"/approvals/{request_id}/approve").status_code == 403
    with app.app_context():
        assert db.session.get(DeploymentRequest, request_id).status == "pending_linux_approval"


def test_sensitive_linux_override_stores_only_a_new_vault_reference(app, client, monkeypatch):
    chiklet = json.loads(Path("chiklets/deploy-web-application.json").read_text())
    chiklet["id"] = "secret-approval"
    chiklet["form_schema"]["properties"]["password"] = {
        "type": "string", "minLength": 8, "x-sensitive": True, "x-ui": {"widget": "password"}}
    chiklet["form_schema"]["required"].append("password")
    chiklet["foreman"]["input_map"]["password_ref"] = "password"
    Path(app.config["CHIKLET_DIRECTORY"], "secret-approval.json").write_text(json.dumps(chiklet))
    app.config.update(VAULT_ADDR="https://vault.example.com", VAULT_TOKEN="test-token")
    writes = []
    def vault_post(url, **kwargs):
        writes.append(kwargs["json"]["data"])
        return Mock(raise_for_status=Mock())
    monkeypatch.setattr("app.secrets.requests.post", vault_post)
    monkeypatch.setattr("app.jobs.tasks.execute_request.delay", Mock())
    request_id = submit(client, app, "secret-approval", field__password="initial-secret-value")
    login(client, "approver")
    client.post(f"/approvals/{request_id}/approve")
    login(client, "linuxadmin")
    response = client.post(f"/approvals/{request_id}/approve", data={
        "override_fields": ["password"], "field__password": "replacement-secret-value"})
    assert response.status_code == 302
    with app.app_context():
        item = db.session.get(DeploymentRequest, request_id)
        assert item.submitted_form_data["password"] != item.form_data["password"]
        assert item.form_data["password"].startswith("vault-kv2://")
        assert "replacement-secret-value" not in json.dumps(item.form_data)
        assert "replacement-secret-value" not in client.get(f"/requests/{request_id}").get_data(as_text=True)
        assert all("replacement-secret-value" not in json.dumps(a.details) for a in db.session.scalars(db.select(AuditEvent)))
    assert writes == [{"password": "initial-secret-value"}, {"password": "replacement-secret-value"}]
