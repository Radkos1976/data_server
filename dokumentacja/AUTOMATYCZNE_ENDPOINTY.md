# Automatyczne Endpointy (Dynamic CRUD)

> **Co to jest i po co? (wyjaśnienie bez technikaliów)**
>
> Ten dokument opisuje, w jaki sposób system **udostępnia dane z bazy** aplikacjom, z którymi współpracuje (np. aplikacji frontendowej, integracji z innymi systemami).
>
> W skrócie:
> - Każda tabela danych w bazie jest automatycznie dostępna przez sieć — można **przeglądać, dodawać, edytować i usuwać rekordy** bez pisania osobnego kodu dla każdej tabeli.
> - Każda taka operacja wymaga **odpowiednich uprawnień** — to znaczy, że nie każdy użytkownik może np. usuwać dane.
> - Operacje zapisu (dodawanie, edytowanie, usuwanie) są przetwarzane **w tle**, żeby nie spowalniać odpowiedzi — użytkownik dostaje od razu potwierdzenie przyjęcia zlecenia, a wynik pojawia się po chwili.
> - System wysyła **powiadomienia w czasie rzeczywistym** (tzw. SSE), gdy dane zostaną zmienione — aplikacja frontendowa może od razu odświeżyć widok bez ręcznego odświeżania strony.
> - Liczba zapytań jest ograniczona (rate limiting), żeby nikt nie mógł przeciążyć serwera.

## Jak to działa

W `main.py` aplikacja iteruje po `MODELS` i dynamicznie rejestruje endpointy dla każdej tabeli:

- `GET /{table_name}`
- `POST /{table_name}`
- `PUT /{table_name}/{item_id}`
- `DELETE /{table_name}/{item_id}`

Dzięki temu nowe tabele są dostępne przez API bez ręcznego pisania kontrolerów.

Dotyczy to także tabel konfiguracyjnych watchera:
- `csv_watch_settings`
- `csv_watch_folders`

## Generowanie modeli

`MODELS` pochodzi z refleksji schematu bazy (`database.py`).

Każda tabela jest mapowana do klasy modelu i używana przez endpointy.

## Szczegóły endpointów

1. `GET /{table_name}`
- paginacja: `page`, `limit` lub `offset`, `limit`
- filtry budowane przez `build_filters(model, request)`
- zwraca: `total`, `pages`, `data`

2. `POST /{table_name}`
- zwraca `202`
- zleca zapis do tła przez Celery (`process_transaction`)
- zwraca `task_id`

3. `PUT /{table_name}/{item_id}`
- zwraca `202`
- zleca update do tła (`process_update_task`)
- zwraca `task_id`

4. `DELETE /{table_name}/{item_id}`
- zwraca `202`
- zleca delete do tła (`process_delete_task`)
- zwraca `task_id`

## Bezpieczeństwo

Każdy endpoint CRUD ma kontrolę dostępu przez:
- `require_permission(table_name, action)`

Mapowanie akcji:
- list/get: `GET`
- create: `POST`
- update: `PUT`
- delete: `DELETE`

## Rate limiting

FastAPI Limiter (Redis):
- GET: `100` żądań / `60s`
- POST: `10` żądań / `60s`
- PUT: `10` żądań / `60s`
- DELETE: `5` żądań / `60s`

## Format filtrów GET

Przykłady:

1. Dokładne dopasowanie:
- `?username=john`

2. Wiele wartości (OR):
- `?status=active,inactive`
- `?status=active&status=inactive`

3. LIKE:
- `?email__like=*@gmail.com`

4. Null:
- `?some_field=null`

## SSE powiadomienia

`GET /stream` subskrybuje kanał Redis `global_updates`.

Zdarzenia (przykłady):
- `SUCCESS:table:id:task_id`
- `UPDATED:table:id:task_id`
- `DELETED:table:id:task_id`
- `ERROR:table:id:task_id:message`

## Uwaga na obejmowanie wszystkich tabel

Ponieważ CRUD jest generowany dla całego `MODELS`, endpointy pojawią się także dla tabel infrastrukturalnych (np. `roles`, `permissions`, `logs`, `imports_*`), o ile są w refleksji.

Uprawnienia i rate limits ograniczają ryzyko, ale warto świadomie zarządzać tabelą `permissions`.

W aktualnym seedzie konfiguracja watchera (`csv_watch_settings`, `csv_watch_folders`) jest ograniczona do roli `admin`.
