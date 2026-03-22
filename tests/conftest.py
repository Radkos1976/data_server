"""
Fixtures dla testów integracyjnych.
Testy działają przeciwko działającej instancji Docker (localhost:8000).
Uruchom Docker przed testami: docker compose up -d
"""
"""
Fixtures dla testów integracyjnych.
Testy działają przeciwko działającej instancji Docker (localhost:8000).
Uruchom Docker przed testami: docker compose up -d
"""
import time
import pytest
import httpx

BASE_URL = "http://localhost:8000"
ADMIN_USER = "admin"
ADMIN_PASS = "admin"


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
