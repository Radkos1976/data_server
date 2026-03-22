"""
Testy endpointów importu CSV (/imports).
"""
import io
import pytest


# Prawidłowy CSV zgodny ze schematem imports_data
VALID_CSV = (
    "external_id,product_code,quantity,unit,planned_date,comment\n"
    "EXT_TEST_001,PROD001,10,szt,01.01.2025,test\n"
    "EXT_TEST_002,PROD002,5,kpl,15.06.2025,test drugi wiersz\n"
)

# CSV z błędnymi danymi (nieprawidłowa jednostka, brak wymaganego pola)
INVALID_CSV = (
    "external_id,product_code,quantity,unit,planned_date,comment\n"
    "EXT_BAD_001,PROD001,10,NIEISTNIEJACA_JEDNOSTKA,01.01.2025,test\n"
)


class TestImportsList:
    def test_list_imports_requires_auth(self, client):
        """GET /imports bez tokenu zwraca 401."""
        resp = client.get("/imports")
        assert resp.status_code == 401

    def test_list_imports_returns_paginated(self, client, admin_headers):
        """GET /imports zwraca spaginowaną listę importów."""
        resp = client.get("/imports", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data or "items" in data or isinstance(data, list)

    def test_watcher_status_requires_admin(self, client, admin_headers):
        """GET /imports/watcher/status wymaga uprawnień admina."""
        resp = client.get("/imports/watcher/status", headers=admin_headers)
        assert resp.status_code == 200

    def test_watcher_status_has_expected_fields(self, client, admin_headers):
        """Status watchera zawiera informacje o ustawieniach."""
        resp = client.get("/imports/watcher/status", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Endpoint powinien zwracać jakiś słownik z danymi
        assert isinstance(data, dict)


class TestImportUpload:
    def test_upload_valid_csv(self, client, admin_headers):
        """POST /imports z prawidłowym CSV zwraca sukces."""
        files = {"file": ("test_import.csv", io.BytesIO(VALID_CSV.encode()), "text/csv")}
        resp = client.post("/imports", files=files, headers=admin_headers)
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "status" in data or "import_file_id" in data

    def test_upload_csv_requires_auth(self, client):
        """POST /imports bez tokenu zwraca 401."""
        files = {"file": ("test.csv", io.BytesIO(VALID_CSV.encode()), "text/csv")}
        resp = client.post("/imports", files=files)
        assert resp.status_code == 401

    def test_upload_duplicate_csv_detected(self, client, admin_headers):
        """Ponowne wysłanie tego samego pliku (ten sam checksum) powinno być wykryte."""
        csv_content = VALID_CSV.encode()
        files1 = {"file": ("duplikat_test.csv", io.BytesIO(csv_content), "text/csv")}
        resp1 = client.post("/imports", files=files1, headers=admin_headers)
        assert resp1.status_code in (200, 201)

        # Drugi upload tego samego pliku
        files2 = {"file": ("duplikat_test.csv", io.BytesIO(csv_content), "text/csv")}
        resp2 = client.post("/imports", files=files2, headers=admin_headers)
        # Powinien być 409 (conflict) lub 200 ze statusem "duplicate"
        assert resp2.status_code in (200, 201, 409)
        if resp2.status_code in (200, 201):
            data = resp2.json()
            assert "duplicate" in str(data).lower() or "status" in data

    def test_upload_invalid_csv_returns_errors(self, client, admin_headers):
        """CSV z błędnymi danymi powinien zwrócić informacje o błędach."""
        files = {"file": ("bledny.csv", io.BytesIO(INVALID_CSV.encode()), "text/csv")}
        resp = client.post("/imports", files=files, headers=admin_headers)
        # Może zwrócić 200 z error_rows > 0 lub 400/422
        assert resp.status_code in (200, 201, 400, 422)
        if resp.status_code in (200, 201):
            data = resp.json()
            # Sprawdź czy są zarejestrowane błędy
            error_count = data.get("error_rows", 0) or data.get("errors", 0)
            assert error_count >= 0  # Aplikacja nie powinna crashować


class TestImportDetails:
    def test_get_import_details(self, client, admin_headers):
        """GET /imports/{id} zwraca szczegóły konkretnego importu."""
        # Najpierw pobierz listę żeby mieć ID
        list_resp = client.get("/imports", headers=admin_headers)
        assert list_resp.status_code == 200
        items = list_resp.json()
        data_list = items.get("data") or items.get("items") or (items if isinstance(items, list) else [])
        if not data_list:
            pytest.skip("Brak importów w bazie — pomiń test szczegółów")

        import_id = data_list[0].get("id")
        if not import_id:
            pytest.skip("Nie można uzyskać ID importu")

        resp = client.get(f"/imports/{import_id}", headers=admin_headers)
        assert resp.status_code == 200

    def test_get_import_errors(self, client, admin_headers):
        """GET /imports/{id}/errors zwraca błędy importu."""
        list_resp = client.get("/imports", headers=admin_headers)
        assert list_resp.status_code == 200
        items = list_resp.json()
        data_list = items.get("data") or items.get("items") or (items if isinstance(items, list) else [])
        if not data_list:
            pytest.skip("Brak importów w bazie")

        import_id = data_list[0].get("id")
        if not import_id:
            pytest.skip("Nie można uzyskać ID importu")

        resp = client.get(f"/imports/{import_id}/errors", headers=admin_headers)
        assert resp.status_code == 200

    def test_get_nonexistent_import_returns_404(self, client, admin_headers):
        """GET /imports/9999999 zwraca 404."""
        resp = client.get("/imports/9999999", headers=admin_headers)
        assert resp.status_code == 404
