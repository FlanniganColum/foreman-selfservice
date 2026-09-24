from flask import Blueprint,current_app,flash,redirect,render_template,request,url_for
from flask_login import current_user,login_user,logout_user
from ..extensions import db,limiter
from ..audit.service import audit
from ..models import utcnow
from .services import verify_local,authenticate_ldap,begin_entra_flow,complete_entra_flow
bp=Blueprint("auth",__name__,url_prefix="/auth")

@bp.get("/login")
def login():
    if current_user.is_authenticated: return redirect(url_for("catalog.index"))
    return render_template("auth/login.html")

@bp.post("/local")
@limiter.limit("10 per minute")
def local_login():
    if not current_app.config["ENABLE_LOCAL"]: return ("Local authentication disabled",404)
    user,error=verify_local(request.form.get("username","").strip(),request.form.get("password",""))
    if not user:
        audit("LOGIN_FAILED",details={"provider":"local","username":request.form.get("username","")}); db.session.commit(); flash(error or "Sign-in failed","danger"); return redirect(url_for("auth.login"))
    login_user(user); user.last_login_at=utcnow(); audit("LOGIN_SUCCEEDED",details={"provider":"local"}); db.session.commit()
    return redirect(url_for("catalog.index"))

@bp.post("/ldap")
@limiter.limit("10 per minute")
def ldap_login():
    if not current_app.config["ENABLE_LDAP"]: return ("LDAP authentication disabled",404)
    user,error=authenticate_ldap(request.form.get("username","").strip(),request.form.get("password",""))
    if not user:
        audit("LOGIN_FAILED",details={"provider":"ldap","username":request.form.get("username","")}); db.session.commit(); flash(error or "Sign-in failed","danger"); return redirect(url_for("auth.login"))
    login_user(user); audit("LOGIN_SUCCEEDED",details={"provider":"ldap"}); db.session.commit()
    return redirect(url_for("catalog.index"))

@bp.get("/entra")
def entra_login():
    if not current_app.config["ENABLE_ENTRA"]: return ("Microsoft Entra authentication disabled",404)
    return redirect(begin_entra_flow())

@bp.get("/entra/callback")
def entra_callback():
    user,error=complete_entra_flow(request.args.to_dict(flat=True))
    if not user: flash(error or "Microsoft Entra sign-in failed","danger"); return redirect(url_for("auth.login"))
    login_user(user); audit("LOGIN_SUCCEEDED",details={"provider":"entra"}); db.session.commit(); return redirect(url_for("catalog.index"))

@bp.post("/logout")
def logout():
    if current_user.is_authenticated: audit("LOGOUT"); db.session.commit()
    logout_user(); return redirect(url_for("auth.login"))
