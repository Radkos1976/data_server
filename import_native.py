"""
SQL Native CSV Import - Python wrapper
Handles file upload, checksum management, and procedure triggering
"""

import hashlib
import io
import csv
import logging
import uuid
from typing import Optional, Tuple
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import DB_URL_SYNC

logger = logging.getLogger(__name__)

# ============================================================
# Synchronous DB wrapper (dla procedur SQL)
# ============================================================


def get_sync_connection():
    """Zwraca synchroniczną konekcję dla procedur SQL"""
    import psycopg2
    from urllib.parse import urlparse

    parsed = urlparse(DB_URL_SYNC)
    return psycopg2.connect(
        dbname=parsed.path.lstrip('/'),
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432
    )


def _log_to_db(cur, task_id: str, task_name: str, status: str, message: str, username: str):
    """Zapisuje wpis do tabeli logs przez istniejący kursor psycopg2."""
    cur.execute(
        "INSERT INTO logs (task_id, task_name, status, message, username) "
        "VALUES (%s, %s, %s::task_status, %s, %s)",
        (task_id, task_name, status, message, username),
    )


# ============================================================
# FILE CHECKSUM & DEDUPLICATION
# ============================================================

def calculate_sha256(file_content: bytes) -> str:
    """Oblicza SHA256 hex dla zawartości pliku"""
    return hashlib.sha256(file_content).hexdigest()


async def check_file_already_processed(
    session: AsyncSession,
    filename: str,
    file_checksum: str
) -> Optional[dict]:
    """
    Sprawdza czy plik został już przetworzony

    Returns:
        None если file_checksum nie istnieje
        dict z import_files record jeśli istnieje
    """
    result = await session.execute(
        text("""
            SELECT id, filename, file_checksum, processed_at,
                   total_rows, ok_rows, error_rows, warning_type, processed_by
            FROM imports_files
            WHERE filename = :filename AND file_checksum = :checksum
        """),
        {"filename": filename, "checksum": file_checksum}
    )
    row = result.fetchone()

    if not row:
        return None

    return {
        "import_file_id": row[0],
        "filename": row[1],
        "file_checksum": row[2],
        "processed_at": row[3],
        "total_rows": row[4],
        "ok_rows": row[5],
        "error_rows": row[6],
        "warning_type": row[7],
        "processed_by": row[8],
        "status": "ALREADY_PROCESSED"
    }


# ============================================================
# MAIN IMPORT FLOW (SYNCHRONOUS - to trigger SQL procedures)
# ============================================================

def import_csv_native(
    csv_content: bytes,
    filename: str,
    username: str
) -> Tuple[int, dict]:
    """
    Główny flow importu - wszystko na SQL side

    Args:
        csv_content: zawartość pliku CSV
        filename: nazwa pliku
        username: który użytkownik uploaduje

    Returns:
        (import_file_id, result_dict)
    """

    file_checksum = calculate_sha256(csv_content)
    task_id = str(uuid.uuid4())
    conn = get_sync_connection()
    cur = conn.cursor()

    try:
        # 1. Sprawdzenie czy plik już istnieje
        cur.execute(
            """
            SELECT id, total_rows, ok_rows, error_rows, warning_type
            FROM imports_files
            WHERE filename = %s AND file_checksum = %s
            """,
            (filename, file_checksum)
        )
        existing = cur.fetchone()

        if existing:
            # Plik Already processed
            return (existing[0], {
                "status": "ALREADY_PROCESSED",
                "import_file_id": existing[0],
                "filename": filename,
                "checksum": file_checksum,
                "total_rows": existing[1] or 0,
                "ok_rows": existing[2] or 0,
                "error_rows": existing[3] or 0,
                "warning_type": existing[4] or "NONE"
            })

        # 2. Tworzenie rekordu w imports_files
        cur.execute(
            """
            INSERT INTO imports_files (filename, file_checksum, processed_by)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (filename, file_checksum, username)
        )
        import_file_id = cur.fetchone()[0]

        _log_to_db(cur, task_id, "csv_import", "STARTED",
                   f"Import pliku: {filename} (id={import_file_id})", username)
        logger.info("CSV import STARTED: file=%s import_id=%s user=%s task_id=%s",
                    filename, import_file_id, username, task_id)

        # 3. Tworzenie temp tabeli dla tego importu (zniknie po COMMIT/ROLLBACK)
        temp_table_name = f"temp_import_{import_file_id}"
        cur.execute(f"""
            CREATE TEMP TABLE {temp_table_name} (
                row_number INTEGER,
                external_id VARCHAR(255),
                product_code VARCHAR(255),
                quantity VARCHAR(50),
                unit VARCHAR(50),
                planned_date VARCHAR(50),
                comment TEXT,
                processing_status VARCHAR(20) DEFAULT 'PENDING',
                error_reason TEXT,
                error_type VARCHAR(20)
            ) ON COMMIT DROP
        """)

        # 4. COPY CSV do temp tabeli
        _copy_csv_to_temp(
            cur,
            csv_content,
            filename,
            import_file_id,
            temp_table_name
        )

        # 5. Walidacja i podział po stronie Postgres (PL/pgSQL)
        cur.execute(
            "SELECT ok_count, error_count, warning_type FROM process_import_temp(%s, %s)",
            (temp_table_name, import_file_id)
        )
        ok_count, error_count, warning_type = cur.fetchone()

        # 6. Update imports_files z wynikami
        cur.execute(
            """
            UPDATE imports_files
            SET total_rows = %s, ok_rows = %s, error_rows = %s,
                warning_type = %s, processed_at = NOW(), completed_at = NOW()
            WHERE id = %s
            """,
            (ok_count + error_count, ok_count, error_count, warning_type, import_file_id)
        )

        _log_to_db(cur, task_id, "csv_import", "SUCCESS",
                   f"Import ukończony: {filename} ok={ok_count} błędy={error_count} warning={warning_type}",
                   username)
        logger.info("CSV import SUCCESS: file=%s import_id=%s ok=%s errors=%s task_id=%s",
                    filename, import_file_id, ok_count, error_count, task_id)

        conn.commit()

        return (import_file_id, {
            "status": "COMPLETED",
            "import_file_id": import_file_id,
            "filename": filename,
            "checksum": file_checksum,
            "total_rows": ok_count + error_count,
            "ok_rows": ok_count,
            "error_rows": error_count,
            "warning_type": warning_type
        })

    except Exception as e:
        conn.rollback()
        logger.error("CSV import ERROR: file=%s user=%s task_id=%s error=%s",
                     filename, username, task_id, e)
        try:
            err_conn = get_sync_connection()
            err_cur = err_conn.cursor()
            _log_to_db(err_cur, task_id, "csv_import", "ERROR", str(e), username)
            err_conn.commit()
            err_cur.close()
            err_conn.close()
        except Exception:
            logger.exception("Nie udało się zapisać błędu importu do tabeli logs")
        return (None, {
            "status": "ERROR",
            "error_message": str(e)
        })

    finally:
        cur.close()
        conn.close()


# ============================================================
# INTERNAL: CSV COPY
# ============================================================

def _detect_csv_encoding_and_delimiter(csv_content: bytes) -> Tuple[str, str]:
    """
    Wykrywa kodowanie i separator CSV.

    Obsługiwane kodowania (w kolejności):
    - utf-8-sig
    - utf-8
    - cp1250
    - iso-8859-2

    Obsługiwane separatory:
    - ; , \t |
    """
    encodings_to_try = ["utf-8-sig", "utf-8", "cp1250", "iso-8859-2"]
    decoded_text = None

    for enc in encodings_to_try:
        try:
            decoded_text = csv_content.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if decoded_text is None:
        raise ValueError("Nie udało się rozpoznać kodowania CSV")

    sample = decoded_text[:4096]
    delimiters = [";", ",", "\t", "|"]

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=delimiters)
        delimiter = dialect.delimiter
    except csv.Error:
        # Najczęstszy separator w PL CSV to ';'
        delimiter = ";"

    return decoded_text, delimiter


def _copy_csv_to_temp(
    cursor,
    csv_content: bytes,
    filename: str,
    import_file_id: int,
    temp_table_name: str
):
    """
    Wczytuje CSV do tabeli tymczasowej używając COPY
    """
    csv_text, delimiter = _detect_csv_encoding_and_delimiter(csv_content)
    lines = csv_text.strip().splitlines()

    if len(lines) < 2:
        raise ValueError("CSV musi mieć nagłówek i przynajmniej 1 wiersz")

    # Sprawdzenie nagłówków
    headers = [h.strip() for h in next(csv.reader([lines[0]], delimiter=delimiter))]
    required_headers = ['external_id', 'product_code', 'quantity', 'unit', 'planned_date', 'comment']

    if headers != required_headers:
        raise ValueError(
            "Niepoprawne kolumny CSV. "
            f"Oczekiwano dokładnie: {required_headers}. "
            f"Otrzymano: {headers}"
        )

    # Przygotowanie danych do COPY
    csv_buffer = io.StringIO()
    csv_buffer.write("\n".join(lines) + "\n")

    csv_buffer.seek(0)

    # COPY do tabeli tymczasowej
    cursor.copy_expert(
        f"""
        COPY {temp_table_name}
        (external_id, product_code, quantity, unit, planned_date, comment)
        FROM STDIN WITH (FORMAT CSV, HEADER, DELIMITER '{delimiter}')
        """,
        csv_buffer
    )

    # Nadanie numerów wierszy po COPY
    cursor.execute(f"""
        WITH numbered AS (
            SELECT ctid, ROW_NUMBER() OVER (ORDER BY ctid) AS rn
            FROM {temp_table_name}
        )
        UPDATE {temp_table_name} t
        SET row_number = n.rn
        FROM numbered n
        WHERE t.ctid = n.ctid
    """)

    csv_buffer.close()
