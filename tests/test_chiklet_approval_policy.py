import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.catalog.service import ChikletError, _validate_definition
from app.extensions import db
from app.models import AuthIdentity, DeploymentRequest, Server, User
from conftest import login


def configure(app, *, approval="none", binding=None):
    path = Path(app.config["CHIKLET_DIRECTORY"], "deploy-web-application.json")
    data = json.loads(path.read_text())
    data["approval"] = {"mode": approval}
    if binding:
        data["identity_binding"] = {"username_field": "account_username", "providers": ["ldap", "entra"]}
        data["form_schema"]["properties"]["account_username"] = {"type": "string", "title": "Account username"}
        data["form_schema"]["required"].append("account_username")
        data["foreman"]["input_map"]["account_username"] = "account_username"
    path.write_text(json.dumps(data))
    return data


def test_no_approval_queues_without_server_owner(app, client, monkeypatch):
    configure(app)
    delay = Mock()
    monkeypatch.setattr("app.jobs.tasks.execute_request.delay", delay)
    with app.app_context():
        server = db.session.scalar(db.select(Server).where(Server.name == "demo01"))
        server.technical_owner_id = None
        db.session.commit()
        server_id = server.id
    login(client, "alice")
    response = client.post("/requests/submit/deploy-web-application", data={
        "server_id": server_id, "field__application": "payments-api", "field__version": "1.2.3"})
    assert response.status_code == 302
    with app.app_context():
        item = db.session.scalar(db.select(DeploymentRequest))
        assert item.status == "approved"
        assert item.execution.status == "queued"
        assert item.approved_at is not None
        assert not item.approvals
        delay.assert_called_once_with(item.id)
        assert b"Approval not required" in client.get(f"/requests/{item.id}").data


@pytest.mark.parametrize("provider,username", [("ldap", "directory-alice"), ("entra", "alice@company.example")])
def test_authenticated_username_cannot_be_replaced_by_form_or_other_identity(app, client, monkeypatch, provider, username):
    configure(app, binding=True)
    monkeypatch.setattr("app.jobs.tasks.execute_request.delay", Mock())
    with app.app_context():
        alice = db.session.scalar(db.select(User).where(User.username == "alice"))
        bob = db.session.scalar(db.select(User).where(User.username == "approver"))
        own = AuthIdentity(user=alice, provider=provider, subject=f"subject-{provider}", authenticated_username=username)
        other = AuthIdentity(user=bob, provider=provider, subject=f"other-{provider}", authenticated_username="victim")
        db.session.add_all([own, other])
        db.session.commit()
        own_id, other_id = own.id, other.id
        server_id = db.session.scalar(db.select(Server).where(Server.name == "demo01")).id
    login(client, "alice")
    payload = {"server_id": server_id, "field__application": "payments-api", "field__version": "1.2.3",
               "field__account_username": "victim"}
    assert client.post("/requests/submit/deploy-web-application", data=payload).status_code == 403
    with client.session_transaction() as session:
        session["authenticated_identity_id"] = other_id
    assert client.post("/requests/submit/deploy-web-application", data=payload).status_code == 403
    with client.session_transaction() as session:
        session["authenticated_identity_id"] = own_id
    detail = client.get("/chiklets/deploy-web-application")
    assert username.encode() in detail.data
    assert b'name="field__account_username"' not in detail.data
    assert client.post("/requests/submit/deploy-web-application", data=payload).status_code == 302
    with app.app_context():
        item = db.session.scalar(db.select(DeploymentRequest))
        assert item.form_data["account_username"] == username
        assert item.submitted_form_data["account_username"] == username
        assert item.execution is not None


def test_invalid_approval_and_unmapped_binding_are_rejected(app):
    data = configure(app, binding=True)
    data["approval"]["mode"] = "bypass"
    with pytest.raises(ChikletError):
        _validate_definition(data)
    data["approval"]["mode"] = "one_stage"
    with pytest.raises(ChikletError):
        _validate_definition(data)
    data["approval"]["mode"] = "none"
    data["foreman"]["input_map"].pop("account_username")
    with pytest.raises(ChikletError):
        _validate_definition(data)


def test_business_only_queues_after_assigned_business_owner_approval(app, client, monkeypatch):
    configure(app, approval="business")
    delay = Mock()
    monkeypatch.setattr("app.jobs.tasks.execute_request.delay", delay)
    with app.app_context():
        from app.auth.services import set_local_password
        business = User(username="business", display_name="Business Owner", role="user")
        set_local_password(business, "correct horse battery staple")
        db.session.add(business)
        db.session.flush()
        server = db.session.scalar(db.select(Server).where(Server.name == "demo01"))
        server.business_owner_id = business.id
        db.session.commit()
        server_id = server.id
    login(client, "alice")
    result = client.post("/requests/submit/deploy-web-application", data={
        "server_id": server_id, "field__application": "payments-api", "field__version": "1.2.3"})
    assert result.status_code == 302
    with app.app_context():
        item = db.session.scalar(db.select(DeploymentRequest))
        request_id = item.id
        assert item.status == "pending_approval" and item.execution is None
    delay.assert_not_called()
    assert client.post(f"/approvals/{request_id}/approve").status_code == 403
    login(client, "approver")  # Assigned technical owner cannot act for the business owner.
    assert client.post(f"/approvals/{request_id}/approve").status_code == 403
    login(client, "linuxadmin")
    assert client.post(f"/approvals/{request_id}/approve").status_code == 403
    login(client, "business")
    assert b"Approve &amp; queue Foreman job" in client.get(f"/approvals/{request_id}/review").data
    assert client.post(f"/approvals/{request_id}/approve", data={
        "override_fields": ["version"], "field__version": "2.0.0"}).status_code == 400
    assert client.post(f"/approvals/{request_id}/approve").status_code == 302
    with app.app_context():
        item = db.session.get(DeploymentRequest, request_id)
        assert item.status == "approved" and item.execution.status == "queued"
        assert [(a.stage, a.decision) for a in item.approvals] == [("business", "approved")]
        assert item.form_data["version"] == "1.2.3"
    delay.assert_called_once_with(request_id)


def test_business_only_rejection_and_missing_owner_never_queue(app, client, monkeypatch):
    configure(app, approval="business")
    delay = Mock()
    monkeypatch.setattr("app.jobs.tasks.execute_request.delay", delay)
    with app.app_context():
        server_id = db.session.scalar(db.select(Server).where(Server.name == "demo01")).id
    login(client, "alice")
    payload = {"server_id": server_id, "field__application": "payments-api", "field__version": "1.2.3"}
    assert client.post("/requests/submit/deploy-web-application", data=payload).status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(DeploymentRequest)) is None
        server = db.session.get(Server, server_id)
        server.business_owner_id = db.session.scalar(db.select(User).where(User.username == "approver")).id
        db.session.commit()
    assert client.post("/requests/submit/deploy-web-application", data=payload).status_code == 302
    with app.app_context():
        request_id = db.session.scalar(db.select(DeploymentRequest)).id
    login(client, "approver")
    assert client.post(f"/approvals/{request_id}/reject", data={"comment": "Declined"}).status_code == 302
    with app.app_context():
        item = db.session.get(DeploymentRequest, request_id)
        assert item.status == "rejected" and item.execution is None
        assert item.approvals[0].stage == "business"
    delay.assert_not_called()


def test_entra_claim_is_preserved_and_refreshed_on_signin(app, client, monkeypatch):
    from app.auth.services import complete_entra_flow
    msal = Mock()
    msal.acquire_token_by_auth_code_flow.return_value = {
        "id_token_claims": {"oid": "stable-oid", "preferred_username": "original@company.example"}}
    monkeypatch.setattr("app.auth.services._msal_app", lambda: msal)
    app.config["ENTRA_AUTO_PROVISION"] = True
    with client.session_transaction() as session:
        session["entra_flow"] = {"state": "test"}
    with app.app_context(), app.test_request_context():
        user, error = complete_entra_flow({"state": "test"})
        assert not error
        db.session.commit()
        ident = db.session.scalar(db.select(AuthIdentity).where(AuthIdentity.provider == "entra"))
        assert ident.authenticated_username == "original@company.example"
        msal.acquire_token_by_auth_code_flow.return_value["id_token_claims"]["preferred_username"] = "renamed@company.example"
        user, error = complete_entra_flow({"state": "test"})
        db.session.commit()
        assert not error
        assert user.id == ident.user_id
        assert ident.authenticated_username == "renamed@company.example"


def test_ldap_username_attribute_is_preserved_on_signin(app, monkeypatch):
    from app.auth.services import authenticate_ldap
    entry = Mock(entry_dn="cn=alice,dc=example")
    entry.__getitem__ = Mock(side_effect=lambda key: Mock(value={
        "uid": "directory-alice", "mail": "alice@example.com", "cn": "Alice"}[key]))
    service = Mock(entries=[entry], search=Mock(return_value=True), server=Mock())
    monkeypatch.setattr("app.auth.services._ldap_service_connection", lambda: service)
    monkeypatch.setattr("app.auth.services.Connection", lambda *args, **kwargs: Mock())
    app.config.update(LDAP_USERNAME_ATTRIBUTE="uid", LDAP_EMAIL_ATTRIBUTE="mail",
                      LDAP_DISPLAYNAME_ATTRIBUTE="cn", LDAP_AUTO_PROVISION=True)
    with app.test_request_context(), app.app_context():
        user, error = authenticate_ldap("alias", "valid-password")
        assert not error
        db.session.commit()
        ident = db.session.scalar(db.select(AuthIdentity).where(AuthIdentity.provider == "ldap"))
        assert user.username == "directory-alice"
        assert ident.authenticated_username == "directory-alice"
