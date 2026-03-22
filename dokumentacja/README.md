# Dokumentacja Systemu

> **Krótko o systemie (bez żargonu technicznego)**
>
> Ten system to serwer danych, który umożliwia firmie:
> - **wczytywanie zamówień / planów produkcji z plików Excel/CSV** — wystarczy wyeksportować dane do pliku i wgrać go przez aplikację,
> - **automatyczne sprawdzenie poprawności danych** — system sam wykrywa błędy (np. brak kodu produktu, zła jednostka, zduplikowane pozycje) i informuje, które wiersze wymagają poprawki,
> - **śledzenie, kto i kiedy wgrał plik** — każda operacja jest zapisywana,
> - **kontrolę dostępu** — każdy użytkownik ma przypisaną rolę i może robić tylko to, na co mu ona pozwala,
> - **automatyczne wykrywanie nowych plików w folderze** — można wskazać folder na serwerze, a system sam przetworzy każdy nowy plik CSV.

Ten katalog zawiera aktualną dokumentację projektu.

## Zanim zaczniesz: Setup

Przed przeczytaniem dokumentacji zapoznaj się z **[SETUP.md](../SETUP.md)** w głównym folderze — zawiera instrukcje:
- Uruchamiania aplikacji **lokalnie (VSC + WSL2)** lub **w Dockerze**
- Konfiguracja `.env` dla obu środowisk
- Struktura i persystencja danych (PostgreSQL, Redis, foldery importu CSV poza kontenerem)
- Troubleshooting

## Spis dokumentacji

1. `IMPORT_SQL_NATIVE.md`
Opis działania importu CSV w architekturze SQL-native, wraz z watcherem folderów CSV.

2. `UWIERZYTELNIANIE_I_ROLE.md`
JWT, odświeżanie tokenów, role i uprawnienia.

3. `AUTOMATYCZNE_ENDPOINTY.md`
Jak działają automatyczne endpointy CRUD generowane dynamicznie.

