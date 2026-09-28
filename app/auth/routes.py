from flask import Blueprint,current_app,flash,redirect,render_template,request,url_for,session
from flask_login import current_user,login_required,login_user,logout_user
from email_validator import EmailNotValidError,validate_email
from ..extensions import db,limiter
from ..audit.service import audit
from ..models import AuthIdentity,DeploymentRequest,Server,utcnow
from .services import verify_local,set_local_password,authenticate_ldap,begin_entra_flow,complete_entra_flow
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
    session.pop("authenticated_identity_id",None)
    session["auth_provider"]="local"
    login_user(user); user.last_login_at=utcnow(); audit("LOGIN_SUCCEEDED",details={"provider":"local"}); db.session.commit()
    return redirect(url_for("catalog.index"))

@bp.post("/ldap")
@limiter.limit("10 per minute")
def ldap_login():
    if not current_app.config["ENABLE_LDAP"]: return ("LDAP authentication disabled",404)
    user,error=authenticate_ldap(request.form.get("username","").strip(),request.form.get("password",""))
    if not user:
        audit("LOGIN_FAILED",details={"provider":"ldap","username":request.form.get("username","")}); db.session.commit(); flash(error or "Sign-in failed","danger"); return redirect(url_for("auth.login"))
    session["auth_provider"]="ldap"
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
    session["auth_provider"]="entra"
    login_user(user); audit("LOGIN_SUCCEEDED",details={"provider":"entra"}); db.session.commit(); return redirect(url_for("catalog.index"))

def _local_password_change_allowed():
    return (current_app.config["ENABLE_LOCAL"] and session.get("auth_provider")=="local"
            and current_user.enabled and current_user.local_credential is not None)

def _profile_context():
    provider=session.get("auth_provider")
    identity_id=session.get("authenticated_identity_id")
    identity=db.session.get(AuthIdentity,identity_id) if isinstance(identity_id,int) else None
    if not identity or identity.user_id!=current_user.id or identity.provider!=provider:
        identity=None
    recent_requests=db.session.scalars(db.select(DeploymentRequest).where(
        DeploymentRequest.requested_by_id==current_user.id).order_by(
        DeploymentRequest.created_at.desc()).limit(5)).all()
    owned_servers=db.session.scalars(db.select(Server).where(
        (Server.technical_owner_id==current_user.id) | (Server.business_owner_id==current_user.id),
        Server.enabled.is_(True)).order_by(Server.name).limit(10)).all()
    return dict(provider=provider,verified_username=identity.authenticated_username if identity else None,
                can_edit=_local_password_change_allowed(),
                target_groups=sorted((g for g in current_user.server_groups if g.enabled),key=lambda g:g.name.casefold()),
                approval_groups=sorted((g for g in current_user.approval_groups if g.enabled),key=lambda g:g.name.casefold()),
                owned_servers=owned_servers,recent_requests=recent_requests)

@bp.get("/profile")
@login_required
def profile():
    if not current_user.enabled: return ("Account disabled",403)
    return render_template("auth/profile.html",**_profile_context())

@bp.post("/profile")
@login_required
def update_profile():
    if not _local_password_change_allowed(): return ("Local sign-in required",403)
    name=request.form.get("display_name","").strip()
    email=request.form.get("email","").strip()
    errors={}
    if not 1<=len(name)<=255:
        errors["display_name"]="Enter a display name of 1 to 255 characters."
    if email:
        try:
            email=validate_email(email,check_deliverability=False).normalized
            if len(email)>255: errors["email"]="Enter an email address of at most 255 characters."
        except EmailNotValidError:
            errors["email"]="Enter a valid email address."
    if errors:
        return render_template("auth/profile.html",**_profile_context(),form_errors=errors,
                               display_name_value=name,email_value=request.form.get("email","")),400
    changes=[]
    if name!=current_user.display_name:
        current_user.display_name=name; changes.append("display_name")
    if (email or None)!=current_user.email:
        current_user.email=email or None; changes.append("email")
    if changes:
        audit("PROFILE_UPDATED",entity_type="user",entity_id=current_user.id,
              details={"changed_fields":changes})
        db.session.commit()
        flash("Your profile was updated.","success")
    else:
        flash("Your profile is already up to date.","info")
    return redirect(url_for("auth.profile"))

@bp.get("/password")
@login_required
def password_form():
    if not _local_password_change_allowed(): return ("Local sign-in required",403)
    return render_template("auth/password.html")

@bp.post("/password")
@login_required
@limiter.limit("5 per minute")
def change_password():
    if not _local_password_change_allowed(): return ("Local sign-in required",403)
    current=request.form.get("current_password","")
    new=request.form.get("new_password","")
    confirmation=request.form.get("confirm_password","")
    if not current or not 14<=len(new)<=256 or new!=confirmation or new==current:
        flash("Enter your current password and a different new password of 14 to 256 characters, then confirm it.","danger")
        return redirect(url_for("auth.password_form"))
    user,error=verify_local(current_user.username,current)
    if not user:
        audit("LOCAL_PASSWORD_CHANGE_FAILED",entity_type="user",entity_id=current_user.id,
              details={"reason":"current_password_rejected"})
        db.session.commit()  # Persist failed attempts and the existing lockout policy.
        flash("Current password is incorrect or the account is temporarily locked.","danger")
        return redirect(url_for("auth.password_form"))
    set_local_password(current_user,new)
    audit("LOCAL_PASSWORD_CHANGED",entity_type="user",entity_id=current_user.id)
    db.session.commit()
    logout_user()
    session.clear()
    flash("Password changed. Sign in again with your new password.","success")
    return redirect(url_for("auth.login"))

@bp.post("/logout")
def logout():
    if current_user.is_authenticated: audit("LOGOUT"); db.session.commit()
    logout_user(); session.clear(); return redirect(url_for("auth.login"))
