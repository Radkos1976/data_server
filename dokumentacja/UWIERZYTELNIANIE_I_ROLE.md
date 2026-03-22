# Uwierzytelnianie, Role i Uprawnienia

> **Co to jest i po co? (wyjaśnienie bez technikaliów)**
>
> Ten dokument opisuje, w jaki sposób system **sprawdza, kto to jest i co mu wolno robić**.
>
> W skrócie:
> - Żeby korzystać z systemu, trzeba się **zalogować** podając login i hasło. W odpowiedzi system wystawia **bilet wstępu** (token) ważny przez określony czas.
> - Każde kolejne zapytanie do systemu musi zawierać ten bilet — bez niego system odmawia dostępu.
> - Bilet można **odświeżyć** bez ponownego logowania, dzięki czemu sesja nie wygasa nieoczekiwanie.
> - Każdy użytkownik ma przypisaną **rolę** (np. admin, kierownik, użytkownik, gość). Rola decyduje, co dana osoba może robić — np. tylko admin może zmieniać konfigurację automatycznego importu, a gość może tylko przeglądać dane.
> - Wszystkie próby logowania i odmowy dostępu są **zapisywane w historii** (kto, kiedy, z jakiego adresu).

## Uwierzytelnianie (JWT)

System używa OAuth2 Bearer Token.

## Endpointy auth

1. `POST /token`
- logowanie przez `OAuth2PasswordRequestForm`
- zwraca:
  - `access_token`
  - `refresh_token`
  - `token_type = bearer`

2. `POST /refresh`
- przyjmuje `refresh_token`
- zwraca nowy `access_token`

## Access token

Tworzony funkcją `create_access_token`.

Payload:
- `sub` = username
- `exp` = czas wygaśnięcia

Czas życia:
- `ACCESS_TOKEN_EXPIRE_MINUTES` z konfiguracji.

## Refresh token

Tworzony funkcją `create_refresh_token`.

Payload:
- `sub` = username
- `exp` = czas wygaśnięcia
- `type` = `refresh`

Czas życia:
- `REFRESH_TOKEN_EXPIRE_DAYS` z konfiguracji.

Walidacja przez `validate_refresh_token` sprawdza m.in. `type == refresh`.

## Weryfikacja użytkownika

`get_current_user`:
1. Pobiera token z nagłówka `Authorization: Bearer ...`.
2. Dekoduje JWT (`SECRET_KEY`, `ALGORITHM`).
3. Odczytuje `sub` i zwraca username.
4. Przy błędzie zwraca `401`.

## Role

Role i ich siła są przechowywane w tabeli `roles`:
- `name`
- `power`

Przykładowe role seed:
- `admin` (100)
- `manager` (50)
- `user` (10)
- `guest` (0)

## Uprawnienia per tabela i akcja

Tabela `permissions` definiuje minimalną rolę dla:
- `table_name`
- `action` (`GET`, `POST`, `PUT`, `DELETE`)
- `required_role`

Przykłady tabel ograniczonych do admina:
- `access_logs`
- `csv_watch_settings`
- `csv_watch_folders`

Funkcja `require_permission(table_name, action)`:
1. Pobiera username z `get_current_user`.
2. Wyznacza wymaganą rolę dla akcji.
3. Porównuje `user_power >= required_power`.
4. Przy braku uprawnień zwraca `403`.

## Fallback uprawnień

Jeśli wpisu brak w `permissions`, używany jest fallback:
- `GET -> guest`
- `POST -> user`
- `PUT -> user`
- `DELETE -> manager`
- inne -> `admin`

## Logowanie zdarzeń

Operacje auth/authz zapisują zdarzenia przez `log_access` (np. sukces logowania, odmowa dostępu).

## Ważna uwaga operacyjna

`ROLE_HIERARCHY` i `PERMISSIONS_DICT` są ładowane przy starcie procesu.
Po zmianach w tabelach `roles` lub `permissions` restart aplikacji odświeży cache w pamięci.

To dotyczy także zmian uprawnień dla watchera folderów CSV.
