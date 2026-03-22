# Import CSV (SQL Native)

> **Co to jest i po co? (wyjaśnienie bez technikaliów)**
>
> Ten moduł służy do **wczytywania danych z pliku CSV** (np. wyeksportowanego z Excela) do systemu.
>
> Jak to wygląda w praktyce:
> 1. Użytkownik wgrywa plik CSV przez aplikację (lub umieszcza go w wyznaczonym folderze na serwerze).
> 2. System automatycznie **sprawdza każdy wiersz** — czy ma wszystkie wymagane pola, czy jednostka jest prawidłowa, czy data jest w dozwolonym formacie.
> 3. Wiersze poprawne **trafiają do bazy** i są od razu dostępne.
> 4. Wiersze z błędami **nie są odrzucane bezpowrotnie** — system zapisuje je osobno z opisem błędu, żeby można było poprawić dane i wgrać ponownie.
> 5. Jeśli ten sam plik zostanie wgrany drugi raz, system go **rozpozna i nie zdubluje danych**.
> 6. Cały przebieg importu (kto wgrał, ile wierszy OK, ile błędów) jest **zapisywany w historii**.

## Cel

Import CSV jest realizowany synchronicznie przez PostgreSQL:
- staging w `TEMP TABLE ... ON COMMIT DROP`
- walidacja i podział danych w funkcji PL/pgSQL `process_import_temp`
- zapis poprawnych rekordów do `imports_data`
- zapis błędów do `imports_errors`

## Tabele

1. `imports_files`
- metadane pliku (`filename`, `file_checksum`, `processed_by`)
- podsumowanie (`total_rows`, `ok_rows`, `error_rows`, `warning_type`)
- znaczniki czasu (`processed_at`, `completed_at`)

2. `import_units`
- słownik dozwolonych jednostek (`unit_code`, `is_active`)
- walidacja `unit` opiera się o tę tabelę (bez list hardcoded)

3. `imports_data`
- rekordy poprawne
- `unit` ma FK do `import_units(unit_code)`

4. `imports_errors`
- rekordy błędne i ich powód (`error_reason`, `error_type`)

## Pipeline

1. `POST /imports` przyjmuje plik CSV.
2. Wyliczany jest `SHA256` i sprawdzany duplikat po (`filename`, `file_checksum`).
3. Tworzona jest `TEMP TABLE temp_import_<id> ... ON COMMIT DROP`.
4. CSV ładowany przez `COPY` do temp table.
5. Wywołanie: `SELECT ok_count, error_count, warning_type FROM process_import_temp(temp_table, import_id)`.
6. Aktualizacja `imports_files` (`processed_at`, `completed_at`, liczniki).
7. `COMMIT` usuwa tabelę tymczasową automatycznie.

## Walidacje (PL/pgSQL)

1. `external_id` nie może być puste.
2. `product_code` nie może być puste.
3. `quantity` musi być dodatnią liczbą całkowitą.
4. `unit` musi istnieć w `import_units` i być aktywne (`is_active = TRUE`).
5. `planned_date` akceptuje formaty:
- `YYYY-MM-DD`
- `DD.MM.YYYY`
- `DD-MM-YYYY`
- `DD/MM/YYYY`
6. Duplikat `external_id` w pliku => błąd.
7. Duplikat `external_id` w `imports_data` => błąd.
8. `warning_type = POSSIBLE_DUPLICATE_BATCH`, jeśli >3 rekordy z tym samym `product_code` w rekordach poprawnych.

## CSV: kodowanie, separator, nagłówki

Detekcja po stronie aplikacji (`import_native.py`):

1. Kodowanie (kolejność prób):
- `utf-8-sig`
- `utf-8`
- `cp1250`
- `iso-8859-2`

2. Separator (auto-detekcja):
- `;`, `,`, `\t`, `|`

3. Nagłówki są walidowane strict (dokładna lista i kolejność):
- `external_id,product_code,quantity,unit,planned_date,comment`

## Endpointy importu

1. `POST /imports`
- upload i uruchomienie importu

2. `GET /imports`
- lista importów (paginacja)

3. `GET /imports/{import_id}`
- szczegóły importu

4. `GET /imports/{import_id}/errors`
- rekordy błędne

5. `GET /imports/{import_id}/data`
- rekordy poprawne

6. `GET /imports/watcher/status`
- status runtime watchera i konfiguracja z bazy

Wszystkie endpointy wymagają JWT (`Depends(get_current_user)`).
Endpoint `GET /imports/watcher/status` jest dodatkowo ograniczony do roli `admin`.

## Watcher folderu CSV (cykliczny import)

Możesz włączyć automatyczne skanowanie wielu katalogów pod kątem nowych/zmienionych plików CSV.

Konfiguracja watchera jest przechowywana w bazie danych.

1. Tabela `csv_watch_settings`
- `watch_enabled` - globalny przełącznik watchera
- `scheduler_interval_seconds` - interwał głównej pętli watchera

2. Tabela `csv_watch_folders`
- `directory_path` - ścieżka folderu
- `is_active` - czy folder jest aktywny
- `interval_seconds` - interwał skanowania dla konkretnego folderu
- `import_user` - użytkownik zapisywany w `imports_files.processed_by`
- pola statusowe: `last_scan_at`, `last_scan_file_count`, `last_detected_files`, `last_imported_files`, `last_error`

Env służy tylko do bootstrapu (seed):

1. `CSV_WATCH_ENABLED`
2. `CSV_WATCH_DIRECTORY`
3. `CSV_WATCH_INTERVAL_SECONDS`
4. `CSV_WATCH_IMPORT_USER`

Działanie:

1. Watcher uruchamia się przy starcie API (`lifespan`) i działa w tle.
2. Co `scheduler_interval_seconds` pobiera aktywną konfigurację z DB.
3. Skanuje wszystkie foldery aktywne, każdy według własnego `interval_seconds`.
4. Importuje tylko nowe/zmienione pliki (detekcja po `mtime` + `size`).
5. Dodatkowa ochrona przed duplikatami działa po checksum w `imports_files`.
6. Sam task watchera jest uruchamiany przy starcie API i pozostaje aktywny nawet gdy `watch_enabled = FALSE`; wtedy po prostu nic nie importuje.
7. Zmiana `csv_watch_settings.watch_enabled` na `TRUE` jest podchwytywana bez restartu aplikacji przy następnym obiegu pętli watchera.

Endpoint statusowy:

1. `GET /imports/watcher/status`
- `runtime`: czy watcher działa, ostatnia pętla, ostatni błąd, ostatnia liczba wykrytych/zaimportowanych plików
- `settings`: wartości z `csv_watch_settings`
- `folders`: lista folderów z `csv_watch_folders` i ich ostatnimi metrykami

## Logowanie

Import CSV zapisuje zdarzenia w dwóch miejscach:

### Tabela `logs` (identyczna jak dla zadań Celery)

Każde wywołanie `import_csv_native` tworzy trzy wpisy o `task_name = csv_import`:

| Status | Kiedy zapisywany |
|--------|-----------------|
| `STARTED` | po założeniu rekordu w `imports_files` |
| `SUCCESS` | po zwróceniu wyników przez `process_import_temp`, przed COMMIT |
| `ERROR` | na wyjątku, po rollback (przez osobne połączenie) |

Pole `username` zawiera użytkownika, który zainicjował import (z JWT lub `import_user` watchera).
Możliwe filtrowania: `GET /logs?task_name=csv_import`, `GET /logs?username=...`.

### Tabela `access_logs`

Endpoint `POST /imports` zapisuje zdarzenie przez `log_access`:
- sukces (`200`): `method=POST`, `path=/imports`, opis `ok_rows` / `error_rows`
- duplikat (`200`): informacja o poprzednim `import_id`
- błąd (`500`): komunikat wyjątku

### Stdout logger

Wszystkie trzy moduły emitują logi do standardowego loggera Pythona:

| Moduł | Poziom | Zdarzenie |
|-------|--------|-----------|
| `import_native` | INFO | STARTED, SUCCESS + liczniki |
| `import_native` | ERROR | awaria importu |
| `import_native_routes` | INFO | ALREADY_PROCESSED, COMPLETED |
| `import_native_routes` | ERROR | błąd endpointu |
| `csv_folder_watcher` | INFO | COMPLETED, ALREADY_PROCESSED per plik |
| `csv_folder_watcher` | WARNING | nieznany status importu |
| `csv_folder_watcher` | ERROR | wyjątek watchera |

---

## Zarządzanie watcherem przez automatyczny CRUD

Tabele watchera są dostępne także przez dynamiczny CRUD:

1. `csv_watch_settings`
2. `csv_watch_folders`

Uprawnienia do obu tabel są seedowane jako `admin` dla wszystkich operacji `GET`, `POST`, `PUT`, `DELETE`.

W praktyce oznacza to, że:

1. tylko admin może zmieniać konfigurację watchera,
2. tylko admin może dodawać lub wyłączać foldery,
3. tylko admin może odczytywać status watchera przez endpoint statusowy.

Przykład `.env`:

```env
CSV_WATCH_ENABLED=true
CSV_WATCH_DIRECTORY=/data/incoming_csv
CSV_WATCH_INTERVAL_SECONDS=60
CSV_WATCH_IMPORT_USER=folder_watcher
```
