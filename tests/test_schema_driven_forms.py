import json
from copy import deepcopy
from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict

from conftest import login
from app.catalog.service import ChikletError, _validate_definition, validate_form
from app.extensions import db
from app.models import DeploymentRequest, Server


def _schema_chiklet(app):
    with app.app_context():
        base = Path(app.config["CHIKLET_DIRECTORY"])
        data = json.loads((base / "deploy-web-application.json").read_text(encoding="utf-8"))
        data["id"] = "schema-ui-test"
        data["name"] = "Schema UI Test"
        data["form_schema"] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "package": {
                    "type": "string",
                    "title": "Package",
                    "enum": ["v1", "v2"],
                    "default": "v2",
                    "description": "Choose the package version.",
                    "x-ui": {"group": "Package settings", "order": 10, "width": "half"},
                },
                "state": {
                    "type": "string",
                    "title": "Package state",
                    "enum": ["present", "latest"],
                    "default": "present",
                    "x-ui": {
                        "group": "Package settings",
                        "order": 20,
                        "width": "half",
                        "enum_labels": {"present": "Installed", "latest": "Latest available"},
                    },
                },
                "restart": {
                    "type": "boolean",
                    "title": "Restart service",
                    "default": True,
                    "x-ui": {"group": "Runtime", "widget": "toggle"},
                },
                "workers": {
                    "type": "integer",
                    "title": "Worker count",
                    "default": 4,
                    "minimum": 1,
                    "maximum": 32,
                    "x-ui": {"group": "Runtime", "width": "half"},
                },
                "notes": {
                    "type": "string",
                    "title": "Deployment notes",
                    "default": "",
                    "x-ui": {"group": "Runtime", "widget": "textarea", "rows": 6},
                },
                "repository": {
                    "type": "string",
                    "title": "Repository",
                    "default": "approved-production-repo",
                    "readOnly": True,
                    "x-ui": {"group": "Policy"},
                },
            },
            "required": ["package", "state", "workers"],
            "additionalProperties": False,
        }
        data["foreman"] = {
            "job_template_name": "SelfService - Schema UI Test",
            "input_map": {
                "package_name": "package",
                "package_state": "state",
                "restart_service": "restart",
                "worker_count": "workers",
                "deployment_notes": "notes",
                "repository": "repository",
            },
        }
        (base / "schema-ui-test.json").write_text(json.dumps(data), encoding="utf-8")
        return data


def test_schema_renders_editable_controls_and_fixed_values(app, client):
    _schema_chiklet(app)
    login(client, "alice")
    response = client.get("/chiklets/schema-ui-test")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="field__package"' in html
    assert '<option value="v2" selected>v2</option>' in html
    assert 'Latest available' in html
    assert 'name="field__restart"' in html
    assert 'name="field__workers"' in html
    assert 'type="number"' in html
    assert 'name="field__notes"' in html
    assert '<textarea' in html
    assert 'approved-production-repo' in html
    assert 'Fixed' in html


def test_schema_submission_persists_user_selected_values(app, client):
    _schema_chiklet(app)
    login(client, "alice")
    with app.app_context():
        server_id = db.session.scalar(db.select(Server).where(Server.name == "demo01")).id

    response = client.post(
        "/requests/submit/schema-ui-test",
        data={
            "server_id": server_id,
            "field__package": "v1",
            "field__state": "latest",
            "field__workers": "12",
            "field__notes": "Custom deployment",
            "field__repository": "tampered-repo",
            "justification": "CHG-1234",
        },
    )
    assert response.status_code == 302

    with app.app_context():
        item = db.session.scalar(db.select(DeploymentRequest).where(DeploymentRequest.chiklet_id == "schema-ui-test"))
        assert item.form_data["package"] == "v1"
        assert item.form_data["state"] == "latest"
        assert item.form_data["restart"] is False
        assert item.form_data["workers"] == 12
        assert item.form_data["notes"] == "Custom deployment"
        # Browser tampering cannot override a fixed/readOnly JSON value.
        assert item.form_data["repository"] == "approved-production-repo"


def test_schema_rejects_enum_value_not_allowed_by_chiklet(app):
    chiklet = _schema_chiklet(app)
    form = MultiDict({
        "field__package": "malicious-package",
        "field__state": "present",
        "field__workers": "4",
    })
    data, errors = validate_form(chiklet, form)
    assert data["package"] == "malicious-package"
    assert any("is not one of" in error for error in errors)


def test_input_map_must_reference_real_schema_fields(app):
    chiklet = _schema_chiklet(app)
    broken = deepcopy(chiklet)
    broken["foreman"]["input_map"]["bad_foreman_input"] = "does_not_exist"
    with pytest.raises(ChikletError, match="does_not_exist"):
        _validate_definition(broken, "broken.json")


def test_foreman_input_map_uses_customised_form_values(app):
    from app.foreman.client import ForemanClient

    chiklet = _schema_chiklet(app)
    submitted = {
        "package": "v1",
        "state": "latest",
        "restart": False,
        "workers": 12,
        "notes": "Custom deployment",
        "repository": "approved-production-repo",
    }

    with app.app_context():
        client = ForemanClient()
        client.mock = False
        client.resolve_template_id = lambda cfg: "245"
        captured = {}

        def fake_request(method, path, **kwargs):
            captured["method"] = method
            captured["path"] = path
            captured["payload"] = kwargs["json"]
            return {"id": 999, "status_label": "queued"}

        client._request = fake_request
        client.create_job(
            chiklet,
            {"name": "demo01", "foreman_host_id": 1},
            submitted,
            correlation_id="REQ-TEST",
        )

    inputs = captured["payload"]["job_invocation"]["inputs"]
    assert inputs == {
        "package_name": "v1",
        "package_state": "latest",
        "restart_service": False,
        "worker_count": 12,
        "deployment_notes": "Custom deployment",
        "repository": "approved-production-repo",
    }
