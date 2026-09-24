import os

def env_bool(name: str, default: bool=False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1","true","yes","on"}

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE-ME")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "postgresql+psycopg://portal:portal@db:5432/portal")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_TYPE = "redis"
    SESSION_REDIS = None
    SESSION_COOKIE_NAME = "foreman_portal"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 3600
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = True
    WTF_CSRF_TIME_LIMIT = 3600

    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
    RATELIMIT_STORAGE_URI = REDIS_URL
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

    CHIKLET_DIRECTORY = os.getenv("CHIKLET_DIRECTORY", "/app/chiklets")
    DEFAULT_AUTH_PROVIDER = os.getenv("DEFAULT_AUTH_PROVIDER", "entra")
    ENABLE_ENTRA = env_bool("ENABLE_ENTRA", True)
    ENABLE_LDAP = env_bool("ENABLE_LDAP", True)
    ENABLE_LOCAL = env_bool("ENABLE_LOCAL", True)

    ENTRA_TENANT_ID = os.getenv("ENTRA_TENANT_ID", "")
    ENTRA_CLIENT_ID = os.getenv("ENTRA_CLIENT_ID", "")
    ENTRA_CLIENT_SECRET = os.getenv("ENTRA_CLIENT_SECRET", "")
    ENTRA_REDIRECT_URI = os.getenv("ENTRA_REDIRECT_URI", "https://localhost/auth/entra/callback")
    ENTRA_SCOPES = ["profile", "email"]
    ENTRA_AUTO_PROVISION = env_bool("ENTRA_AUTO_PROVISION", True)

    LDAP_URI = os.getenv("LDAP_URI", "ldaps://ad.example.com:636")
    LDAP_BASE_DN = os.getenv("LDAP_BASE_DN", "DC=example,DC=com")
    LDAP_BIND_DN = os.getenv("LDAP_BIND_DN", "")
    LDAP_BIND_PASSWORD = os.getenv("LDAP_BIND_PASSWORD", "")
    LDAP_USER_FILTER = os.getenv("LDAP_USER_FILTER", "(&(objectClass=user)(sAMAccountName={username}))")
    LDAP_USERNAME_ATTRIBUTE = os.getenv("LDAP_USERNAME_ATTRIBUTE", "sAMAccountName")
    LDAP_EMAIL_ATTRIBUTE = os.getenv("LDAP_EMAIL_ATTRIBUTE", "mail")
    LDAP_DISPLAYNAME_ATTRIBUTE = os.getenv("LDAP_DISPLAYNAME_ATTRIBUTE", "displayName")
    LDAP_TLS_VALIDATE = env_bool("LDAP_TLS_VALIDATE", True)
    LDAP_AUTO_PROVISION = env_bool("LDAP_AUTO_PROVISION", True)
    ALLOW_IDENTITY_AUTO_LINK = env_bool("ALLOW_IDENTITY_AUTO_LINK", False)

    FOREMAN_URL = os.getenv("FOREMAN_URL", "https://foreman.example.com")
    FOREMAN_USERNAME = os.getenv("FOREMAN_USERNAME", "")
    FOREMAN_PASSWORD = os.getenv("FOREMAN_PASSWORD", "")
    FOREMAN_API_TOKEN = os.getenv("FOREMAN_API_TOKEN", "")
    FOREMAN_CA_BUNDLE = os.getenv("FOREMAN_CA_BUNDLE", "")
    FOREMAN_VERIFY_TLS = env_bool("FOREMAN_VERIFY_TLS", True)
    FOREMAN_TIMEOUT_SECONDS = int(os.getenv("FOREMAN_TIMEOUT_SECONDS", "30"))
    FOREMAN_RECONCILE_INTERVAL_SECONDS = max(2.0, float(os.getenv("FOREMAN_RECONCILE_INTERVAL_SECONDS", "5")))
    FOREMAN_MOCK = env_bool("FOREMAN_MOCK", True)

    LOCAL_LOCKOUT_ATTEMPTS = int(os.getenv("LOCAL_LOCKOUT_ATTEMPTS", "5"))
    LOCAL_LOCKOUT_MINUTES = int(os.getenv("LOCAL_LOCKOUT_MINUTES", "15"))

    BOOTSTRAP_ADMIN_USERNAME = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "")
    BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "")

    TRUST_PROXY_HEADERS = env_bool("TRUST_PROXY_HEADERS", True)

class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    SESSION_TYPE = "filesystem"
    SQLALCHEMY_DATABASE_URI = "sqlite+pysqlite:///:memory:"
    FOREMAN_MOCK = True
    RATELIMIT_STORAGE_URI = "memory://"
