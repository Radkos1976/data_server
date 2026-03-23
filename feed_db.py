import os
import sys
import psycopg2
from psycopg2 import sql
import time
import bcrypt
from config import ADMIN_DB_PARAMS
from config import CSV_WATCH_ENABLED, CSV_WATCH_DIRECTORY, CSV_WATCH_INTERVAL_SECONDS, CSV_WATCH_IMPORT_USER


# Dane docelowe
NEW_USER = os.getenv("DB_USER", "moj_uzytkownik")
NEW_PASS = os.getenv("DB_PASSWORD", "silne_haslo123")
NEW_DB = os.getenv("DB_NAME", "moja_baza")


def wait_for_db(params, retries=20, delay=2):
    """Pętla oczekująca na gotowość bazy danych."""
    print("Oczekiwanie na gotowość PostgreSQL...")
    for i in range(retries):
        try:
            conn = psycopg2.connect(**params)
            conn.close()
            print("PostgreSQL jest gotowy!")
            return True
        except psycopg2.OperationalError:
            print(f"Baza jeszcze nie odpowiada... (próba {i + 1}/{retries})")
            time.sleep(delay)
    print("Nie udało się połączyć z bazą danych.")
    return False


def setup_database():
    # Najpierw czekamy na start serwera
    if not wait_for_db(ADMIN_DB_PARAMS):
        return False

    try:
        # 1. Połączenie jako admin (z autocommit dla CREATE DB/USER)
        conn = psycopg2.connect(**ADMIN_DB_PARAMS)
        conn.autocommit = True
        cur = conn.cursor()

        # 2. Tworzenie użytkownika (jeśli nie istnieje)
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (NEW_USER,))
        if not cur.fetchone():
            cur.execute(sql.SQL("CREATE USER {} WITH PASSWORD %s").format(
                sql.Identifier(NEW_USER)), [NEW_PASS]
            )
            print(f"Użytkownik '{NEW_USER}' utworzony.")

        # 3. Tworzenie bazy danych (jeśli nie istnieje)
        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (NEW_DB,))
        if not cur.fetchone():
            cur.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(NEW_DB), sql.Identifier(NEW_USER)
            ))
            print(f"Baza danych '{NEW_DB}' utworzona.")

        cur.close()
        conn.close()

        # 4. Łączenie z nową bazą i tworzenie tabeli
        conn = psycopg2.connect(dbname=NEW_DB, user=NEW_USER, password=NEW_PASS,
                                host=ADMIN_DB_PARAMS["host"], port=ADMIN_DB_PARAMS["port"])
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50) UNIQUE NOT NULL,
                power INTEGER NOT NULL
            );
        """)

        # Wstawienie domyślnych ról
        cur.execute("""
            INSERT INTO roles (name, power) VALUES
            ('admin', 100),
            ('manager', 50),
            ('user', 10),
            ('guest', 0)
            ON CONFLICT (name) DO NOTHING;
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                hashed_password TEXT NOT NULL,
                role_id INTEGER REFERENCES roles(id),
                is_active BOOLEAN DEFAULT TRUE,
                data_rejestracji TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            DO $$
            BEGIN
                CREATE TYPE task_status AS ENUM ('STARTED', 'SUCCESS', 'ERROR');
            EXCEPTION
                WHEN duplicate_object THEN NULL;
            END $$;
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS permissions (
                id SERIAL PRIMARY KEY,
                table_name VARCHAR(50) NOT NULL,
                action VARCHAR(10) NOT NULL,
                required_role VARCHAR(50) NOT NULL
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS access_logs (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                username VARCHAR(50),
                method VARCHAR(10),       -- GET, POST, PUT, DELETE
                path VARCHAR(255),
                status_code INTEGER,
                user_agent TEXT,
                ip_address INET,
                detail TEXT               -- dodatkowe szczegóły, np. błąd autoryzacji
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                task_id VARCHAR(255) NOT NULL,
                task_name VARCHAR(255) NOT NULL,
                status task_status NOT NULL,
                message TEXT,
                username VARCHAR(50),  -- Dodane dla użytkownika zlecającego
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Tabele dla SQL Native CSV Import
        cur.execute("""
            CREATE TABLE IF NOT EXISTS imports_files (
                id SERIAL PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                file_checksum VARCHAR(64) NOT NULL,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                total_rows INTEGER,
                ok_rows INTEGER,
                error_rows INTEGER,
                warning_type VARCHAR(50),
                processed_by VARCHAR(100),
                UNIQUE(filename, file_checksum)
            );
        """)

        cur.execute("""
            ALTER TABLE imports_files
            ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;
        """)

        # Słownik dozwolonych jednostek (rozszerzalny)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS import_units (
                unit_code VARCHAR(20) PRIMARY KEY,
                description VARCHAR(255),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            INSERT INTO import_units (unit_code, description, is_active) VALUES
            ('szt', 'Sztuki', TRUE),
            ('kpl', 'Komplet', TRUE),
            ('m2', 'Metry kwadratowe', TRUE)
            ON CONFLICT (unit_code) DO NOTHING;
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS imports_data (
                id SERIAL PRIMARY KEY,
                import_file_id INTEGER NOT NULL REFERENCES imports_files(id),
                external_id VARCHAR(255) NOT NULL UNIQUE,
                product_code VARCHAR(255) NOT NULL,
                quantity INTEGER NOT NULL,
                unit VARCHAR(20) NOT NULL REFERENCES import_units(unit_code),
                planned_date DATE NOT NULL,
                comment TEXT,
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS imports_errors (
                id SERIAL PRIMARY KEY,
                import_file_id INTEGER NOT NULL REFERENCES imports_files(id),
                row_number INTEGER,
                external_id VARCHAR(255),
                product_code VARCHAR(255),
                quantity VARCHAR(50),
                unit VARCHAR(50),
                planned_date VARCHAR(50),
                comment TEXT,
                error_reason TEXT NOT NULL,
                error_type VARCHAR(20),
                warning_type VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Indeksy dla wydajności
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_imports_files_checksum
            ON imports_files(filename, file_checksum);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_imports_data_file_id
            ON imports_data(import_file_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_import_units_active
            ON import_units(is_active);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_imports_errors_file_id
            ON imports_errors(import_file_id);
        """)

        # Konfiguracja watchera CSV (DB-driven)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS csv_watch_settings (
                id SMALLINT PRIMARY KEY CHECK (id = 1),
                watch_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                scheduler_interval_seconds INTEGER NOT NULL DEFAULT 5,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            INSERT INTO csv_watch_settings (id, watch_enabled, scheduler_interval_seconds, updated_at)
            VALUES (1, %s, 5, NOW())
            ON CONFLICT (id) DO UPDATE
            SET watch_enabled = EXCLUDED.watch_enabled,
                updated_at = NOW();
        """, (CSV_WATCH_ENABLED,))

        cur.execute("""
            CREATE TABLE IF NOT EXISTS csv_watch_folders (
                id SERIAL PRIMARY KEY,
                directory_path VARCHAR(1024) NOT NULL UNIQUE,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                interval_seconds INTEGER NOT NULL DEFAULT 60,
                import_user VARCHAR(100) NOT NULL DEFAULT 'folder_watcher',
                last_scan_at TIMESTAMP,
                last_scan_file_count INTEGER NOT NULL DEFAULT 0,
                last_detected_files INTEGER NOT NULL DEFAULT 0,
                last_imported_files INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_csv_watch_folders_active
            ON csv_watch_folders(is_active);
        """)

        if CSV_WATCH_DIRECTORY:
            cur.execute("""
                INSERT INTO csv_watch_folders (directory_path, is_active, interval_seconds, import_user)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (directory_path) DO UPDATE
                SET interval_seconds = EXCLUDED.interval_seconds,
                    import_user = EXCLUDED.import_user,
                    updated_at = NOW();
            """, (CSV_WATCH_DIRECTORY, True, CSV_WATCH_INTERVAL_SECONDS, CSV_WATCH_IMPORT_USER))

        # Stała funkcja PL/pgSQL do przetwarzania danych z tabeli tymczasowej
        cur.execute("""
            CREATE OR REPLACE FUNCTION process_import_temp(
                p_temp_table TEXT,
                p_import_file_id INTEGER
            )
            RETURNS TABLE(ok_count INTEGER, error_count INTEGER, warning_type TEXT)
            LANGUAGE plpgsql
            AS $$
            DECLARE
                sql_text TEXT;
                has_batch_warning BOOLEAN := FALSE;
            BEGIN
                -- 1. external_id empty
                sql_text := format(
                    'UPDATE %I
                     SET processing_status = ''ERROR'',
                         error_reason = ''external_id nie może być puste'',
                         error_type = ''VALIDATION_ERROR''
                     WHERE TRIM(COALESCE(external_id, '''')) = ''''', p_temp_table
                );
                EXECUTE sql_text;

                -- 2. product_code empty
                sql_text := format(
                    'UPDATE %I
                     SET processing_status = ''ERROR'',
                         error_reason = ''product_code nie może być puste'',
                         error_type = ''VALIDATION_ERROR''
                     WHERE TRIM(COALESCE(product_code, '''')) = ''''
                       AND processing_status != ''ERROR''', p_temp_table
                );
                EXECUTE sql_text;

                -- 3. quantity not positive integer
                sql_text := format(
                    'UPDATE %I
                     SET processing_status = ''ERROR'',
                         error_reason = ''quantity musi być liczbą dodatnią, otrzymano: '' || COALESCE(quantity, ''NULL''),
                         error_type = ''VALIDATION_ERROR''
                     WHERE (quantity IS NULL OR quantity !~ ''^[1-9][0-9]*$'')
                       AND processing_status != ''ERROR''', p_temp_table
                );
                EXECUTE sql_text;

                -- 4. unit not in allowed dictionary table
                sql_text := format(
                    'UPDATE %I
                     SET processing_status = ''ERROR'',
                         error_reason = ''unit jest niedozwolona, otrzymano: '' || COALESCE(unit, ''NULL''),
                         error_type = ''VALIDATION_ERROR''
                     WHERE NOT EXISTS (
                         SELECT 1
                         FROM import_units iu
                                                 WHERE iu.unit_code = unit
                           AND iu.is_active = TRUE
                     )
                       AND processing_status != ''ERROR''', p_temp_table
                );
                EXECUTE sql_text;

                -- 5. planned_date invalid (akceptowane: YYYY-MM-DD, DD.MM.YYYY, DD-MM-YYYY, DD/MM/YYYY)
                sql_text := format(
                    'UPDATE %I
                     SET processing_status = ''ERROR'',
                         error_reason = ''planned_date ma niepoprawny format (dozwolone: YYYY-MM-DD, DD.MM.YYYY, DD-MM-YYYY, DD/MM/YYYY), otrzymano: '' || COALESCE(planned_date, ''NULL''),
                         error_type = ''VALIDATION_ERROR''
                     WHERE (
                         CASE
                             WHEN planned_date IS NULL THEN NULL
                             WHEN planned_date ~ ''^[0-9]{4}-[0-9]{2}-[0-9]{2}$''
                                  AND to_char(to_date(planned_date, ''YYYY-MM-DD''), ''YYYY-MM-DD'') = planned_date
                                 THEN to_date(planned_date, ''YYYY-MM-DD'')
                             WHEN planned_date ~ ''^[0-9]{2}\\.[0-9]{2}\\.[0-9]{4}$''
                                  AND to_char(to_date(planned_date, ''DD.MM.YYYY''), ''DD.MM.YYYY'') = planned_date
                                 THEN to_date(planned_date, ''DD.MM.YYYY'')
                             WHEN planned_date ~ ''^[0-9]{2}-[0-9]{2}-[0-9]{4}$''
                                  AND to_char(to_date(planned_date, ''DD-MM-YYYY''), ''DD-MM-YYYY'') = planned_date
                                 THEN to_date(planned_date, ''DD-MM-YYYY'')
                             WHEN planned_date ~ ''^[0-9]{2}/[0-9]{2}/[0-9]{4}$''
                                  AND to_char(to_date(planned_date, ''DD/MM/YYYY''), ''DD/MM/YYYY'') = planned_date
                                 THEN to_date(planned_date, ''DD/MM/YYYY'')
                             ELSE NULL
                         END
                     ) IS NULL
                       AND processing_status != ''ERROR''', p_temp_table
                );
                EXECUTE sql_text;

                -- 6. duplicate external_id within import
                sql_text := format(
                    'UPDATE %I
                     SET processing_status = ''ERROR'',
                         error_reason = ''Duplikat external_id w imporcie'',
                         error_type = ''DUPLICATE_ERROR''
                     WHERE external_id IN (
                         SELECT external_id FROM %I
                         WHERE TRIM(COALESCE(external_id, '''')) != ''''
                         GROUP BY external_id
                         HAVING COUNT(*) > 1
                     )
                       AND processing_status != ''ERROR''', p_temp_table, p_temp_table
                );
                EXECUTE sql_text;

                -- 7. Mark remaining as VALID
                sql_text := format(
                    'UPDATE %I
                     SET processing_status = ''VALID''
                     WHERE processing_status = ''PENDING''', p_temp_table
                );
                EXECUTE sql_text;

                -- Insert error rows
                sql_text := format(
                    'INSERT INTO imports_errors
                     (import_file_id, row_number, external_id, product_code, quantity, unit, planned_date, comment, error_reason, error_type)
                     SELECT %s, row_number, external_id, product_code, quantity, unit, planned_date, comment, error_reason, error_type
                     FROM %I
                     WHERE processing_status = ''ERROR''', p_import_file_id, p_temp_table
                );
                EXECUTE sql_text;
                GET DIAGNOSTICS error_count = ROW_COUNT;

                -- Insert warnings for VALID rows that will replace records from previous imports
                sql_text := format(
                    'INSERT INTO imports_errors
                     (import_file_id, row_number, external_id, product_code, quantity, unit, planned_date, comment, error_reason, error_type, warning_type)
                     SELECT %s, t.row_number, t.external_id, t.product_code, t.quantity, t.unit, t.planned_date, t.comment,
                            ''Rekord zastąpił istniejący rekord z importu #'' || d.import_file_id,
                            ''INFO'',
                            ''REPLACED_EXISTING''
                     FROM %I t
                     JOIN imports_data d ON d.external_id = t.external_id
                     WHERE t.processing_status = ''VALID''', p_import_file_id, p_temp_table
                );
                EXECUTE sql_text;

                -- Insert valid rows (upsert — replace if external_id already exists)
                sql_text := format(
                    'INSERT INTO imports_data (import_file_id, external_id, product_code, quantity, unit, planned_date, comment)
                     SELECT %s, external_id, product_code, quantity::INTEGER, unit,
                            CASE
                                WHEN planned_date ~ ''^[0-9]{4}-[0-9]{2}-[0-9]{2}$''
                                     AND to_char(to_date(planned_date, ''YYYY-MM-DD''), ''YYYY-MM-DD'') = planned_date
                                    THEN to_date(planned_date, ''YYYY-MM-DD'')
                                WHEN planned_date ~ ''^[0-9]{2}\\.[0-9]{2}\\.[0-9]{4}$''
                                     AND to_char(to_date(planned_date, ''DD.MM.YYYY''), ''DD.MM.YYYY'') = planned_date
                                    THEN to_date(planned_date, ''DD.MM.YYYY'')
                                WHEN planned_date ~ ''^[0-9]{2}-[0-9]{2}-[0-9]{4}$''
                                     AND to_char(to_date(planned_date, ''DD-MM-YYYY''), ''DD-MM-YYYY'') = planned_date
                                    THEN to_date(planned_date, ''DD-MM-YYYY'')
                                WHEN planned_date ~ ''^[0-9]{2}/[0-9]{2}/[0-9]{4}$''
                                     AND to_char(to_date(planned_date, ''DD/MM/YYYY''), ''DD/MM/YYYY'') = planned_date
                                    THEN to_date(planned_date, ''DD/MM/YYYY'')
                                ELSE NULL
                            END,
                            comment
                     FROM %I
                     WHERE processing_status = ''VALID''
                     ON CONFLICT (external_id) DO UPDATE SET
                         import_file_id = EXCLUDED.import_file_id,
                         product_code   = EXCLUDED.product_code,
                         quantity       = EXCLUDED.quantity,
                         unit           = EXCLUDED.unit,
                         planned_date   = EXCLUDED.planned_date,
                         comment        = EXCLUDED.comment,
                         imported_at    = NOW()', p_import_file_id, p_temp_table
                );
                EXECUTE sql_text;
                GET DIAGNOSTICS ok_count = ROW_COUNT;

                -- Batch warning when same product_code appears more than 3 times in VALID rows
                sql_text := format(
                    'SELECT EXISTS (
                        SELECT 1
                        FROM %I
                        WHERE processing_status = ''VALID''
                        GROUP BY product_code
                        HAVING COUNT(*) > 3
                    )', p_temp_table
                );
                EXECUTE sql_text INTO has_batch_warning;

                warning_type := CASE
                    WHEN has_batch_warning THEN 'POSSIBLE_DUPLICATE_BATCH'
                    ELSE 'NONE'
                END;

                RETURN QUERY SELECT ok_count, error_count, warning_type;
            END;
            $$;
        """)

        # Wstawienie domyślnych uprawnień (np. dla tabeli users)
        cur.execute("""
            INSERT INTO permissions (table_name, action, required_role) VALUES
            ('users', 'GET', 'guest'),
            ('users', 'POST', 'user'),
            ('users', 'PUT', 'user'),
            ('users', 'DELETE', 'manager'),
            ('access_logs', 'GET', 'admin'),
            ('csv_watch_settings', 'GET', 'admin'),
            ('csv_watch_settings', 'POST', 'admin'),
            ('csv_watch_settings', 'PUT', 'admin'),
            ('csv_watch_settings', 'DELETE', 'admin'),
            ('csv_watch_folders', 'GET', 'admin'),
            ('csv_watch_folders', 'POST', 'admin'),
            ('csv_watch_folders', 'PUT', 'admin'),
            ('csv_watch_folders', 'DELETE', 'admin')
            ON CONFLICT DO NOTHING;
        """)

        # Wstawienie domyślnego użytkownika admin
        hashed_admin_pass = bcrypt.hashpw(b'admin', bcrypt.gensalt()).decode('utf-8')
        cur.execute("""
            INSERT INTO users (username, hashed_password, role_id, is_active) VALUES (%s, %s, %s, %s)
            ON CONFLICT (username) DO NOTHING;
        """, ('admin', hashed_admin_pass, 1, True))

        conn.commit()
        print("Struktura tabel została sprawdzona.")
        return True

    except Exception as e:
        print(f"Błąd podczas konfiguracji: {e}")
        return False
    finally:
        if 'conn' in locals() and conn:
            cur.close()
            conn.close()


if __name__ == "__main__":
    if not setup_database():
        sys.exit(1)
