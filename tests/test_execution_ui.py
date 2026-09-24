from pathlib import Path


def test_execution_template_has_live_refresh_hooks():
    template = Path("app/templates/requests/detail.html").read_text()
    assert 'data-status-url=' in template
    assert 'data-step="approved"' in template
    assert 'data-step="foreman"' in template
    assert 'data-step="ansible"' in template
    assert 'id="job-output"' in template
    assert 'id="toggle-execution-fullscreen"' in template


def test_execution_javascript_has_periodic_refresh():
    script = Path("app/static/js/app.js").read_text()
    assert "statusIntervalMs=4000" in script
    assert "outputIntervalMs=8000" in script
    assert "scheduleOutput" in script
    assert "updateSteps" in script


def test_execution_css_has_large_output_workspace():
    css = Path("app/static/css/app.css").read_text()
    assert ".execution-card.fullscreen" in css
    assert "min-height:520px" in css
    assert "resize:vertical" in css
