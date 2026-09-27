from copy import deepcopy
from uuid import uuid4

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from jsonschema import Draft202012Validator

from ..audit.service import audit
from ..catalog.service import build_form_layout, field_value_from_request, sensitive_fields
from ..extensions import db
from ..models import Approval, DeploymentRequest, JobExecution, RequestStatus, Server, utcnow
from ..secrets import SecretStoreError, store_secrets

bp = Blueprint("approvals", __name__, url_prefix="/approvals")


def owner_ids(item):
    target = item.target_snapshot or {}
    if "technical_owner_id" in target or "business_owner_id" in target:
        return {target.get("technical_owner_id"), target.get("business_owner_id")} - {None}
    # Requests created before the owner fields were introduced.
    server = db.session.get(Server, target.get("server_id")) if target.get("server_id") else None
    return {server.technical_owner_id, server.business_owner_id} - {None} if server else set()


def can_review(item, stage):
    if item.requested_by_id == current_user.id or not current_user.enabled:
        return False
    if stage == "owner":
        return current_user.id in owner_ids(item)
    if stage == "linux":
        return (current_user.role in {"linux_admin", "global_admin"}
                and not any(a.stage == "owner" and a.decision == "approved"
                            and a.approver_id == current_user.id for a in item.approvals))
    return False


def current_stage(item):
    if item.status == RequestStatus.PENDING_APPROVAL.value:
        return "owner"
    if item.status == RequestStatus.PENDING_LINUX_APPROVAL.value:
        return "linux"
    return None


def _require_stage(item, stage):
    if not can_review(item, stage):
        abort(403)
    if current_stage(item) != stage:
        abort(409)
    if stage == "linux" and not any(a.stage == "owner" and a.decision == "approved" for a in item.approvals):
        abort(409)


@bp.get("/")
@login_required
def index():
    if current_user.role not in {"linux_admin", "global_admin"} and not current_user.is_server_owner():
        abort(403)
    items = db.session.scalars(
        db.select(DeploymentRequest).where(DeploymentRequest.status.in_(
            [RequestStatus.PENDING_APPROVAL.value, RequestStatus.PENDING_LINUX_APPROVAL.value]
        )).order_by(DeploymentRequest.submitted_at.asc())
    ).all()
    items = [x for x in items if can_review(x, current_stage(x))]
    return render_template("approvals/index.html", requests=items)


@bp.get("/<request_id>/review")
@login_required
def review(request_id):
    item = db.session.get(DeploymentRequest, request_id)
    if not item:
        abort(404)
    stage = current_stage(item)
    if not can_review(item, stage):
        abort(403)
    bound_field = (item.config_snapshot.get("identity_binding") or {}).get("username_field")
    bound_values = {bound_field: item.form_data[bound_field]} if bound_field and bound_field in item.form_data else None
    return render_template("approvals/review.html", item=item, stage=stage,
                           form_layout=build_form_layout(item.config_snapshot, item.form_data, bound_values=bound_values))


@bp.post("/<request_id>/approve")
@login_required
def approve(request_id):
    item = db.session.execute(db.select(DeploymentRequest).where(
        DeploymentRequest.id == request_id).with_for_update()).scalar_one_or_none()
    if not item:
        abort(404)
    stage = current_stage(item)
    _require_stage(item, stage)
    comment = request.form.get("comment", "").strip()[:2000] or None
    if stage == "owner":
        item.status = RequestStatus.PENDING_LINUX_APPROVAL.value
        event = "REQUEST_OWNER_APPROVED"
        message = f"{item.request_number} approved by the server owner; awaiting Linux review."
    else:
        overrides, errors = _read_overrides(item)
        if errors:
            for error in errors:
                flash(error, "danger")
            return redirect(url_for("approvals.review", request_id=item.id)), 303
        secret_names = sensitive_fields(item.config_snapshot)
        secret_values = {key: value for key, value in overrides.items() if key in secret_names}
        try:
            references = store_secrets(str(uuid4()), secret_values)
        except SecretStoreError:
            flash("Sensitive overrides could not be stored. Please retry later.", "danger")
            return redirect(url_for("approvals.review", request_id=item.id)), 303
        overrides.update(references)
        if overrides:
            item.form_data = {**item.form_data, **overrides}
        item.status = RequestStatus.APPROVED.value
        item.approved_at = utcnow()
        db.session.add(JobExecution(request=item, status=RequestStatus.QUEUED.value))
        event = "REQUEST_LINUX_APPROVED"
        message = f"{item.request_number} approved by Linux and queued."
    db.session.add(Approval(request=item, approver_id=current_user.id, stage=stage,
                            decision="approved", comment=comment))
    audit(event, entity_type="deployment_request", entity_id=item.id,
          details={"request_number": item.request_number, "overridden_fields": sorted(overrides) if stage == "linux" else []})
    db.session.commit()
    if stage == "linux":
        from ..jobs.tasks import execute_request
        execute_request.delay(item.id)
    flash(message, "success")
    return redirect(url_for("requests.detail", request_id=item.id))


def _read_overrides(item):
    schema = item.config_snapshot["form_schema"]
    properties = schema.get("properties", {})
    chosen = request.form.getlist("override_fields")
    bound_field = (item.config_snapshot.get("identity_binding") or {}).get("username_field")
    if len(set(chosen)) != len(chosen) or any(key not in properties or properties[key].get("readOnly") or key == bound_field for key in chosen):
        abort(400)
    overrides = {}
    for key in chosen:
        spec = properties[key]
        if spec.get("type") == "boolean" and request.form.get(f"field__{key}") not in {"true", "false"}:
            return {}, [f"{key}: invalid override"]
        try:
            value = field_value_from_request(key, spec, request.form)
        except (TypeError, ValueError):
            return {}, [f"{key}: invalid override"]
        if value is None or (value == "" and key in schema.get("required", [])):
            return {}, [f"{key}: override is required"]
        if list(Draft202012Validator(spec).iter_errors(value)):
            return {}, [f"{key}: invalid override"]
        overrides[key] = value
    # Validate the full effective form, without examining stored Vault references
    # against rules for raw secrets (for example a private key PEM pattern).
    effective = {**item.form_data, **overrides}
    safe_schema = deepcopy(schema)
    for key in sensitive_fields(item.config_snapshot):
        safe_schema["properties"][key] = {"type": "string"}
    if list(Draft202012Validator(safe_schema).iter_errors(effective)):
        return {}, ["The overridden values do not satisfy the Chiklet schema"]
    return overrides, []


@bp.post("/<request_id>/reject")
@login_required
def reject(request_id):
    item = db.session.execute(db.select(DeploymentRequest).where(
        DeploymentRequest.id == request_id).with_for_update()).scalar_one_or_none()
    if not item:
        abort(404)
    stage = current_stage(item)
    _require_stage(item, stage)
    item.status = RequestStatus.REJECTED.value
    item.rejected_at = utcnow()
    db.session.add(Approval(request=item, approver_id=current_user.id, stage=stage,
                            decision="rejected", comment=request.form.get("comment", "").strip()[:2000] or None))
    audit("REQUEST_REJECTED", entity_type="deployment_request", entity_id=item.id,
          details={"request_number": item.request_number, "stage": stage})
    db.session.commit()
    flash(f"{item.request_number} rejected.", "info")
    return redirect(url_for("approvals.index"))
