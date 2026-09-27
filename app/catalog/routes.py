from pathlib import Path
from flask import Blueprint, abort, current_app, render_template, send_from_directory
from flask_login import login_required, current_user
from .service import (
    list_chiklets,
    get_chiklet,
    can_user_access_chiklet,
    build_form_layout,
    authorised_servers,
    bound_username,
)

bp = Blueprint("catalog", __name__)


@bp.get("/")
@login_required
def index():
    return render_template("catalog/index.html", chiklets=[x for x in list_chiklets() if can_user_access_chiklet(current_user, x)])


@bp.get("/chiklets/<chiklet_id>")
@login_required
def detail(chiklet_id):
    chiklet = get_chiklet(chiklet_id)
    if not chiklet or not can_user_access_chiklet(current_user, chiklet):
        abort(404)
    bound_values = bound_username(chiklet)
    if bound_values is None:
        abort(403, description="This Chiklet requires a verified LDAP or Entra username.")
    return render_template(
        "catalog/detail.html",
        chiklet=chiklet,
        servers=authorised_servers(current_user, chiklet),
        form_layout=build_form_layout(chiklet, bound_values=bound_values),
    )


@bp.get("/chiklet-assets/<path:filename>")
@login_required
def asset(filename):
    suffix = Path(filename).suffix.lower()
    if suffix not in {".svg", ".png", ".jpg", ".jpeg", ".webp"}:
        abort(404)
    asset_dir = Path(current_app.config["CHIKLET_DIRECTORY"]) / "assets"
    response = send_from_directory(asset_dir, filename, conditional=True, max_age=0)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
