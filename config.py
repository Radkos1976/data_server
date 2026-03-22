import os

from sqlalchemy.engine import URL


DB_NAME = os.getenv("DB_NAME", "moja_baza")
DB_USER = os.getenv("DB_USER", "moj_uzytkownik")
DB_PASSWORD = os.getenv("DB_PASSWORD", "silne_haslo123")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))

ADMIN_DB_NAME = os.getenv("ADMIN_DB_NAME", "postgres")
ADMIN_DB_USER = os.getenv("ADMIN_DB_USER", "postgres")
ADMIN_DB_PASSWORD = os.getenv("ADMIN_DB_PASSWORD", "twoje_haslo_admina")
ADMIN_DB_HOST = os.getenv("ADMIN_DB_HOST", DB_HOST)
ADMIN_DB_PORT = os.getenv("ADMIN_DB_PORT", str(DB_PORT))

SECRET_KEY = os.getenv("SECRET_KEY", "BARDZO_TAJNY_KLUCZ_1234567890")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CELERY_DB = int(os.getenv("REDIS_CELERY_DB", "0"))
REDIS_SSE_DB = int(os.getenv("REDIS_SSE_DB", "1"))
REDIS_LIMITER_DB = int(os.getenv("REDIS_LIMITER_DB", "2"))

CSV_WATCH_ENABLED = os.getenv("CSV_WATCH_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
CSV_WATCH_DIRECTORY = os.getenv("CSV_WATCH_DIRECTORY", "")
CSV_WATCH_INTERVAL_SECONDS = int(os.getenv("CSV_WATCH_INTERVAL_SECONDS", "30"))
CSV_WATCH_IMPORT_USER = os.getenv("CSV_WATCH_IMPORT_USER", "system_watcher")

DB_URL_ASYNC = os.getenv("DB_URL_ASYNC") or URL.create(
    "postgresql+asyncpg",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
).render_as_string(hide_password=False)

DB_URL_SYNC = os.getenv("DB_URL_SYNC") or URL.create(
    "postgresql",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
).render_as_string(hide_password=False)

ADMIN_DB_PARAMS = {
    "dbname": ADMIN_DB_NAME,
    "user": ADMIN_DB_USER,
    "password": ADMIN_DB_PASSWORD,
    "host": ADMIN_DB_HOST,
    "port": ADMIN_DB_PORT,
}


def redis_url(db: int) -> str:
    return f"redis://{REDIS_HOST}:{REDIS_PORT}/{db}"