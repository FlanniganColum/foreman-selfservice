from flask import current_app
from ..extensions import db
from ..models import Server,ServerGroup,utcnow
from ..foreman.client import ForemanClient
def sync_hosts():
    if current_app.config["FOREMAN_MOCK"]:
        fallback=db.session.scalar(db.select(ServerGroup).where(ServerGroup.slug=="demo"))
        if not fallback: fallback=ServerGroup(slug="demo",name="Demo Servers",description="Local mock inventory"); db.session.add(fallback); db.session.flush()
        demo=[(1001,"demo-app-01.example.net","10.10.0.11"),(1002,"demo-app-02.example.net","10.10.0.12")]
        for hid,name,ip in demo:
            s=db.session.scalar(db.select(Server).where(Server.foreman_host_id==hid))
            if not s: s=Server(foreman_host_id=hid,name=name,ip_address=ip,group=fallback); db.session.add(s)
            s.last_synced_at=utcnow()
        db.session.commit(); return len(demo)
    data=ForemanClient()._request("GET","/api/hosts",params={"per_page":"all"}); results=data.get("results",[])
    fallback=db.session.scalar(db.select(ServerGroup).where(ServerGroup.slug=="unassigned"))
    if not fallback: fallback=ServerGroup(slug="unassigned",name="Unassigned",description="Imported from Foreman and awaiting assignment"); db.session.add(fallback); db.session.flush()
    for h in results:
        s=db.session.scalar(db.select(Server).where(Server.foreman_host_id==h["id"]))
        if not s: s=Server(foreman_host_id=h["id"],name=h["name"],group=fallback); db.session.add(s)
        s.name=h["name"]; s.ip_address=h.get("ip"); s.foreman_metadata={"hostgroup_name":h.get("hostgroup_name"),"environment_name":h.get("environment_name")}; s.last_synced_at=utcnow()
    db.session.commit(); return len(results)
