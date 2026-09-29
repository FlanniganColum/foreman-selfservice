from celery import Celery, Task


def make_celery(app):
    """Create and configure Celery so every task runs inside Flask context.

    Celery 5.x stores runtime configuration on ``celery.conf``.  The task
    module is explicitly included so workers know about execution,
    reconciliation, and inventory tasks before the first job is submitted.
    """

    class FlaskTask(Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery = Celery(
        app.import_name,
        broker=app.config["CELERY_BROKER_URL"],
        backend=app.config["CELERY_RESULT_BACKEND"],
        task_cls=FlaskTask,
        include=["app.jobs.tasks"],
    )
    celery.conf.update(
        task_ignore_result=True,
        timezone="UTC",
        enable_utc=True,
        beat_schedule={
            "reconcile-active-foreman-jobs": {
                "task": "app.jobs.tasks.reconcile_active_jobs",
                "schedule": app.config["FOREMAN_RECONCILE_INTERVAL_SECONDS"],
            },
            "recover-approved-unsubmitted-jobs": {
                "task": "app.jobs.tasks.recover_unqueued_requests",
                "schedule": 30.0,
            },
            "sync-foreman-host-inventory": {
                "task": "app.jobs.tasks.sync_foreman_hosts",
                "schedule": app.config["FOREMAN_HOST_SYNC_INTERVAL_SECONDS"],
            },
        },
    )
    celery.set_default()
    app.extensions["celery"] = celery
    return celery
