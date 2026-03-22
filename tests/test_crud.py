"""
Testy dynamicznych endpointów CRUD (auto-generowanych na podstawie schematu DB).
Używamy tabeli 'roles' — zawsze istnieje po inicjalizacji (feed_db.py).
"""
import pytest


class TestGetList:
    def test_get_roles_returns_list(self, client, admin_headers):
        """GET /roles zwraca spaginowaną listę ról."""
        resp = client.get("/roles", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data
        assert isinstance(data["data"], list)

    def test_get_roles_has_seeded_data(self, client, admin_headers):
        """feed_db.py tworzy 4 domyślne role (admin, manager, user, guest)."""
        resp = client.get("/roles", headers=admin_headers)
        assert resp.status_code == 200
        names = [r["name"] for r in resp.json()["data"]]
        for role in ("admin", "manager", "user", "guest"):
            assert role in names

    def test_get_users_contains_admin(self, client, admin_headers):
        """Tabela users zawiera domyślnego admina."""
        resp = client.get("/users", headers=admin_headers)
        assert resp.status_code == 200
        usernames = [u["username"] for u in resp.json()["data"]]
        assert "admin" in usernames

    def test_pagination_limit(self, client, admin_headers):
        """Parametr ?limit ogranicza liczbę wyników."""
        resp = client.get("/roles?limit=2", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) <= 2
        assert data["limit"] == 2

    def test_pagination_page(self, client, admin_headers):
        """Parametr ?page działa poprawnie."""
        resp = client.get("/roles?page=1&limit=2", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1

    def test_filter_exact_value(self, client, admin_headers):
        """Filtrowanie po dokładnej wartości (?name=admin)."""
        resp = client.get("/roles?name=admin", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1
        assert all(r["name"] == "admin" for r in data)

    def test_filter_like(self, client, admin_headers):
        """Filtrowanie przez LIKE (?name__like=*min*)."""
        resp = client.get("/roles?name__like=*min*", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert any("min" in r["name"] for r in data)

    def test_nonexistent_table_returns_404(self, client, admin_headers):
        """Nieistniejąca tabela zwraca 404."""
        resp = client.get("/nieistniejaca_tabela", headers=admin_headers)
        assert resp.status_code == 404


class TestCreateAndDelete:
    def test_post_creates_record(self, client, admin_headers):
        """POST /roles tworzy nowy rekord i zwraca task_id."""
        payload = {"name": "test_role_do_usuniecia", "power": 5}
        resp = client.post("/roles", json=payload, headers=admin_headers)
        assert resp.status_code in (200, 201, 202)
        data = resp.json()
        assert "task_id" in data

    def test_post_without_auth_returns_401(self, client):
        """POST bez tokenu zwraca 401."""
        resp = client.post("/roles", json={"name": "test_unauth", "power": 5})
        assert resp.status_code == 401


class TestUpdateAndReadback:
    def test_get_import_units(self, client, admin_headers):
        """Tabela import_units zawiera domyślne jednostki miary (szt, kpl, m2)."""
        resp = client.get("/import_units", headers=admin_headers)
        assert resp.status_code == 200
        codes = [u["unit_code"] for u in resp.json()["data"]]
        for unit in ("szt", "kpl", "m2"):
            assert unit in codes
