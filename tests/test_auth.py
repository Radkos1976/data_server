"""
Testy autoryzacji: login, token, refresh, dostęp bez tokenu.
"""
from tests.conftest import BASE_URL, ADMIN_USER, ADMIN_PASS, _post_token


class TestLogin:
    def test_login_success(self, client):
        """Poprawny login zwraca access_token i refresh_token."""
        resp = _post_token(BASE_URL, ADMIN_USER, ADMIN_PASS)
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"


class TestTokenRefresh:
    def test_refresh_returns_new_token(self, client, refresh_token):
        """Refresh token generuje nowy access_token."""
        resp = client.post(f"/refresh?refresh_token={refresh_token}")
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data

    def test_refresh_invalid_token(self, client):
        """Nieprawidłowy refresh token zwraca 401."""
        resp = client.post("/refresh?refresh_token=nieprawidlowy.token.tutaj")
        assert resp.status_code in (401, 422)

    def test_refresh_access_token_not_accepted(self, client, admin_token):
        """Access token jako refresh token powinien być odrzucony (inny typ)."""
        resp = client.post(f"/refresh?refresh_token={admin_token}")
        assert resp.status_code == 401


class TestProtectedEndpoints:
    def test_access_without_token_returns_401(self, client):
        """Dostęp do chronionych endpointów bez tokenu zwraca 401."""
        resp = client.get("/roles")
        assert resp.status_code == 401

    def test_access_with_invalid_token_returns_401(self, client):
        """Nieprawidłowy token zwraca 401."""
        resp = client.get("/roles", headers={"Authorization": "Bearer bledny.token"})
        assert resp.status_code == 401

    def test_access_with_valid_token_succeeds(self, client, admin_headers):
        """Prawidłowy token admina pozwala na dostęp."""
        resp = client.get("/roles", headers=admin_headers)
        assert resp.status_code == 200

    def test_access_logs_requires_admin(self, client, admin_headers):
        """Endpoint access_logs wymaga uprawnień admina."""
        resp = client.get("/access_logs", headers=admin_headers)
        assert resp.status_code == 200
