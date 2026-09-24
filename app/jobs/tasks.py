from celery import shared_task
from flask import current_app
from redis import Redis
from ..extensions import db
from ..models import DeploymentRequest, JobExecution, utcnow
from ..foreman.client import ForemanClient
from ..audit.service import audit


TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _map(label):
    return {
        "queued": "queued",
        "running": "running",
        "succeeded": "succeeded",
        "failed": "failed",
        "cancelled": "cancelled",
        "canceled": "cancelled",
    }.get((label or "").lower(), "running")


def _map_foreman_state(state):
    """Map structured Foreman job data to the portal execution state.

    status_label remains the primary source of truth. Structured failed-host
    counts take precedence over a success label so the portal cannot report a
    successful deployment when Foreman itself reports failed hosts.
    """
    label = (state.get("status_label") or "").strip()
    mapped = _map(label)
    failed = _as_int(state.get("failed"))
    pending = _as_int(state.get("pending"))
    running = _as_int(state.get("running"))

    if failed > 0 and pending == 0 and running == 0:
        return "failed", label or "failed"
    return mapped, label or mapped


def _fallback_target_host(item):
    target = item.target_snapshot or {}
    host_id = target.get("foreman_host_id")
    if not host_id:
        return []
    return [{"id": host_id, "host_id": host_id, "name": target.get("name"), "status": item.status}]


def _execution_lock(request_id):
    redis = Redis.from_url(current_app.config["REDIS_URL"])
    return redis.lock(f"foreman-selfservice:execute:{request_id}", timeout=180, blocking_timeout=1)


@shared_task(bind=True, name="app.jobs.tasks.execute_request", max_retries=3)
def execute_request(self, request_id):
    lock = _execution_lock(request_id)
    if not lock.acquire(blocking=True):
        return
    try:
        item = db.session.get(DeploymentRequest, request_id)
        if not item or item.status not in {"approved", "queued"}:
            return
        execn = item.execution or JobExecution(request=item)
        if execn.foreman_job_id:
            return
        item.status = "queued"
        execn.status = "queued"
        db.session.add(execn)
        db.session.commit()

        client = ForemanClient()
        try:
            # If a previous worker died after Foreman accepted the invocation but before
            # PostgreSQL was committed, recover by correlation ID rather than resubmitting.
            recovered = client.find_job_by_correlation(item.request_number) if self.request.retries else None
            result = recovered or client.create_job(
                item.config_snapshot,
                item.target_snapshot,
                item.form_data,
                correlation_id=item.request_number,
            )
            execn = item.execution
            execn.foreman_job_id = str(result["id"])
            execn.submitted_at = execn.submitted_at or utcnow()
            execn.status_label = result.get("status_label", "queued")
            item.status = _map(execn.status_label)
            execn.status = item.status
            execn.error_message = None
            audit(
                "FOREMAN_JOB_RECOVERED" if recovered else "FOREMAN_JOB_SUBMITTED",
                entity_type="deployment_request",
                entity_id=item.id,
                details={"foreman_job_id": execn.foreman_job_id, "correlation": item.request_number},
            )
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            item = db.session.get(DeploymentRequest, request_id)
            execn = item.execution
            execn.error_message = str(exc)[:4000]
            if self.request.retries >= self.max_retries:
                execn.status = "failed"
                item.status = "failed"
                item.completed_at = utcnow()
                audit(
                    "FOREMAN_JOB_SUBMIT_FAILED",
                    entity_type="deployment_request",
                    entity_id=item.id,
                    details={"error": str(exc)[:1000], "attempts": self.request.retries + 1},
                )
                db.session.commit()
                return
            execn.status = "queued"
            item.status = "queued"
            db.session.commit()
            raise self.retry(exc=exc, countdown=min(60, 5 * (2 ** self.request.retries)))
    finally:
        try:
            lock.release()
        except Exception:
            pass


@shared_task(name="app.jobs.tasks.recover_unqueued_requests")
def recover_unqueued_requests():
    stmt = (
        db.select(JobExecution)
        .join(DeploymentRequest, JobExecution.request_id == DeploymentRequest.id)
        .where(
            JobExecution.foreman_job_id.is_(None),
            JobExecution.status == "queued",
            DeploymentRequest.status.in_(["approved", "queued"]),
        )
        .limit(100)
    )
    for execn in db.session.scalars(stmt).all():
        execute_request.delay(execn.request_id)


@shared_task(name="app.jobs.tasks.reconcile_active_jobs")
def reconcile_active_jobs():
    stmt = db.select(JobExecution).where(JobExecution.status.in_(["queued", "running"]))
    for execn in db.session.scalars(stmt).all():
        if not execn.foreman_job_id:
            continue
        try:
            client = ForemanClient()
            state = client.get_job(execn.foreman_job_id)
            mapped, label = _map_foreman_state(state)
            execn.status_label = label
            execn.status = mapped
            execn.last_polled_at = utcnow()
            execn.error_message = None
            item = execn.request
            item.status = mapped
            if mapped == "running" and not execn.started_at:
                execn.started_at = utcnow()
            if mapped in TERMINAL_STATES:
                execn.finished_at = execn.finished_at or utcnow()
                item.completed_at = item.completed_at or utcnow()
                try:
                    hosts = client.get_hosts(execn.foreman_job_id, state=state)
                    execn.host_results = hosts or _fallback_target_host(item)
                except Exception as host_exc:
                    # Host-detail enrichment must never prevent the authoritative
                    # Foreman terminal state from being committed to the portal.
                    current_app.logger.warning(
                        "Foreman job %s reached %s but host details could not be retrieved: %s",
                        execn.foreman_job_id,
                        mapped,
                        host_exc,
                    )
                    execn.host_results = execn.host_results or _fallback_target_host(item)
                    execn.error_message = f"Job status recorded; Foreman host-detail lookup failed: {host_exc}"[:4000]
                audit(
                    "FOREMAN_JOB_COMPLETED",
                    entity_type="deployment_request",
                    entity_id=item.id,
                    details={"foreman_job_id": execn.foreman_job_id, "status": mapped},
                )
            db.session.commit()
        except Exception as exc:
            current_app.logger.exception("Failed polling Foreman job %s", execn.foreman_job_id)
            execn.error_message = f"Last polling error: {exc}"[:4000]
            db.session.commit()
