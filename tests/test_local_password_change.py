from conftest import login
from app.extensions import db
from app.models import AuditEvent, User
from app.auth.services import ph


def test_local_user_can_change_only_their_own_password(app, client):
    login(client, "alice")
    assert b"Change password" in client.get("/").data
    assert client.get("/auth/password").status_code == 200

    result = client.post("/auth/password", data={
        "current_password": "correct horse battery staple",
        "new_password": "a completely different password 2026",
        "confirm_password": "a completely different password 2026",
        "user_id": "2", "username": "approver",
    }, follow_redirects=True)
    assert result.status_code == 200
    assert b"Sign in again with your new password" in result.data
    assert client.get("/auth/password").status_code == 302
    with app.app_context():
        alice = db.session.scalar(db.select(User).where(User.username == "alice"))
        approver = db.session.scalar(db.select(User).where(User.username == "approver"))
        assert ph.verify(alice.local_credential.password_hash, "a completely different password 2026")
        assert ph.verify(approver.local_credential.password_hash, "correct horse battery staple")
        assert alice.local_credential.password_changed_at is not None
        event = db.session.scalar(db.select(AuditEvent).where(AuditEvent.event_type == "LOCAL_PASSWORD_CHANGED"))
        assert event.actor_user_id == alice.id and event.entity_id == str(alice.id)
        assert "password" not in str(event.details).lower()

    assert client.post("/auth/local", data={"username": "alice", "password": "correct horse battery staple"},
                       follow_redirects=True).status_code == 200
    assert client.get("/auth/password").status_code == 302
    assert client.post("/auth/local", data={"username": "alice", "password": "a completely different password 2026"},
                       follow_redirects=True).status_code == 200
    assert client.get("/auth/password").status_code == 200


def test_wrong_current_password_and_invalid_new_password_do_not_change_hash(app, client):
    login(client, "alice")
    with app.app_context():
        alice = db.session.scalar(db.select(User).where(User.username == "alice"))
        original_hash = alice.local_credential.password_hash

    for payload in [
        {"current_password": "wrong", "new_password": "a correct new password", "confirm_password": "a correct new password"},
        {"current_password": "correct horse battery staple", "new_password": "too short", "confirm_password": "too short"},
        {"current_password": "correct horse battery staple", "new_password": "a correct new password", "confirm_password": "another good password"},
        {"current_password": "correct horse battery staple", "new_password": "correct horse battery staple", "confirm_password": "correct horse battery staple"},
    ]:
        result = client.post("/auth/password", data=payload, follow_redirects=True)
        assert result.status_code == 200
        assert payload["new_password"].encode() not in result.data

    with app.app_context():
        alice = db.session.scalar(db.select(User).where(User.username == "alice"))
        assert alice.local_credential.password_hash == original_hash
        assert alice.local_credential.failed_attempts == 1
        assert db.session.scalar(db.select(AuditEvent).where(AuditEvent.event_type == "LOCAL_PASSWORD_CHANGE_FAILED"))
        assert db.session.scalar(db.select(AuditEvent).where(AuditEvent.event_type == "LOCAL_PASSWORD_CHANGED")) is None


def test_local_change_requires_local_authentication_and_an_existing_credential(app, client):
    assert client.get("/auth/password").status_code == 302
    login(client, "alice")
    with client.session_transaction() as session:
        session["auth_provider"] = "entra"
    assert client.get("/auth/password").status_code == 403
    assert client.post("/auth/password", data={"current_password": "correct horse battery staple",
        "new_password": "a new strong password 2026", "confirm_password": "a new strong password 2026"}).status_code == 403
    login(client, "alice")
    app.config["ENABLE_LOCAL"] = False
    assert client.get("/auth/password").status_code == 403
    app.config["ENABLE_LOCAL"] = True
    with app.app_context():
        alice = db.session.scalar(db.select(User).where(User.username == "alice"))
        db.session.delete(alice.local_credential)
        db.session.commit()
    assert client.get("/auth/password").status_code == 403
