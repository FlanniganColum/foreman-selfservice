from app.extensions import db
from app.models import Server
from conftest import login


def test_form_validation_links_to_field_without_losing_other_values(app, client):
    login(client, "alice")
    with app.app_context():
        server_id = db.session.scalar(db.select(Server).where(Server.name == "demo01")).id
    response = client.post("/requests/submit/deploy-web-application", data={
        "server_id": server_id,
        "field__application": "payments-api",
        "field__version": "",
        "field__environment": "Production",
    })
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert 'data-form-error-summary' in html
    assert 'href="#field__version"' in html
    assert 'id="field__version"' in html
    assert 'aria-invalid="true"' in html
    assert 'id="field__version-error"' in html
    assert 'value="Production" selected' in html


def test_keyboard_navigation_and_current_page_are_exposed(client):
    login(client, "alice")
    html = client.get("/").get_data(as_text=True)
    assert 'href="#main-content"' in html
    assert 'id="main-content"' in html
    assert 'aria-label="Primary"' in html
    assert 'aria-current="page"' in html
    assert '/static/css/ux.css' in html
