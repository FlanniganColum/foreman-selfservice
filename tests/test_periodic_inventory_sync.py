from unittest.mock import Mock

from app.jobs.tasks import sync_foreman_hosts


def test_beat_schedules_foreman_host_sync_every_15_minutes(app):
    entry=app.extensions["celery"].conf.beat_schedule["sync-foreman-host-inventory"]
    assert entry["task"] == "app.jobs.tasks.sync_foreman_hosts"
    assert entry["schedule"] == app.config["FOREMAN_HOST_SYNC_INTERVAL_SECONDS"] == 900


def test_periodic_task_calls_existing_inventory_sync(app, monkeypatch):
    sync=Mock(return_value=42)
    monkeypatch.setattr("app.jobs.inventory.sync_hosts",sync)
    with app.app_context():
        assert sync_foreman_hosts.run() == 42
    sync.assert_called_once_with()
