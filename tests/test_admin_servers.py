from conftest import login
from app.extensions import db
from app.models import Server, ServerGroup, User


def test_servers_live_on_a_separate_admin_page(app, client):
    login(client, "root")
    admin_page = client.get("/admin/")
    assert admin_page.status_code == 200
    assert b"View servers" in admin_page.data
    assert b"<h2>Servers</h2>" not in admin_page.data
    page = client.get("/admin/servers")
    assert page.status_code == 200
    assert b"demo01" in page.data and b"secret01" in page.data
    assert b"Sync Foreman hosts" in page.data
    assert b"2 servers found" in page.data
    login(client, "alice")
    assert client.get("/admin/servers").status_code == 403


def test_server_search_and_filters_use_the_database(app, client):
    with app.app_context():
        demo = db.session.scalar(db.select(Server).where(Server.name == "demo01"))
        secret = db.session.scalar(db.select(Server).where(Server.name == "secret01"))
        demo.ip_address = "10.20.30.40"
        demo.foreman_host_id = 31415
        demo.environment = "Production"
        secret.environment = "Test"
        secret.enabled = False
        demo_group = demo.group_id
        db.session.commit()
    login(client, "root")
    for query in ("q=DEM", "q=10.20.30", "q=31415", f"group_id={demo_group}",
                  "environment=Production", "status=enabled"):
        result = client.get("/admin/servers?" + query)
        assert b"demo01" in result.data and b"secret01" not in result.data
    disabled = client.get("/admin/servers?status=disabled")
    assert b"secret01" in disabled.data and b"demo01" not in disabled.data
    empty = client.get("/admin/servers?q=missing")
    assert b"No servers found" in empty.data and b"0 servers found" in empty.data
    assert client.get("/admin/servers?group_id=invalid").status_code == 400


def test_paginated_servers_include_records_beyond_previous_limit(app, client):
    with app.app_context():
        group = db.session.scalar(db.select(ServerGroup).where(ServerGroup.slug == "demo"))
        db.session.add_all(Server(foreman_host_id=1000+i, name=f"host{i:04d}", group_id=group.id)
                           for i in range(501))
        db.session.commit()
    login(client, "root")
    first = client.get("/admin/servers")
    assert b"503 servers found" in first.data
    assert b"Page 1 of 21" in first.data
    assert b"host0000" in first.data and b"host0499" not in first.data
    last = client.get("/admin/servers?page=21")
    assert b"host0500" in last.data and b"Page 21 of 21" in last.data


def test_editing_server_preserves_filtered_page(app, client):
    with app.app_context():
        server = db.session.scalar(db.select(Server).where(Server.name == "demo01"))
        secret = db.session.scalar(db.select(ServerGroup).where(ServerGroup.slug == "secret"))
        approver = db.session.scalar(db.select(User).where(User.username == "approver"))
        server_id, group_id, owner_id = server.id, secret.id, approver.id
    login(client, "root")
    owner = client.post(f"/admin/servers/{server_id}/owners", data={
        "technical_owner_id": str(owner_id), "business_owner_id": str(owner_id),
        "filter_q": "demo", "filter_status": "enabled", "page": "2",
    })
    assert owner.status_code == 302
    assert "q=demo" in owner.location and "status=enabled" in owner.location
    assert "page=2" in owner.location
    changed = client.post(f"/admin/servers/{server_id}/group", data={
        "group_id": str(group_id), "filter_group_id": str(group_id), "page": "1",
    })
    assert changed.status_code == 302
    assert f"group_id={group_id}" in changed.location
    with app.app_context():
        server = db.session.get(Server, server_id)
        assert server.technical_owner_id == owner_id
        assert server.business_owner_id == owner_id
        assert server.group_id == group_id
