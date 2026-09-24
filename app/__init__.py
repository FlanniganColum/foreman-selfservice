from flask import Flask,render_template
from redis import Redis
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import text
from .config import Config
from .extensions import db,migrate,login_manager,csrf,server_session,limiter
from .models import User
from .jobs.celery_app import make_celery
def create_app(config_object=Config):
    app=Flask(__name__); app.config.from_object(config_object)
    if app.config["SESSION_TYPE"]=="redis": app.config["SESSION_REDIS"]=Redis.from_url(app.config["REDIS_URL"])
    if app.config["TRUST_PROXY_HEADERS"]: app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=1)
    db.init_app(app); migrate.init_app(app,db); login_manager.init_app(app); csrf.init_app(app); server_session.init_app(app); limiter.init_app(app)
    login_manager.login_view="auth.login"; login_manager.session_protection="strong"
    @login_manager.user_loader
    def load_user(user_id): return db.session.get(User,int(user_id))
    from .auth.routes import bp as auth_bp
    from .catalog.routes import bp as catalog_bp
    from .requests.routes import bp as requests_bp
    from .approvals.routes import bp as approvals_bp
    from .admin.routes import bp as admin_bp
    from .api import bp as api_bp
    from .audit.routes import bp as audit_bp
    for bp in (auth_bp,catalog_bp,requests_bp,approvals_bp,admin_bp,audit_bp,api_bp): app.register_blueprint(bp)
    from .cli import register_cli
    register_cli(app)
    @app.get("/health/live")
    def health_live(): return {"status":"ok"},200
    @app.get("/health/ready")
    def health_ready():
        try: db.session.execute(text("SELECT 1")); return {"status":"ready"},200
        except Exception: return {"status":"not-ready"},503
    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options","nosniff"); resp.headers.setdefault("X-Frame-Options","DENY"); resp.headers.setdefault("Referrer-Policy","strict-origin-when-cross-origin"); resp.headers.setdefault("Permissions-Policy","camera=(), microphone=(), geolocation=()"); resp.headers.setdefault("Content-Security-Policy","default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'"); return resp
    @app.errorhandler(403)
    def forbidden(e): return render_template("errors/403.html"),403
    @app.errorhandler(404)
    def not_found(e): return render_template("errors/404.html"),404
    @app.errorhandler(500)
    def server_error(e): return render_template("errors/500.html"),500
    make_celery(app); return app
