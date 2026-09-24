from conftest import login
from app.extensions import db
from app.models import DeploymentRequest,Server,User
def test_requester_cannot_self_approve_even_if_approver(app,client):
    with app.app_context():
        u=db.session.scalar(db.select(User).where(User.username=="alice")); u.role="approver"; u.approval_groups=list(u.server_groups); s=db.session.scalar(db.select(Server).where(Server.name=="demo01"))
        item=DeploymentRequest(request_number="REQ-TEST",requested_by_id=u.id,chiklet_id="x",chiklet_name="X",chiklet_version="1",server_group_id=s.group_id,status="pending_approval",form_data={},config_snapshot={},target_snapshot={"name":s.name}); db.session.add(item); db.session.commit(); rid=item.id
    login(client,"alice"); assert client.post(f"/approvals/{rid}/approve",data={"comment":"x"}).status_code==403
