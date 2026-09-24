import pytest, shutil
from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import User,ServerGroup,Server
from app.auth.services import set_local_password
@pytest.fixture
def app(tmp_path):
    class C(TestConfig): CHIKLET_DIRECTORY=str(tmp_path/"chiklets")
    (tmp_path/"chiklets").mkdir(); shutil.copy("chiklets/deploy-web-application.json",tmp_path/"chiklets/deploy-web-application.json")
    app=create_app(C)
    with app.app_context():
        db.create_all(); g1=ServerGroup(slug="demo",name="Demo"); g2=ServerGroup(slug="secret",name="Secret")
        u=User(username="alice",role="user",display_name="Alice"); set_local_password(u,"correct horse battery staple")
        a=User(username="approver",role="approver",display_name="Approver"); set_local_password(a,"correct horse battery staple")
        admin=User(username="root",role="global_admin"); set_local_password(admin,"correct horse battery staple")
        db.session.add_all([g1,g2,u,a,admin]); db.session.flush(); u.server_groups.append(g1); a.approval_groups.append(g1)
        db.session.add_all([Server(foreman_host_id=1,name="demo01",group=g1),Server(foreman_host_id=2,name="secret01",group=g2)]); db.session.commit()
    yield app
@pytest.fixture
def client(app): return app.test_client()
def login(client,username): return client.post("/auth/local",data={"username":username,"password":"correct horse battery staple"},follow_redirects=True)
