from flask import Blueprint,abort,flash,redirect,render_template,request,url_for
from flask_login import login_required,current_user
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import joinedload
from ..extensions import db
from ..models import User,ServerGroup,Server
from ..audit.service import audit
from ..auth.services import set_local_password
bp=Blueprint("admin",__name__,url_prefix="/admin")
def admin_required(global_only=False):
    allowed={"global_admin"} if global_only else {"admin","global_admin"}
    if current_user.role not in allowed: abort(403)

@bp.get("/")
@login_required
def index():
    admin_required()
    counts=dict(db.session.execute(db.select(Server.group_id,func.count(Server.id)).group_by(Server.group_id)).all())
    return render_template("admin/index.html",users=db.session.scalars(db.select(User).order_by(User.username)).all(),groups=db.session.scalars(db.select(ServerGroup).order_by(ServerGroup.name)).all(),group_counts=counts)

def _server_filters(source):
    search=source.get("q","").strip()[:160]
    group_id=source.get("group_id","").strip()
    environment=source.get("environment","").strip()[:120]
    status=source.get("status","").strip()
    if group_id and (not group_id.isdigit() or len(group_id)>12): abort(400)
    if status not in {"","enabled","disabled"}: abort(400)
    return {"q":search,"group_id":group_id,"environment":environment,"status":status}

def _servers_redirect():
    filters=_server_filters({"q":request.form.get("filter_q",""),
                             "group_id":request.form.get("filter_group_id",""),
                             "environment":request.form.get("filter_environment",""),
                             "status":request.form.get("filter_status","")})
    page=request.form.get("page","1")
    if not page.isdigit() or len(page)>9 or int(page)<1: page="1"
    return redirect(url_for("admin.servers",**filters,page=page))

@bp.get("/servers")
@login_required
def servers():
    admin_required()
    filters=_server_filters(request.args)
    search=filters["q"]
    conditions=[]
    if search:
        term=search.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
        pattern=f"%{term}%"
        conditions.append(or_(Server.name.ilike(pattern,escape="\\"),
                              Server.ip_address.ilike(pattern,escape="\\"),
                              cast(Server.foreman_host_id,String).ilike(pattern,escape="\\")))
    if filters["group_id"]: conditions.append(Server.group_id==int(filters["group_id"]))
    if filters["environment"]: conditions.append(Server.environment==filters["environment"])
    if filters["status"]: conditions.append(Server.enabled.is_(filters["status"]=="enabled"))
    page_raw=request.args.get("page","1")
    page=int(page_raw) if page_raw.isdigit() and len(page_raw)<=9 and int(page_raw)>0 else 1
    per_page=25
    total=db.session.scalar(db.select(func.count(Server.id)).where(*conditions))
    pages=max(1,(total+per_page-1)//per_page)
    page=min(page,pages)
    records=db.session.scalars(db.select(Server).options(
        joinedload(Server.group),joinedload(Server.technical_owner),joinedload(Server.business_owner)
    ).where(*conditions).order_by(Server.name,Server.id).limit(per_page).offset((page-1)*per_page)).all()
    groups=db.session.scalars(db.select(ServerGroup).order_by(ServerGroup.name)).all()
    environments=db.session.scalars(db.select(Server.environment).where(
        Server.environment.is_not(None),Server.environment!="").distinct().order_by(Server.environment)).all()
    users=db.session.scalars(db.select(User).where(User.enabled.is_(True)).order_by(User.username)).all()
    return render_template("admin/servers.html",servers=records,groups=groups,
                           environments=environments,users=users,total=total,page=page,pages=pages,
                           **filters)

@bp.post("/groups")
@login_required
def create_group():
    admin_required(); slug=request.form.get("slug","").strip().lower(); name=request.form.get("name","").strip()
    if not slug or not name: abort(400)
    if db.session.scalar(db.select(ServerGroup).where(ServerGroup.slug==slug)): flash("Server group already exists.","danger")
    else:
        g=ServerGroup(slug=slug,name=name,description=request.form.get("description","").strip() or None); db.session.add(g); db.session.flush(); audit("SERVER_GROUP_CREATED",entity_type="server_group",entity_id=g.id,details={"slug":slug}); db.session.commit(); flash("Server group created.","success")
    return redirect(url_for("admin.index"))

@bp.post("/users/<int:user_id>/access")
@login_required
def update_user_access(user_id):
    admin_required(True); user=db.session.get(User,user_id)
    if not user: abort(404)
    role=request.form.get("role","user")
    if role not in {"user","approver","linux_admin","admin","auditor","global_admin"}: abort(400)
    user.role=role; gids={int(x) for x in request.form.getlist("server_group_ids")}; agids={int(x) for x in request.form.getlist("approval_group_ids")}
    user.server_groups=list(db.session.scalars(db.select(ServerGroup).where(ServerGroup.id.in_(gids or {-1}))).all()); user.approval_groups=list(db.session.scalars(db.select(ServerGroup).where(ServerGroup.id.in_(agids or {-1}))).all())
    audit("USER_ACCESS_CHANGED",entity_type="user",entity_id=user.id,details={"role":role,"server_groups":sorted(gids),"approval_groups":sorted(agids)}); db.session.commit(); flash("Access updated.","success"); return redirect(url_for("admin.index"))

@bp.post("/servers/<int:server_id>/group")
@login_required
def assign_server_group(server_id):
    admin_required(); server=db.session.get(Server,server_id); group=db.session.get(ServerGroup,int(request.form["group_id"]))
    if not server or not group: abort(404)
    server.group=group; audit("SERVER_GROUP_ASSIGNMENT_CHANGED",entity_type="server",entity_id=server.id,details={"server":server.name,"group":group.slug}); db.session.commit(); flash("Server assignment updated.","success"); return _servers_redirect()

@bp.post("/servers/<int:server_id>/owners")
@login_required
def assign_server_owners(server_id):
    admin_required()
    server = db.session.get(Server, server_id)
    if not server:
        abort(404)
    owners = {}
    for kind in ("technical", "business"):
        raw = request.form.get(f"{kind}_owner_id", "").strip()
        if raw:
            try:
                owner = db.session.get(User, int(raw))
            except ValueError:
                abort(400)
            if not owner or not owner.enabled:
                abort(400)
            owners[kind] = owner.id
        else:
            owners[kind] = None
    server.technical_owner_id = owners["technical"]
    server.business_owner_id = owners["business"]
    audit("SERVER_OWNERS_CHANGED", entity_type="server", entity_id=server.id,
          details={"technical_owner_id": owners["technical"], "business_owner_id": owners["business"]})
    db.session.commit()
    flash("Server owners updated.", "success")
    return _servers_redirect()

@bp.post("/local-users")
@login_required
def create_local_user():
    admin_required(True); username=request.form.get("username","").strip(); password=request.form.get("password","")
    if not username or len(password)<14: flash("Username required and password must be at least 14 characters.","danger"); return redirect(url_for("admin.index"))
    if db.session.scalar(db.select(User).where(User.username==username)): flash("User already exists.","danger"); return redirect(url_for("admin.index"))
    user=User(username=username,email=request.form.get("email","").strip() or None,display_name=request.form.get("display_name","").strip() or username,role="user"); db.session.add(user); db.session.flush(); set_local_password(user,password); audit("LOCAL_USER_CREATED",entity_type="user",entity_id=user.id); db.session.commit(); flash("Local user created.","success"); return redirect(url_for("admin.index"))

@bp.post("/foreman/sync")
@login_required
def sync_foreman():
    admin_required(); from ..jobs.inventory import sync_hosts
    count=sync_hosts(); flash(f"Synchronized {count} Foreman hosts.","success"); return redirect(url_for("admin.servers"))
