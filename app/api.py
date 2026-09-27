from flask import Blueprint, abort, jsonify
from flask_login import login_required, current_user
from .extensions import db
from .models import DeploymentRequest
from .foreman.client import ForemanClient
from .approvals.routes import owner_ids

bp = Blueprint("api", __name__, url_prefix="/api")


def _authorise(item):
    if item.requested_by_id == current_user.id:
        return
    if current_user.role in {"global_admin", "admin", "auditor"}:
        return
    if current_user.role == "linux_admin":
        return
    if current_user.id in owner_ids(item):
        return
    abort(403)


def _target_host_fallback(item):
    target = item.target_snapshot or {}
    host_id = target.get("foreman_host_id")
    if not host_id:
        return []
    return [{"id": host_id, "host_id": host_id, "name": target.get("name")}]


@bp.get("/requests/<request_id>/status")
@login_required
def request_status(request_id):
    item = db.session.get(DeploymentRequest, request_id)
    if not item:
        abort(404)
    _authorise(item)
    e = item.execution
    return jsonify({
        "request_id": item.id,
        "request_number": item.request_number,
        "status": item.status,
        "owner_approved": any(a.stage == "owner" and a.decision == "approved" for a in item.approvals),
        "foreman_job_id": e.foreman_job_id if e else None,
        "status_label": e.status_label if e else None,
        "last_polled_at": e.last_polled_at.isoformat() if e and e.last_polled_at else None,
        "host_results": e.host_results if e else None,
        "error": e.error_message if e else None,
    })


@bp.get("/requests/<request_id>/output")
@login_required
def request_output(request_id):
    item = db.session.get(DeploymentRequest, request_id)
    if not item:
        abort(404)
    _authorise(item)
    execution = item.execution
    if not execution or not execution.foreman_job_id:
        return jsonify({"ready": False, "outputs": []})
    client = ForemanClient()
    if client.mock:
        return jsonify({
            "ready": True,
            "outputs": [{"host": item.target_snapshot["name"], "output": "Mock execution completed successfully."}],
        })

    # Reuse cached host details first. If they are unavailable, use Foreman's
    # compatibility-aware discovery and finally the immutable request target.
    hosts = execution.host_results or []
    if not hosts:
        state = client.get_job(execution.foreman_job_id)
        hosts = client.get_hosts(execution.foreman_job_id, state=state)
    hosts = hosts or _target_host_fallback(item)

    outputs = []
    for host in hosts:
        host_id = host.get("host_id") or host.get("id") or host.get("targeted_host_id")
        if not host_id:
            continue
        raw = client.get_host_output(execution.foreman_job_id, host_id)
        outputs.append({
            "host": host.get("host") or host.get("name") or str(host_id),
            "status": host.get("status"),
            "output": raw,
        })
    return jsonify({"ready": bool(outputs), "outputs": outputs})
