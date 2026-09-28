from conftest import login
from app.extensions import db
from app.models import AuditEvent, AuthIdentity, DeploymentRequest, User


def test_profile_shows_own_access_and_requests(app, client):
    login(client, "alice")
    with app.app_context():
        alice = db.session.scalar(db.select(User).where(User.username == "alice"))
        db.session.add(DeploymentRequest(
            request_number="REQ-ALICE", requested_by_id=alice.id,
            chiklet_id="example", chiklet_name="Alice's request", chiklet_version="1",
            server_group_id=alice.server_groups[0].id, form_data={},
            config_snapshot={}, target_snapshot={}, status="queued"))
        approver = db.session.scalar(db.select(User).where(User.username == "approver"))
        db.session.add(DeploymentRequest(
            request_number="REQ-OTHER", requested_by_id=approver.id,
            chiklet_id="example", chiklet_name="Another person's request", chiklet_version="1",
            server_group_id=alice.server_groups[0].id, form_data={},
            config_snapshot={}, target_snapshot={}, status="queued"))
        db.session.commit()
    result = client.get("/auth/profile")
    assert result.status_code == 200
    assert b"My profile" in result.data
    assert b"Local account" in result.data
    assert b"Demo" in result.data
    assert b"Change password" in result.data
    assert b"REQ-ALICE" in result.data
    assert b"REQ-OTHER" not in result.data


def test_local_profile_edit_is_limited_to_own_contact_details(app, client):
    login(client, "alice")
    response = client.post("/auth/profile", data={
        "display_name": "  Alice Example  ", "email": "alice@example.com",
        "username": "approver", "user_id": "2", "role": "global_admin",
        "server_groups": "secret",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Your profile was updated." in response.data
    with app.app_context():
        alice = db.session.scalar(db.select(User).where(User.username == "alice"))
        approver = db.session.scalar(db.select(User).where(User.username == "approver"))
        assert alice.display_name == "Alice Example"
        assert alice.email == "alice@example.com"
        assert alice.role == "user" and [g.slug for g in alice.server_groups] == ["demo"]
        assert approver.display_name == "Approver" and approver.email is None
        event = db.session.scalar(db.select(AuditEvent).where(AuditEvent.event_type == "PROFILE_UPDATED"))
        assert event.actor_user_id == alice.id and event.entity_id == str(alice.id)
        assert event.details == {"changed_fields": ["display_name", "email"]}


def test_invalid_profile_edit_keeps_existing_details(app, client):
    login(client, "alice")
    response = client.post("/auth/profile", data={"display_name": " ", "email": "invalid"})
    assert response.status_code == 400
    assert b"Check your details" in response.data
    assert b'aria-invalid="true"' in response.data
    with app.app_context():
        alice = db.session.scalar(db.select(User).where(User.username == "alice"))
        assert alice.display_name == "Alice" and alice.email is None
        assert db.session.scalar(db.select(AuditEvent).where(AuditEvent.event_type == "PROFILE_UPDATED")) is None


def test_directory_profiles_are_read_only_even_with_a_local_credential(app, client):
    login(client, "alice")
    with app.app_context():
        alice = db.session.scalar(db.select(User).where(User.username == "alice"))
        identity = AuthIdentity(user_id=alice.id, provider="ldap", subject="alice-dn",
                                authenticated_username="alice.directory")
        db.session.add(identity)
        db.session.commit()
        identity_id = identity.id
    with client.session_transaction() as session:
        session["auth_provider"] = "ldap"
        session["authenticated_identity_id"] = identity_id
    response = client.get("/auth/profile")
    assert response.status_code == 200
    assert b"LDAP directory" in response.data
    assert b"alice.directory" in response.data
    assert b"identity provider" in response.data
    assert b"Save contact details" not in response.data
    assert b"Change password" not in response.data
    assert client.post("/auth/profile", data={"display_name": "Wrong", "email": "wrong@example.com"}).status_code == 403
    with app.app_context():
        assert db.session.scalar(db.select(User).where(User.username == "alice")).display_name == "Alice"


def test_profile_requires_authentication_and_local_edit_setting(app, client):
    assert client.get("/auth/profile").status_code == 302
    login(client, "alice")
    app.config["ENABLE_LOCAL"] = False
    assert b"Save contact details" not in client.get("/auth/profile").data
    assert client.post("/auth/profile", data={"display_name": "Wrong"}).status_code == 403
