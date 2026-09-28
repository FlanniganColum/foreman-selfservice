import json
from pathlib import Path

from conftest import login


def test_catalog_search_and_category_use_only_authorised_chiklets(app, client):
    base = Path(app.config["CHIKLET_DIRECTORY"])
    original = json.loads((base / "deploy-web-application.json").read_text())
    db = dict(original, id="database-task", name="Install Database Driver",
              description="ODBC connectivity", category="Database")
    hidden = dict(original, id="secret-os-task", name="Secret Linux Task",
                  category="Operating System", allowed_server_groups=["secret"])
    (base / "database-task.json").write_text(json.dumps(db))
    (base / "secret-os-task.json").write_text(json.dumps(hidden))

    login(client, "alice")
    page = client.get("/")
    assert b"Install Database Driver" in page.data
    assert b"Secret Linux Task" not in page.data
    assert b"Operating System" not in page.data

    page = client.get("/?q=odbc&category=Database")
    assert b"Install Database Driver" in page.data
    assert b"Deploy Web Application" not in page.data
    assert b"1 of 2 available applications" in page.data

    page = client.get("/?q=secret+linux")
    assert b"No matching applications" in page.data
    assert b"Secret Linux Task" not in page.data
