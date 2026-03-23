"""
Fixtures dla testów integracyjnych.
Testy działają przeciwko działającej instancji Docker (localhost:8000).
Uruchom Docker przed testami: docker compose up -d
"""
import os
import time
from pathlib import Path

import psycopg2
import pytest
import httpx

BASE_URL = "http://localhost:8000"
ADMIN_USER = "admin"
ADMIN_PASS = "admin"
TEST_ROLE_NAME = "test_role_do_usuniecia"
TEST_IMPORT_FILENAMES = (
    "test_import.csv",
    "duplikat_test.csv",
    "bledny.csv",
)
TEST_EXTERNAL_PREFIXES = ("EXT_TEST_%", "EXT_BAD_%")


def _db_params():
    env_file = Path(".env.docker")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

    return {
        "dbname": os.getenv("DB_NAME", "moja_baza"),
        "user": os.getenv("DB_USER", "moj_uzytkownik"),
        "password": os.getenv("DB_PASSWORD", "silne_haslo123"),
        "host": os.getenv("DB_HOST", "localhost"),
        "port": os.getenv("DB_PORT", "5432"),
    }


def _cleanup_test_data():
    conn = psycopg2.connect(**_db_params())
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM imports_errors
                WHERE import_file_id IN (
                    SELECT id FROM imports_files WHERE filename = ANY(%s)
                )
                OR external_id LIKE %s
                OR external_id LIKE %s
                """,
                (list(TEST_IMPORT_FILENAMES), TEST_EXTERNAL_PREFIXES[0], TEST_EXTERNAL_PREFIXES[1]),
            )
            cur.execute(
                """
                DELETE FROM imports_data
                WHERE import_file_id IN (
                    SELECT id FROM imports_files WHERE filename = ANY(%s)
                )
                OR external_id LIKE %s
                OR external_id LIKE %s
                """,
                (list(TEST_IMPORT_FILENAMES), TEST_EXTERNAL_PREFIXES[0], TEST_EXTERNAL_PREFIXES[1]),
            )
            cur.execute(
                "DELETE FROM imports_files WHERE filename = ANY(%s)",
                (list(TEST_IMPORT_FILENAMES),),
            )
            cur.execute(
                "DELETE FROM roles WHERE name = %s",
                (TEST_ROLE_NAME,),
            )
        conn.commit()
    finally:
        conn.close()


def _post_token(base_url: str, username: str, password: str, retries: int = 3, wait: int = 65):
    """Pobiera token z obsługą rate limit (429 → czeka i ponawia)."""
    with httpx.Client(base_url=base_url) as c:
        for attempt in range(retries):
            resp = c.post("/token", data={"username": username, "password": password})
            if resp.status_code == 429 and attempt < retries - 1:
                time.sleep(wait)
                continue
            return resp
    return resp


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_data_session():
    """Czyści testowe rekordy przed i po sesji testowej."""
    try:
        _cleanup_test_data()
    except psycopg2.Error as e:
        # Nie blokuj sesji testowej jeśli cleanup nie może połączyć się z DB.
        print(f"[tests cleanup] skip pre-cleanup: {e}")
    yield
    try:
        _cleanup_test_data()
    except psycopg2.Error as e:
        print(f"[tests cleanup] skip post-cleanup: {e}")


@pytest.fixture(scope="session")
def client():
    """Synchroniczny klient HTTP do testów."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token():
    """Token JWT admina (pobierany raz na całą sesję testową)."""
    resp = _post_token(BASE_URL, ADMIN_USER, ADMIN_PASS)
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    """Nagłówki HTTP z tokenem admina."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def refresh_token():
    """Refresh token admina (pobierany raz na sesję)."""
    resp = _post_token(BASE_URL, ADMIN_USER, ADMIN_PASS)
    assert resp.status_code == 200, f"Login for refresh_token failed: {resp.text}"
    return resp.json()["refresh_token"]
