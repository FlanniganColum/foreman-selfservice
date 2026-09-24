from conftest import login
from app.extensions import db
from app.models import DeploymentRequest,Server
def test_submission_is_pending_approval(app,client):
    login(client,"alice")
    with app.app_context(): sid=db.session.scalar(db.select(Server).where(Server.name=="demo01")).id
    r=client.post("/requests/submit/deploy-web-application",data={"server_id":sid,"field__application":"payments-api","field__version":"1.2.3","field__environment":"UAT","field__restart_service":"true","field__healthcheck_path":"/health","justification":"CHG0001"})
    assert r.status_code==302
    with app.app_context():
        item=db.session.scalar(db.select(DeploymentRequest)); assert item.status=="pending_approval"; assert item.config_snapshot["id"]=="deploy-web-application"
