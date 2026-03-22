"""
Negatywne testy logowania — uruchamiaj OSOBNO lub PO teście sesji.
Każdy test uderza w /token i konsumuje slot rate limitera (5/60s).

Aby uruchomić tylko te testy:
    pytest tests/test_z_auth_negative.py -v

UWAGA: Po wyczerpaniu limitu poczekaj 60 sekund.
"""
import time
import pytest


class TestLoginNegative:
    def test_login_wrong_password(self, client):
        """Błędne hasło zwraca 401."""
        resp = client.post("/token", data={"username": "admin", "password": "bledne_haslo"})
        assert resp.status_code in (401, 429)

    def test_login_wrong_username(self, client):
        """Nieistniejący użytkownik zwraca 401."""
        resp = client.post("/token", data={"username": "uzytkownik_ktory_nie_istnieje", "password": "cokolwiek"})
        assert resp.status_code in (401, 429)

    def test_login_missing_fields(self, client):
        """Brak pól formularza zwraca 422 (walidacja FastAPI, przed rate limiterm)."""
        resp = client.post("/token", data={})
        assert resp.status_code == 422

    def test_login_empty_password(self, client):
        """Puste hasło zwraca 401 lub 422."""
        resp = client.post("/token", data={"username": "admin", "password": ""})
        assert resp.status_code in (401, 422, 429)
