# Setup i Uruchamianie Aplikacji

Aplikacja może działać w dwóch środowiskach: **lokalnie (VSC + WSL2)** lub **w Dockerze**. Ścieżki do bazy danych i folderów importu są automatycznie dostosowywane w zależności od wybranego środowiska.

## Struktura folderów

```
/home/radkos/data_server/          # Główny folder aplikacji
├── .env.local                      # Konfiguracja dla środowiska lokalnego
├── .env.docker                     # Konfiguracja dla Dockera
├── docker-compose.yml              # Setup Postgres + Redis + App w Dockerze
├── Dockerfile                      # Obraz aplikacji
├── data/                           # (Utworży się po uruchomieniu)
│   ├── postgres_data/              # Dane PostgreSQL (poza kontenerem)
│   ├── redis_data/                 # Dane Redis (poza kontenerem)
│   ├── imports_input/              # Foldery CSV do importu (poza kontenerem)
│   └── app_logs/                   # Logi aplikacji (opcjonalnie)
├── main.py
├── config.py
├── import_native.py
└── ...
```

---

## Uruchamianie LOKALNIE (VSC + WSL2)

### Warunki wstępne

1. **PostgreSQL** zainstalowany i uruchomiony na `localhost:5432`
   ```bash
   # Sprawdzenie
   psql -U postgres
   ```

2. **Redis** zainstalowany i uruchomiony na `localhost:6379`
   ```bash
   # Sprawdzenie
   redis-cli ping
   # Odpowiedź: PONG
   ```

3. **Python 3.12+** i venv
   ```bash
   python3 --version
   ```

### Krok 1: Konfiguracja

```bash
# Skopiuj plik lokalnej konfiguracji (jeśli go nie masz)
cp .env.local .env

# (Opcjonalnie) Edytuj, jeśli domyślne hasła Postgresa się różnią
# nano .env
```

Zmieniaj tylko te wartości w `.env` (jeśli różnią się od rzeczywistych):
- `DB_PASSWORD` — hasło użytkownika `moj_uzytkownik` w Postgresie
- `ADMIN_DB_PASSWORD` — hasło admina `postgres` w Postgresie
- `CSV_WATCH_DIRECTORY` — ścieżka do folderu, z którego watcher będzie czytać CSV (na WSL)

### Krok 2: Instalacja zależności

```bash
# Aktywuj venv (jeśli nie jest aktywny)
source .venv/bin/activate

# Zainstaluj/odśwież pakiety
pip install -r requirements.txt
```

### Krok 3: Inicjalizacja bazy danych

```bash
# Tworzy tabele, roli, seeduje domyślne dane
python -m feed_db
```

### Krok 4: Uruchomienie serwera

```bash
# VSC: Ctrl+Shift+` — otworz terminal (WSL2)
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Aplikacja będzie dostępna na: **http://localhost:8000**

### Sprawdzenie dokumentacji API

```
http://localhost:8000/docs
```

---

## Uruchamianie W DOCKERZE

### SZYBKI START - Skrypt interaktywny

**Najprostszy sposób** — użyj skryptu `setup-docker.sh`:

```bash
chmod +x setup-docker.sh
./setup-docker.sh
```

Skrypt:
1. **Pyta o ścieżki** — gdzie przechowywać dane PostgreSQL, Redis i importy CSV
2. **Pamiętać ścieżki** — zapisuje je w `.env.docker.paths`
3. **Przy ponownym uruchomieniu** — oferuje opcję załadowania poprzednich ścieżek
4. **Tworzy foldery** — automatycznie i sprawdza uprawnienia zapisu
5. **Uruchamia Docker** — z prawidłową konfiguracją

Przykład (pierwsze uruchomienie):
```
=== Setup Docker - Data Server ===

Opcje:
  1) Skonfiguruj nowe ścieżki
  2) Użyj poprzedniej konfiguracji (jeśli istnieje)
  3) Zmień ścieżki
  4) Wyjdź

Wybierz opcję [1-4]: 1

=== Konfiguracja ścieżek ===

Ścieżka do danych PostgreSQL: [domyślnie: /home/radkos/data_server/data/postgres_data]: 
Ścieżka do danych Redis: [domyślnie: /home/radkos/data_server/data/redis_data]: 
Ścieżka do importu CSV: [domyślnie: /home/radkos/data_server/data/imports_input]: 

=== Weryfikacja ścieżek ===
✓ PostgreSQL: /home/radkos/data_server/data/postgres_data
✓ Redis: /home/radkos/data_server/data/redis_data
✓ CSV import: /home/radkos/data_server/data/imports_input

Czy chcesz uruchomić Docker? (y/n) [y]: y

=== Uruchamianie Docker Compose ===
[docker-compose uruchamia się...]
```

Przykład (drugie uruchomienie — używa memoratora):
```
=== Setup Docker - Data Server ===

Obecna konfiguracja:
PostgreSQL data:  /home/radkos/data_server/data/postgres_data
Redis data:       /home/radkos/data_server/data/redis_data
CSV import:       /home/radkos/data_server/data/imports_input

Opcje:
  1) Skonfiguruj nowe ścieżki
  2) Użyj poprzedniej konfiguracji (jeśli istnieje)  ← wybieraj to
  3) Zmień ścieżki
  4) Wyjdź

Wybierz opcję [1-4]: 2
✓ Załadowana poprzednia konfiguracja
```

### Tryb automatyczny (dla zaawansowanych użytkowników)

Jeśli chcesz uruchomić Docker z ostatnią konfigurацją bez pytań:

```bash
./setup-docker.sh --auto
```

To jest przydatne w skryptach CI/CD lub automatycznym starcie.

---

### Ręczna konfiguracja (alternatywa do skryptu)

Jeśli wolisz ręcznie, przejdź do kroku poniżej.

### Warunki wstępne

1. **Docker** zainstalowany
   ```bash
   docker --version
   ```

2. **Docker Compose** zainstalowany
   ```bash
   docker-compose --version
   ```

### Krok 1: Konfiguracja

```bash
# Nie musisz nic robić — .env.docker jest już przygotowany
# ale możesz sprawdzić i edytować jeśli potrzeba
cat .env.docker
```

---

### Architektura konfiguracji w Dockerze

Hasła i zmienne środowiskowe w Dockerze są **centralizowane w `.env.docker`** i automatycznie propagowane:

```
.env.docker (źródło prawdy)
    ↓
    ├─→ docker-compose.yml (usługa postgres)
    │   └─→ POSTGRES_PASSWORD=${ADMIN_DB_PASSWORD}
    │
    ├─→ docker-compose.yml (usługa app)
    │   └─→ env_file: .env.docker
    │
    ├─→ config.py (wewnątrz kontenera)
    │   └─→ os.getenv("ADMIN_DB_PASSWORD")
    │
    └─→ feed_db.py (seed - inicjalizacja bazy)
        └─→ os.getenv("DB_PASSWORD") -> tworzy użytkownika
```

**Nie edytuj haseł w `docker-compose.yml`** — zmień je w `.env.docker`, a docker-compose je automatycznie podchwyci.

---

### Krok 2: Uruchomienie

```bash
# Uruchom wszystkie serwisy (Postgres, Redis, App)
docker-compose up --build

# (--build: przebuduj obraz aplikacji za każdym razem)
# (bez flagi: uruchom istniejące kontenery)

# W tle (daemon mode):
docker-compose up -d --build
```

### Krok 3: Sprawdzenie stanu

```bash
# Lista kontenerów
docker-compose ps

# Logi aplikacji
docker-compose logs -f app

# Logi Postgresa
docker-compose logs -f postgres

# Logi Redisa
docker-compose logs -f redis
```

### Krok 4: Dostęp do aplikacji

```
http://localhost:8000
http://localhost:8000/docs
```

### Zatrzymanie

```bash
# Zatrzymaj wszystkie serwisy
docker-compose down

# (opcjonalnie) Usuń też volume-y (usunie dane!)
# docker-compose down -v
```

---

## Kluczowe różnice między środowiskami

| Aspekt | Lokalne (WSL2) | Docker |
|--------|---|---|
| Database host | `localhost` | `postgres` (Docker DNS) |
| Database port | `5432` | `5432` (wewnątrz sieci Dockera) |
| Redis host | `localhost` | `redis` (Docker DNS) |
| CSV import folder | Lokalna ścieżka WSL (np `/home/radkos/...`) | Volume mount (np `/data/imports_input`) |
| Plik .env | `.env.local` → `.env` | `.env.docker` (automatycznie przez docker-compose) |
| Data persystencja | Gdy PostgreSQL uruchomiony lokalnie | Foldery `./data/postgres_data`, `./data/redis_data` |

---

## Importowanie CSV z folderu (watcher)

### Lokalne uruchamianie

1. Ustaw w `.env`:
   ```
   CSV_WATCH_ENABLED=true
   CSV_WATCH_DIRECTORY=/home/radkos/data_server/imports_input
   ```

2. Utwórz folder:
   ```bash
   mkdir -p /home/radkos/data_server/imports_input
   ```

3. Wrzuć plik CSV do folderu — watcher go automatycznie przetworzy (co 30 sekund).

### Docker

1. Już skonfigurowane — `CSV_WATCH_DIRECTORY=/data/imports_input`

2. Umieść plik CSV na hoście:
   ```bash
   cp plik.csv ./data/imports_input/
   ```

3. Watcher w kontenerze go przetworzy automatycznie.

---

## Troubleshooting

### Błąd: `Connection refused` na PostgreSQL

**Lokalnie:**
```bash
# Sprawdź, czy Postgres jest uruchomiony
sudo systemctl status postgresql

# Lub jeśli używasz bez sudo:
psql -U postgres -h localhost
```

**Docker:**
```bash
# Sprawdź, czy kontener postgres jest uruchomiony
docker-compose ps postgres

# Sprawdź logi
docker-compose logs postgres
```

### Błąd: Port już zajęty

**Lokalnie:**
```bash
# Zmień port w .env
DB_PORT=5433  # zamiast 5432
```

**Docker:**
Edytuj `docker-compose.yml`:
```yaml
postgres:
  ports:
    - "5433:5432"  # port_na_hoście:port_w_kontenerze
```

### Błąd: Nie mogę się połączyć do aplikacji

```bash
# Sprawdź, czy aplikacja słucha
lsof -i :8000  # lokalnie
docker-compose logs app  # w Dockerze
```

---

## Zmiana haseł dla produkcji

**WAŻNE:** Zmień wszystkie domyślne hasła zanim wdrożysz na produkację!

1. **W `.env.local`/`.env.docker`:**
   ```
   DB_PASSWORD=nowe_sile_haslo_bazy
   ADMIN_DB_PASSWORD=nowe_haslo_admina
   SECRET_KEY=nowy_tajny_klucz_jwt_minimum_32_znaki
   ```

2. **Przestart aplikacji:**
   ```bash
   # Lokalnie: Ctrl+C + ponownie uvicorn
   # Docker: docker-compose down && docker-compose up
   ```

---

## Backup danych

### Lokalnie (PostgreSQL)

```bash
# Dump bazy
pg_dump -U moj_uzytkownik -h localhost moja_baza > backup.sql

# Restore
psql -U moj_uzytkownik -h localhost moja_baza < backup.sql
```

### Docker

```bash
# Dump z kontenera
docker-compose exec postgres pg_dump -U postgres moja_baza > backup.sql

# Restore
docker-compose exec -T postgres psql -U postgres moja_baza < backup.sql

# Backup całego volume-u
docker run --rm -v data_server_postgres_data:/data --mount type=bind,source=/tmp,target=/backup \
  alpine tar czf /backup/postgres_backup.tar.gz /data
```

---

## Dalsze kroki

- Dokumentacja API: http://localhost:8000/docs
- Importowanie CSV: `POST /imports`  lub watcher folder
- Logowanie: `POST /token` → otrzymaj access_token
- Role i uprawnienia: dokumentacja w [UWIERZYTELNIANIE_I_ROLE.md](./UWIERZYTELNIANIE_I_ROLE.md)
