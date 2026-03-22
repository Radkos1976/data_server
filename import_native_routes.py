"""
SQL Native CSV Import - FastAPI Routes
Endpoints do upload CSV i monitorowania importu
"""

import logging

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from database import AsyncSessionLocal
from auth import get_current_user, require_permission
from access_logging import log_access
from import_native import import_csv_native, check_file_already_processed, calculate_sha256
from csv_folder_watcher import get_csv_watcher_runtime_status

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/imports", tags=["imports"])


@router.get("/watcher/status")
async def get_watcher_status(
    current_user: str = Depends(require_permission("csv_watch_settings", "GET")),
    session: AsyncSession = Depends(lambda: AsyncSessionLocal())
):
    """Status watchera folderów CSV oraz konfiguracja z bazy danych."""

    runtime = get_csv_watcher_runtime_status()

    settings_result = await session.execute(
        text(
            """
            SELECT id, watch_enabled, scheduler_interval_seconds, updated_at
            FROM csv_watch_settings
            WHERE id = 1
            """
        )
    )
    settings_row = settings_result.fetchone()

    folders_result = await session.execute(
        text(
            """
            SELECT
                id,
                directory_path,
                is_active,
                interval_seconds,
                import_user,
                last_scan_at,
                last_scan_file_count,
                last_detected_files,
                last_imported_files,
                last_error,
                updated_at
            FROM csv_watch_folders
            ORDER BY id ASC
            """
        )
    )

    folders = []
    for row in folders_result.fetchall():
        folders.append(
            {
                "id": row[0],
                "directory_path": row[1],
                "is_active": row[2],
                "interval_seconds": row[3],
                "import_user": row[4],
                "last_scan_at": row[5].isoformat() if row[5] else None,
                "last_scan_file_count": row[6],
                "last_detected_files": row[7],
                "last_imported_files": row[8],
                "last_error": row[9],
                "updated_at": row[10].isoformat() if row[10] else None,
            }
        )

    return {
        "runtime": runtime,
        "settings": {
            "id": settings_row[0] if settings_row else 1,
            "watch_enabled": settings_row[1] if settings_row else False,
            "scheduler_interval_seconds": settings_row[2] if settings_row else 5,
            "updated_at": settings_row[3].isoformat() if settings_row and settings_row[3] else None,
        },
        "folders": folders,
    }

# ============================================================
# 1. POST /imports - Upload CSV
# ============================================================

@router.post("")
async def upload_csv(
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user),
    session: AsyncSession = Depends(lambda: AsyncSessionLocal())
):
    """
    Upload CSV do importu
    
    Flow:
    1. Oblicz SHA256 pliku
    2. Sprawdź czy już przetworzony
    3. Jeśli TAK - zwróć status
    4. Jeśli NIE - uruchom synchroniczny import (SQL COPY + walidacja)
    
    Returns:
        - Jeśli nowy plik: status COMPLETED + counts
        - Jeśli duplikat: status ALREADY_PROCESSED + poprzednie counts
        - Jeśli błąd: status ERROR + error_message
    """
    
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Tylko pliki CSV")
    
    try:
        # Odczyt zawartości
        content = await file.read()
        
        # Sprawdzenie duplikatu
        file_checksum = calculate_sha256(content)
        existing = await check_file_already_processed(session, file.filename, file_checksum)
        
        if existing:
            logger.info("CSV upload ALREADY_PROCESSED: file=%s user=%s", file.filename, current_user)
            await log_access(current_user, "POST", "/imports", 200,
                             f"Duplikat pliku: {file.filename} (import_id={existing['import_file_id']})")
            return {
                "status": existing["status"],
                "import_file_id": existing["import_file_id"],
                "filename": existing["filename"],
                "total_rows": existing["total_rows"],
                "ok_rows": existing["ok_rows"],
                "error_rows": existing["error_rows"],
                "warning_type": existing["warning_type"],
                "message": f"Plik {file.filename} został już przetworzony"
            }
        
        # Import (synchroniczny - SQL side)
        import_file_id, result = import_csv_native(content, file.filename, current_user)
        
        if import_file_id is None:
            logger.error("CSV upload ERROR: file=%s user=%s error=%s",
                         file.filename, current_user, result.get("error_message"))
            await log_access(current_user, "POST", "/imports", 500,
                             f"Import błąd: {file.filename}: {result.get('error_message')}")
            raise HTTPException(status_code=500, detail=result.get("error_message"))

        logger.info("CSV upload COMPLETED: file=%s user=%s ok=%s errors=%s import_id=%s",
                    file.filename, current_user,
                    result.get("ok_rows", 0), result.get("error_rows", 0), import_file_id)
        await log_access(current_user, "POST", "/imports", 200,
                         f"Import OK: {file.filename} ok={result.get('ok_rows',0)} błędy={result.get('error_rows',0)}")
        return {
            "status": result["status"],
            "import_file_id": import_file_id,
            "filename": file.filename,
            "total_rows": result.get("total_rows", 0),
            "ok_rows": result.get("ok_rows", 0),
            "error_rows": result.get("error_rows", 0),
            "warning_type": result.get("warning_type", "NONE")
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("CSV upload EXCEPTION: file=%s user=%s", file.filename, current_user)
        await log_access(current_user, "POST", "/imports", 500,
                         f"Import wyjątek: {file.filename}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


# ============================================================
# 2. GET /imports - Lista importów
# ============================================================

@router.get("")
async def list_imports(
    page: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: str = Depends(get_current_user),
    session: AsyncSession = Depends(lambda: AsyncSessionLocal())
):
    """
    Lista wszystkich importów z paginacją
    """
    
    offset = page * limit
    
    # Total count
    result = await session.execute(
        text("SELECT COUNT(*) FROM imports_files")
    )
    total = result.scalar()
    pages = (total + limit - 1) // limit
    
    # Data
    result = await session.execute(
        text("""
            SELECT 
                id, filename, file_checksum, processed_at,
                total_rows, ok_rows, error_rows, warning_type, processed_by
            FROM imports_files
            ORDER BY processed_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"limit": limit, "offset": offset}
    )
    
    rows = result.fetchall()
    data = [
        {
            "id": row[0],
            "filename": row[1],
            "checksum": row[2][:16] + "..." if row[2] else None,  # Show first 16 chars
            "processed_at": row[3].isoformat() if row[3] else None,
            "total_rows": row[4],
            "ok_rows": row[5],
            "error_rows": row[6],
            "warning_type": row[7] or "NONE",
            "processed_by": row[8]
        }
        for row in rows
    ]
    
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "pages": pages,
        "data": data
    }


# ============================================================
# 3. GET /imports/{import_id} - Szczegóły importu
# ============================================================

@router.get("/{import_id}")
async def get_import_details(
    import_id: int,
    current_user: str = Depends(get_current_user),
    session: AsyncSession = Depends(lambda: AsyncSessionLocal())
):
    """
    Szczegóły pojedynczego importu
    """
    
    result = await session.execute(
        text("""
            SELECT 
                id, filename, file_checksum, processed_at, completed_at,
                total_rows, ok_rows, error_rows, warning_type, processed_by
            FROM imports_files
            WHERE id = :import_id
        """),
        {"import_id": import_id}
    )
    
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Import nie znaleziony")
    
    return {
        "id": row[0],
        "filename": row[1],
        "checksum": row[2],
        "processed_at": row[3].isoformat() if row[3] else None,
        "completed_at": row[4].isoformat() if row[4] else None,
        "total_rows": row[5],
        "ok_rows": row[6],
        "error_rows": row[7],
        "warning_type": row[8] or "NONE",
        "processed_by": row[9],
        "status": "COMPLETED"  # W SQL native wszystkie są COMPLETED
    }


# ============================================================
# 4. GET /imports/{import_id}/errors - Błędy importu
# ============================================================

@router.get("/{import_id}/errors")
async def get_import_errors(
    import_id: int,
    page: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: str = Depends(get_current_user),
    session: AsyncSession = Depends(lambda: AsyncSessionLocal())
):
    """
    Historia błędów dla danego importu
    """
    
    # Sprawdzenie czy import istnieje
    result = await session.execute(
        text("SELECT id FROM imports_files WHERE id = :import_id"),
        {"import_id": import_id}
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Import nie znaleziony")
    
    offset = page * limit
    
    # Total count
    result = await session.execute(
        text("""
            SELECT COUNT(*) FROM imports_errors WHERE import_file_id = :import_id
        """),
        {"import_id": import_id}
    )
    total = result.scalar()
    pages = (total + limit - 1) // limit
    
    # Data
    result = await session.execute(
        text("""
            SELECT 
                id, row_number, external_id, product_code, quantity, unit, planned_date,
                comment, error_reason, error_type, warning_type, created_at
            FROM imports_errors
            WHERE import_file_id = :import_id
            ORDER BY row_number ASC
            LIMIT :limit OFFSET :offset
        """),
        {"import_id": import_id, "limit": limit, "offset": offset}
    )
    
    rows = result.fetchall()
    data = [
        {
            "id": row[0],
            "row_number": row[1],
            "external_id": row[2],
            "product_code": row[3],
            "quantity": row[4],
            "unit": row[5],
            "planned_date": row[6],
            "comment": row[7],
            "error_reason": row[8],
            "error_type": row[9],
            "warning_type": row[10] or "NONE",
            "created_at": row[11].isoformat() if row[11] else None
        }
        for row in rows
    ]
    
    return {
        "import_id": import_id,
        "page": page,
        "limit": limit,
        "total": total,
        "pages": pages,
        "data": data
    }


# ============================================================
# 5. GET /imports/{import_id}/data - Zaimportowane dane (OK rekordy)
# ============================================================

@router.get("/{import_id}/data")
async def get_import_data(
    import_id: int,
    page: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: str = Depends(get_current_user),
    session: AsyncSession = Depends(lambda: AsyncSessionLocal())
):
    """
    Rekordy które zostały pomyślnie zaimportowane
    """
    
    # Sprawdzenie czy import istnieje
    result = await session.execute(
        text("SELECT id FROM imports_files WHERE id = :import_id"),
        {"import_id": import_id}
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Import nie znaleziony")
    
    offset = page * limit
    
    # Total count
    result = await session.execute(
        text("""
            SELECT COUNT(*) FROM imports_data WHERE import_file_id = :import_id
        """),
        {"import_id": import_id}
    )
    total = result.scalar()
    pages = (total + limit - 1) // limit
    
    # Data
    result = await session.execute(
        text("""
            SELECT 
                id, external_id, product_code, quantity, unit, planned_date, comment, imported_at
            FROM imports_data
            WHERE import_file_id = :import_id
            ORDER BY id ASC
            LIMIT :limit OFFSET :offset
        """),
        {"import_id": import_id, "limit": limit, "offset": offset}
    )
    
    rows = result.fetchall()
    data = [
        {
            "id": row[0],
            "external_id": row[1],
            "product_code": row[2],
            "quantity": row[3],
            "unit": row[4],
            "planned_date": row[5].isoformat() if row[5] else None,
            "comment": row[6],
            "imported_at": row[7].isoformat() if row[7] else None
        }
        for row in rows
    ]
    
    return {
        "import_id": import_id,
        "page": page,
        "limit": limit,
        "total": total,
        "pages": pages,
        "data": data
    }
