import ssl, msal
from datetime import timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from flask import current_app, session
from ldap3 import Server, Connection, ALL, SUBTREE, Tls
from ldap3.utils.conv import escape_filter_chars
from ..extensions import db
from ..models import User, AuthIdentity, LocalCredential, utcnow

ph=PasswordHasher(time_cost=3,memory_cost=65536,parallelism=4)

def set_local_password(user,password):
    cred=user.local_credential or LocalCredential(user=user,password_hash="")
    cred.password_hash=ph.hash(password); cred.failed_attempts=0; cred.locked_until=None; cred.password_changed_at=utcnow(); db.session.add(cred)

def verify_local(username,password):
    cfg=current_app.config
    user=db.session.scalar(db.select(User).where(User.username==username))
    if not user or not user.enabled or not user.local_credential: return None,"Invalid username or password"
    cred=user.local_credential; now=utcnow()
    if cred.locked_until and cred.locked_until>now: return None,"Account temporarily locked"
    try:
        ph.verify(cred.password_hash,password)
        if ph.check_needs_rehash(cred.password_hash): cred.password_hash=ph.hash(password)
        cred.failed_attempts=0; cred.locked_until=None
        return user,None
    except (VerifyMismatchError,InvalidHashError):
        cred.failed_attempts+=1
        if cred.failed_attempts>=cfg["LOCAL_LOCKOUT_ATTEMPTS"]:
            cred.locked_until=now+timedelta(minutes=cfg["LOCAL_LOCKOUT_MINUTES"]); cred.failed_attempts=0
        return None,"Invalid username or password"

def _ldap_service_connection():
    cfg=current_app.config
    tls=Tls(validate=ssl.CERT_REQUIRED if cfg["LDAP_TLS_VALIDATE"] else ssl.CERT_NONE)
    server=Server(cfg["LDAP_URI"],get_info=ALL,tls=tls)
    if cfg["LDAP_BIND_DN"]: return Connection(server,user=cfg["LDAP_BIND_DN"],password=cfg["LDAP_BIND_PASSWORD"],auto_bind=True)
    return Connection(server,auto_bind=True)

def authenticate_ldap(username,password):
    cfg=current_app.config
    if not password: return None,"Password required"
    try:
        service=_ldap_service_connection()
        filt=cfg["LDAP_USER_FILTER"].format(username=escape_filter_chars(username))
        attrs=[cfg["LDAP_USERNAME_ATTRIBUTE"],cfg["LDAP_EMAIL_ATTRIBUTE"],cfg["LDAP_DISPLAYNAME_ATTRIBUTE"]]
        if not service.search(cfg["LDAP_BASE_DN"],filt,SUBTREE,attributes=attrs) or not service.entries:
            service.unbind(); return None,"Invalid username or password"
        entry=service.entries[0]; user_dn=entry.entry_dn; server=service.server; service.unbind()
        probe=Connection(server,user=user_dn,password=password,auto_bind=True); probe.unbind()
        directory_username=str(entry[cfg["LDAP_USERNAME_ATTRIBUTE"]].value or username)
        email=str(entry[cfg["LDAP_EMAIL_ATTRIBUTE"]].value or "") or None
        display_name=str(entry[cfg["LDAP_DISPLAYNAME_ATTRIBUTE"]].value or directory_username)
        ident=db.session.scalar(db.select(AuthIdentity).where(AuthIdentity.provider=="ldap",AuthIdentity.subject==user_dn))
        if ident: user=ident.user
        elif cfg["LDAP_AUTO_PROVISION"]:
            user=db.session.scalar(db.select(User).where(User.username==directory_username))
            if user and not cfg["ALLOW_IDENTITY_AUTO_LINK"]:
                return None,"An account with this username already exists under another identity provider; an administrator must resolve the identity mapping"
            if not user:
                user=User(username=directory_username,email=email,display_name=display_name); db.session.add(user); db.session.flush()
            db.session.add(AuthIdentity(user=user,provider="ldap",subject=user_dn))
        else: return None,"Account is not provisioned"
        if not user.enabled: return None,"Account is disabled"
        user.email=email or user.email; user.display_name=display_name or user.display_name; user.last_login_at=utcnow()
        return user,None
    except Exception:
        current_app.logger.exception("LDAP authentication failed"); return None,"Directory authentication failed"

def _msal_app():
    cfg=current_app.config
    return msal.ConfidentialClientApplication(cfg["ENTRA_CLIENT_ID"],authority=f"https://login.microsoftonline.com/{cfg['ENTRA_TENANT_ID']}",client_credential=cfg["ENTRA_CLIENT_SECRET"])

def begin_entra_flow():
    flow=_msal_app().initiate_auth_code_flow(scopes=current_app.config["ENTRA_SCOPES"],redirect_uri=current_app.config["ENTRA_REDIRECT_URI"])
    session["entra_flow"]=flow
    return flow["auth_uri"]

def complete_entra_flow(auth_response):
    try: result=_msal_app().acquire_token_by_auth_code_flow(session.pop("entra_flow",{}),auth_response)
    except ValueError: return None,"Invalid or expired authentication response"
    if "error" in result: return None,result.get("error_description","Microsoft Entra authentication failed")
    claims=result.get("id_token_claims",{}); subject=claims.get("oid") or claims.get("sub"); username=claims.get("preferred_username") or claims.get("email") or subject
    if not subject or not username: return None,"Entra token is missing required identity claims"
    ident=db.session.scalar(db.select(AuthIdentity).where(AuthIdentity.provider=="entra",AuthIdentity.subject==subject))
    if ident: user=ident.user
    elif current_app.config["ENTRA_AUTO_PROVISION"]:
        user=db.session.scalar(db.select(User).where(User.username==username))
        if user and not current_app.config["ALLOW_IDENTITY_AUTO_LINK"]:
            return None,"An account with this username already exists under another identity provider; an administrator must resolve the identity mapping"
        if not user:
            user=User(username=username,email=claims.get("email") or claims.get("preferred_username"),display_name=claims.get("name") or username); db.session.add(user); db.session.flush()
        db.session.add(AuthIdentity(user=user,provider="entra",subject=subject))
    else: return None,"Account is not provisioned"
    if not user.enabled: return None,"Account is disabled"
    user.display_name=claims.get("name") or user.display_name; user.email=claims.get("email") or claims.get("preferred_username") or user.email; user.last_login_at=utcnow()
    return user,None
