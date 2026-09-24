from flask import request, has_request_context
from flask_login import current_user
from ..extensions import db
from ..models import AuditEvent

def audit(event_type, *, entity_type=None, entity_id=None, details=None, actor=None):
    if actor is None and has_request_context() and getattr(current_user,"is_authenticated",False): actor=current_user
    source_ip=user_agent=None
    if has_request_context():
        source_ip=request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        user_agent=request.headers.get("User-Agent","")[:512]
    db.session.add(AuditEvent(actor_user_id=getattr(actor,"id",None),event_type=event_type,entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,source_ip=source_ip,user_agent=user_agent,details=details or {}))
