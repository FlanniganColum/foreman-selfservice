from flask import Blueprint,abort,flash,redirect,render_template,request,url_for
from flask_login import login_required,current_user
from ..extensions import db
from ..models import DeploymentRequest,Approval,JobExecution,RequestStatus,utcnow
from ..audit.service import audit
bp=Blueprint("approvals",__name__,url_prefix="/approvals")
def _require_approver(item):
    if current_user.role not in {"approver","admin","global_admin"}: abort(403)
    if not current_user.can_approve_group(item.server_group_id): abort(403)
    if item.requested_by_id==current_user.id: abort(403,"Separation of duties prevents self-approval")

@bp.get("/")
@login_required
def index():
    if current_user.role not in {"approver","admin","global_admin"}: abort(403)
    items=db.session.scalars(db.select(DeploymentRequest).where(DeploymentRequest.status==RequestStatus.PENDING_APPROVAL.value).order_by(DeploymentRequest.submitted_at.asc())).all()
    if current_user.role=="approver":
        gids={g.id for g in current_user.approval_groups}; items=[x for x in items if x.server_group_id in gids and x.requested_by_id!=current_user.id]
    return render_template("approvals/index.html",requests=items)

@bp.post("/<request_id>/approve")
@login_required
def approve(request_id):
    item=db.session.execute(db.select(DeploymentRequest).where(DeploymentRequest.id==request_id).with_for_update()).scalar_one_or_none()
    if not item: abort(404)
    _require_approver(item)
    if item.status!=RequestStatus.PENDING_APPROVAL.value: abort(409)
    item.status=RequestStatus.APPROVED.value; item.approved_at=utcnow()
    db.session.add(Approval(request=item,approver_id=current_user.id,decision="approved",comment=request.form.get("comment","").strip() or None))
    db.session.add(JobExecution(request=item,status=RequestStatus.QUEUED.value))
    audit("REQUEST_APPROVED",entity_type="deployment_request",entity_id=item.id,details={"request_number":item.request_number}); db.session.commit()
    from ..jobs.tasks import execute_request
    execute_request.delay(item.id)
    flash(f"{item.request_number} approved and queued.","success"); return redirect(url_for("requests.detail",request_id=item.id))

@bp.post("/<request_id>/reject")
@login_required
def reject(request_id):
    item=db.session.execute(db.select(DeploymentRequest).where(DeploymentRequest.id==request_id).with_for_update()).scalar_one_or_none()
    if not item: abort(404)
    _require_approver(item)
    if item.status!=RequestStatus.PENDING_APPROVAL.value: abort(409)
    item.status=RequestStatus.REJECTED.value; item.rejected_at=utcnow()
    db.session.add(Approval(request=item,approver_id=current_user.id,decision="rejected",comment=request.form.get("comment","").strip() or None))
    audit("REQUEST_REJECTED",entity_type="deployment_request",entity_id=item.id,details={"request_number":item.request_number}); db.session.commit()
    flash(f"{item.request_number} rejected.","info"); return redirect(url_for("approvals.index"))
