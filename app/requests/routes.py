from datetime import datetime, timezone
import secrets
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user
from ..extensions import db
from ..models import DeploymentRequest, Server, RequestStatus
from ..catalog.service import (
    get_chiklet,
    can_user_access_chiklet,
    can_user_target_server,
    validate_form,
    build_form_layout,
    authorised_servers,
)
from ..audit.service import audit

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

    form_data, errors = validate_form(chiklet, request.form)
    if errors:
        for error in errors:
            flash(error, "danger")
        return (
            render_template(
                "catalog/detail.html",
                chiklet=chiklet,
                servers=authorised_servers(current_user, chiklet),
                form_layout=build_form_layout(chiklet, form_data),
                selected_server_id=server.id,
                justification=request.form.get("justification", ""),
            ),
            400,
        )

    item = DeploymentRequest(
        request_number=_request_number(),
        requested_by_id=current_user.id,
        chiklet_id=chiklet["id"],
        chiklet_name=chiklet["name"],
        chiklet_version=chiklet["version"],
        server_group_id=server.group_id,
        status=RequestStatus.PENDING_APPROVAL.value,
        justification=request.form.get("justification", "").strip() or None,
        form_data=form_data,
        config_snapshot=chiklet,
        target_snapshot={
            "server_id": server.id,
            "foreman_host_id": server.foreman_host_id,
            "name": server.name,
            "ip_address": server.ip_address,
            "server_group_id": server.group_id,
            "server_group_slug": server.group.slug,
        },
    )
    db.session.add(item)
    db.session.flush()
    audit(
        "REQUEST_SUBMITTED",
        entity_type="deployment_request",
        entity_id=item.id,
        details={"request_number": item.request_number, "chiklet": item.chiklet_id, "server": server.name},
    )
    db.session.commit()
    flash(f"{item.request_number} submitted for approval.", "success")
    return redirect(url_for("requests.detail", request_id=item.id))


@bp.get("/")
@login_required
def index():
    stmt = db.select(DeploymentRequest).order_by(DeploymentRequest.created_at.desc())
    if current_user.role not in {"global_admin", "admin", "auditor", "approver"}:
        stmt = stmt.where(DeploymentRequest.requested_by_id == current_user.id)
        items = db.session.scalars(stmt.limit(200)).all()
    elif current_user.role == "approver":
        items = db.session.scalars(stmt.limit(500)).all()
        gids = {g.id for g in current_user.approval_groups}
        items = [x for x in items if x.requested_by_id == current_user.id or x.server_group_id in gids][:200]
    else:
        items = db.session.scalars(stmt.limit(200)).all()
    return render_template("requests/index.html", requests=items)


@bp.get("/<request_id>")
@login_required
def detail(request_id):
    item = db.session.get(DeploymentRequest, request_id)
    if not item:
        abort(404)
    if item.requested_by_id != current_user.id and current_user.role not in {"global_admin", "admin", "auditor", "approver"}:
        abort(403)
    if current_user.role == "approver" and item.requested_by_id != current_user.id and not current_user.can_approve_group(item.server_group_id):
        abort(403)
    return render_template("requests/detail.html", item=item)
