import json
from pathlib import Path
from conftest import login
from app.extensions import db
from app.models import Server


def _install_wildcard_chiklet(app):
    with app.app_context():
        base=Path(app.config["CHIKLET_DIRECTORY"])
        source=json.loads((base/"deploy-web-application.json").read_text(encoding="utf-8"))
        source["id"]="wildcard-test"
        source["name"]="Wildcard Test"
        source["allowed_server_groups"]=["*"]
        source["icon"]={"type":"image","src":"test.svg","alt":"Test"}
        (base/"wildcard-test.json").write_text(json.dumps(source),encoding="utf-8")
        assets=base/"assets"
        assets.mkdir(exist_ok=True)
        (assets/"test.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>',encoding="utf-8")


def test_wildcard_chiklet_keeps_user_server_rbac(app,client):
    _install_wildcard_chiklet(app)
    login(client,"alice")
    response=client.get("/chiklets/wildcard-test")
    assert response.status_code==200
    assert b"demo01" in response.data
    assert b"secret01" not in response.data


def test_wildcard_chiklet_rejects_unauthorised_submission(app,client):
    _install_wildcard_chiklet(app)
    login(client,"alice")
    with app.app_context():
        secret_id=db.session.scalar(db.select(Server).where(Server.name=="secret01")).id
    response=client.post("/requests/submit/wildcard-test",data={
        "server_id":secret_id,
        "field__application":"payments-api",
        "field__version":"1.2.3",
        "field__environment":"UAT",
        "field__restart_service":"true",
        "field__healthcheck_path":"/health"
    })
    assert response.status_code==403


def test_hot_loaded_chiklet_asset_is_served(app,client):
    _install_wildcard_chiklet(app)
    login(client,"alice")
    response=client.get("/chiklet-assets/test.svg")
    assert response.status_code==200
    assert response.mimetype=="image/svg+xml"
    assert b"<svg" in response.data
    assert "no-cache" in response.headers.get("Cache-Control","")
