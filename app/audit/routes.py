from __future__ import annotations
import csv
import io
from flask import Blueprint, abort, make_response, render_template, request
from flask_login import current_user, login_required
from ..extensions import db
from ..models import AuditEvent, User

bp = Blueprint("audit", __name__, url_prefix="/audit")


def _require_audit_access():
    if current_user.role not in {"auditor", "admin", "global_admin"}:
        abort(403)


def _query():
    stmt = db.select(AuditEvent).order_by(AuditEvent.occurred_at.desc())
    event_type = request.args.get("event_type", "").strip()
    entity_id = request.args.get("entity_id", "").strip()
    actor = request.args.get("actor", "").strip()
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if entity_id:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    if actor:
        stmt = stmt.join(User, AuditEvent.actor_user_id == User.id).where(User.username.ilike(f"%{actor}%"))
    return stmt


@bp.get("/")
@login_required
def index():
    _require_audit_access()
    events = db.session.scalars(_query().limit(500)).all()
    event_types = db.session.scalars(db.select(AuditEvent.event_type).distinct().order_by(AuditEvent.event_type)).all()
    return render_template("audit/index.html", events=events, event_types=event_types)


@bp.get("/export.csv")
@login_required
def export_csv():
    _require_audit_access()
    events = db.session.scalars(_query().limit(10000)).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["occurred_at", "event_id", "actor", "event_type", "entity_type", "entity_id", "source_ip", "details"])
    for e in events:
        writer.writerow([
            e.occurred_at.isoformat(), e.event_id, e.actor.username if e.actor else "system", e.event_type,
            e.entity_type or "", e.entity_id or "", e.source_ip or "", e.details or {},
        ])
    response = make_response(buf.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=foreman-selfservice-audit.csv"
    return response
