import click
from flask import current_app
from .extensions import db
from .models import User
from .auth.services import set_local_password
from .jobs.inventory import sync_hosts
def register_cli(app):
    @app.cli.group("portal")
    def portal(): """Foreman Self-Service administration."""
    @portal.command("bootstrap")
    def bootstrap():
        username=current_app.config["BOOTSTRAP_ADMIN_USERNAME"]; password=current_app.config["BOOTSTRAP_ADMIN_PASSWORD"]; email=current_app.config["BOOTSTRAP_ADMIN_EMAIL"]
        if not username or not password: raise click.ClickException("Set BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_PASSWORD")
        if len(password)<14: raise click.ClickException("Bootstrap password must be at least 14 characters")
        user=db.session.scalar(db.select(User).where(User.username==username))
        if not user: user=User(username=username,email=email or None,display_name=username,role="global_admin"); db.session.add(user); db.session.flush()
        user.role="global_admin"; user.enabled=True; set_local_password(user,password); db.session.commit(); click.echo(f"Bootstrap global admin ready: {username}")
    @portal.command("sync-hosts")
    def sync_hosts_cmd(): click.echo(f"Synchronized {sync_hosts()} hosts")
