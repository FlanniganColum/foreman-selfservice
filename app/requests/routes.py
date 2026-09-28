from datetime import datetime, timezone
import secrets
from uuid import uuid4
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user
from ..extensions import db
from ..models import DeploymentRequest, JobExecution, Server, User, RequestStatus, utcnow
from ..catalog.service import (
    get_chiklet,
    can_user_access_chiklet,
    can_user_target_server,
    validate_form,
    build_form_layout,
    authorised_servers,
    sensitive_fields,
    approval_mode,
    bound_username,
)
from ..audit.service import audit
from ..secrets import SecretStoreError, store_secrets
from ..approvals.routes import owner_ids

bp = Blueprint("requests", __name__, url_prefix="/requests")


def _request_number():
    return f"REQ-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{secrets.token_hex(6).upper()}"


@bp.post("/submit/<chiklet_id>")
@login_required
def submit(chiklet_id):
    chiklet = get_chiklet(chiklet_id)
    if not chiklet or not can_user_access_chiklet(current_user, chiklet):
        abort(403)
    try:
        server_id = int(request.form.get("server_id", ""))
    except ValueError:
        abort(400)
    server = db.session.get(Server, server_id)
    if not server or not server.enabled or not server.group:
        abort(400)
    if not can_user_target_server(current_user, chiklet, server):
        abort(403)
    bound_values = bound_username(chiklet)
    if bound_values is None:
        abort(403, description="This Chiklet requires a verified LDAP or Entra username.")
    mode = approval_mode(chiklet)
    eligible_owners = ({server.business_owner_id} if mode == "business" else
                       {server.technical_owner_id, server.business_owner_id}) - {None, current_user.id}
    if mode != "none" and not any((owner := db.session.get(User, uid)) and owner.enabled for uid in eligible_owners):
        flash(("This server needs an enabled business owner other than the requester." if mode == "business" else
               "This server needs an enabled technical or business owner other than the requester."), "danger")
        return redirect(url_for("catalog.detail", chiklet_id=chiklet_id))

    form_data, errors, field_errors = validate_form(chiklet, request.form, bound_values=bound_values, with_fields=True)
    if errors:
        return (
            render_template(
                "catalog/detail.html",
                chiklet=chiklet,
                servers=authorised_servers(current_user, chiklet),
                form_layout=build_form_layout(chiklet, form_data, bound_values=bound_values),
                errors=errors,
                field_errors=field_errors,
                selected_server_id=server.id,
                justification=request.form.get("justification", ""),
            ),
            400,
        )

    request_id = str(uuid4())
    secret_names = sensitive_fields(chiklet)
    try:
        references = store_secrets(request_id, {name: form_data[name] for name in secret_names if name in form_data})
    except SecretStoreError:
        flash("Sensitive values could not be stored. Please retry later.", "danger")
        return (
            render_template("catalog/detail.html", chiklet=chiklet,
                            servers=authorised_servers(current_user, chiklet),
                            form_layout=build_form_layout(chiklet, form_data, bound_values=bound_values),
                            selected_server_id=server.id,
                            justification=request.form.get("justification", "")),
            503,
        )
    form_data.update(references)
    item = DeploymentRequest(
        id=request_id,
        request_number=_request_number(),
        requested_by_id=current_user.id,
        chiklet_id=chiklet["id"],
        chiklet_name=chiklet["name"],
        chiklet_version=chiklet["version"],
        server_group_id=server.group_id,
        status=RequestStatus.PENDING_APPROVAL.value if mode != "none" else RequestStatus.APPROVED.value,
        approved_at=utcnow() if mode == "none" else None,
        justification=request.form.get("justification", "").strip() or None,
        form_data=form_data,
        submitted_form_data=dict(form_data),
        config_snapshot=chiklet,
        target_snapshot={
            "server_id": server.id,
            "foreman_host_id": server.foreman_host_id,
            "name": server.name,
            "ip_address": server.ip_address,
            "server_group_id": server.group_id,
            "server_group_slug": server.group.slug,
            "technical_owner_id": server.technical_owner_id,
            "business_owner_id": server.business_owner_id,
        },
    )
    db.session.add(item)
    db.session.flush()
    if mode == "none":
        db.session.add(JobExecution(request=item, status=RequestStatus.QUEUED.value))
    audit(
        "REQUEST_SUBMITTED",
        entity_type="deployment_request",
        entity_id=item.id,
        details={"request_number": item.request_number, "chiklet": item.chiklet_id, "server": server.name},
    )
    if mode == "none":
        audit("REQUEST_AUTO_APPROVED", entity_type="deployment_request", entity_id=item.id,
              details={"request_number": item.request_number, "policy": "none"})
    db.session.commit()
    if mode == "none":
        from ..jobs.tasks import execute_request
        execute_request.delay(item.id)
    flash(f"{item.request_number} submitted {'for business owner approval' if mode == 'business' else 'for owner approval' if mode == 'full' else 'for execution'}.", "success")
    return redirect(url_for("requests.detail", request_id=item.id))


@bp.get("/")
@login_required
def index():
    stmt = db.select(DeploymentRequest).order_by(DeploymentRequest.created_at.desc())
    if current_user.role in {"global_admin", "admin", "auditor", "linux_admin"}:
        items = db.session.scalars(stmt.limit(200)).all()
    else:
        items = [x for x in db.session.scalars(stmt.limit(500)).all()
                 if x.requested_by_id == current_user.id or current_user.id in owner_ids(x)][:200]
    return render_template("requests/index.html", requests=items)


@bp.get("/<request_id>")
@login_required
def detail(request_id):
    item = db.session.get(DeploymentRequest, request_id)
    if not item:
        abort(404)
    if (item.requested_by_id != current_user.id and
            current_user.role not in {"global_admin", "admin", "auditor", "linux_admin"} and
            current_user.id not in owner_ids(item)):
        abort(403)
    target = item.target_snapshot or {}
    owners = {
        kind: db.session.get(User, target.get(f"{kind}_owner_id")) if target.get(f"{kind}_owner_id") else None
        for kind in ("technical", "business")
    }
    return render_template("requests/detail.html", item=item, owners=owners)
