from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4
from flask_login import UserMixin
from sqlalchemy import UniqueConstraint
from .extensions import db

def utcnow():
    return datetime.now(timezone.utc)

user_server_groups = db.Table(
    "user_server_groups",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("server_group_id", db.Integer, db.ForeignKey("server_groups.id", ondelete="CASCADE"), primary_key=True),
)
approver_server_groups = db.Table(
    "approver_server_groups",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("server_group_id", db.Integer, db.ForeignKey("server_groups.id", ondelete="CASCADE"), primary_key=True),
)

class AppRole(str, Enum):
    USER="user"; APPROVER="approver"; LINUX_ADMIN="linux_admin"; ADMIN="admin"; AUDITOR="auditor"; GLOBAL_ADMIN="global_admin"

class RequestStatus(str, Enum):
    PENDING_APPROVAL="pending_approval"; PENDING_LINUX_APPROVAL="pending_linux_approval"; REJECTED="rejected"; APPROVED="approved"; QUEUED="queued"; RUNNING="running"; SUCCEEDED="succeeded"; FAILED="failed"; CANCELLED="cancelled"

class User(db.Model, UserMixin):
    __tablename__="users"
    id=db.Column(db.Integer, primary_key=True)
    username=db.Column(db.String(160), unique=True, nullable=False, index=True)
    email=db.Column(db.String(255), index=True)
    display_name=db.Column(db.String(255))
    role=db.Column(db.String(32), nullable=False, default=AppRole.USER.value, index=True)
    enabled=db.Column(db.Boolean, nullable=False, default=True)
    created_at=db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at=db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    last_login_at=db.Column(db.DateTime(timezone=True))
    identities=db.relationship("AuthIdentity", back_populates="user", cascade="all, delete-orphan")
    local_credential=db.relationship("LocalCredential", back_populates="user", uselist=False, cascade="all, delete-orphan")
    server_groups=db.relationship("ServerGroup", secondary=user_server_groups, back_populates="members")
    approval_groups=db.relationship("ServerGroup", secondary=approver_server_groups, back_populates="approvers")
    @property
    def is_active(self): return self.enabled
    def has_role(self,*roles): return self.role in set(roles)
    def is_global_admin(self): return self.role==AppRole.GLOBAL_ADMIN.value
    def is_server_owner(self):
        return db.session.scalar(db.select(Server.id).where(
            (Server.technical_owner_id == self.id) | (Server.business_owner_id == self.id)).limit(1)) is not None
    def can_approve_group(self,group_id):
        if self.is_global_admin() or self.role==AppRole.ADMIN.value: return True
        return self.role==AppRole.APPROVER.value and any(g.id==group_id for g in self.approval_groups)

class AuthIdentity(db.Model):
    __tablename__="auth_identities"
    id=db.Column(db.Integer, primary_key=True)
    user_id=db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider=db.Column(db.String(32), nullable=False)
    subject=db.Column(db.String(255), nullable=False)
    authenticated_username=db.Column(db.String(255))
    created_at=db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    user=db.relationship("User", back_populates="identities")
    __table_args__=(UniqueConstraint("provider","subject",name="uq_auth_identity_provider_subject"),)

class LocalCredential(db.Model):
    __tablename__="local_credentials"
    user_id=db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    password_hash=db.Column(db.String(512), nullable=False)
    failed_attempts=db.Column(db.Integer, nullable=False, default=0)
    locked_until=db.Column(db.DateTime(timezone=True))
    password_changed_at=db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    user=db.relationship("User", back_populates="local_credential")

class ServerGroup(db.Model):
    __tablename__="server_groups"
    id=db.Column(db.Integer, primary_key=True)
    slug=db.Column(db.String(120), unique=True, nullable=False, index=True)
    name=db.Column(db.String(160), nullable=False)
    description=db.Column(db.Text)
    enabled=db.Column(db.Boolean, nullable=False, default=True)
    created_at=db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    members=db.relationship("User", secondary=user_server_groups, back_populates="server_groups")
    approvers=db.relationship("User", secondary=approver_server_groups, back_populates="approval_groups")
    servers=db.relationship("Server", back_populates="group")

class Server(db.Model):
    __tablename__="servers"
    id=db.Column(db.Integer, primary_key=True)
    foreman_host_id=db.Column(db.Integer, unique=True, nullable=False, index=True)
    name=db.Column(db.String(255), unique=True, nullable=False, index=True)
    ip_address=db.Column(db.String(64))
    environment=db.Column(db.String(120))
    group_id=db.Column(db.Integer, db.ForeignKey("server_groups.id"), nullable=False, index=True)
    technical_owner_id=db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    business_owner_id=db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    enabled=db.Column(db.Boolean, nullable=False, default=True)
    foreman_metadata=db.Column(db.JSON)
    last_synced_at=db.Column(db.DateTime(timezone=True))
    group=db.relationship("ServerGroup", back_populates="servers")
    technical_owner=db.relationship("User", foreign_keys=[technical_owner_id])
    business_owner=db.relationship("User", foreign_keys=[business_owner_id])

class DeploymentRequest(db.Model):
    __tablename__="deployment_requests"
    id=db.Column(db.String(36), primary_key=True, default=lambda:str(uuid4()))
    request_number=db.Column(db.String(32), unique=True, nullable=False, index=True)
    requested_by_id=db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    chiklet_id=db.Column(db.String(160), nullable=False, index=True)
    chiklet_name=db.Column(db.String(255), nullable=False)
    chiklet_version=db.Column(db.String(64), nullable=False)
    server_group_id=db.Column(db.Integer, db.ForeignKey("server_groups.id"), nullable=False, index=True)
    status=db.Column(db.String(32), nullable=False, default=RequestStatus.PENDING_APPROVAL.value, index=True)
    justification=db.Column(db.Text)
    form_data=db.Column(db.JSON, nullable=False)
    submitted_form_data=db.Column(db.JSON)
    config_snapshot=db.Column(db.JSON, nullable=False)
    target_snapshot=db.Column(db.JSON, nullable=False)
    created_at=db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    submitted_at=db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    approved_at=db.Column(db.DateTime(timezone=True))
    rejected_at=db.Column(db.DateTime(timezone=True))
    completed_at=db.Column(db.DateTime(timezone=True))
    requested_by=db.relationship("User", foreign_keys=[requested_by_id])
    server_group=db.relationship("ServerGroup")
    approvals=db.relationship("Approval", back_populates="request", cascade="all, delete-orphan", order_by="Approval.id")
    execution=db.relationship("JobExecution", back_populates="request", uselist=False, cascade="all, delete-orphan")

class Approval(db.Model):
    __tablename__="approvals"
    id=db.Column(db.Integer, primary_key=True)
    request_id=db.Column(db.String(36), db.ForeignKey("deployment_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    approver_id=db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    decision=db.Column(db.String(16), nullable=False)
    stage=db.Column(db.String(16), nullable=False, default="owner")
    comment=db.Column(db.Text)
    decided_at=db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    request=db.relationship("DeploymentRequest", back_populates="approvals")
    approver=db.relationship("User")

class JobExecution(db.Model):
    __tablename__="job_executions"
    id=db.Column(db.Integer, primary_key=True)
    request_id=db.Column(db.String(36), db.ForeignKey("deployment_requests.id", ondelete="CASCADE"), unique=True, nullable=False)
    foreman_job_id=db.Column(db.String(128), index=True)
    status=db.Column(db.String(32), nullable=False, default=RequestStatus.QUEUED.value)
    status_label=db.Column(db.String(120))
    submitted_at=db.Column(db.DateTime(timezone=True))
    started_at=db.Column(db.DateTime(timezone=True))
    finished_at=db.Column(db.DateTime(timezone=True))
    last_polled_at=db.Column(db.DateTime(timezone=True))
    host_results=db.Column(db.JSON)
    output_excerpt=db.Column(db.Text)
    error_message=db.Column(db.Text)
    request=db.relationship("DeploymentRequest", back_populates="execution")

class AuditEvent(db.Model):
    __tablename__="audit_events"
    id=db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True)
    event_id=db.Column(db.String(36), unique=True, nullable=False, default=lambda:str(uuid4()))
    occurred_at=db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    actor_user_id=db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    event_type=db.Column(db.String(100), nullable=False, index=True)
    entity_type=db.Column(db.String(100), index=True)
    entity_id=db.Column(db.String(160), index=True)
    source_ip=db.Column(db.String(64))
    user_agent=db.Column(db.String(512))
    details=db.Column(db.JSON)
    actor=db.relationship("User")
