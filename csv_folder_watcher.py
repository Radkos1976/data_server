import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from import_native import import_csv_native
from import_native import get_sync_connection

logger = logging.getLogger(__name__)

_RUNTIME_STATUS: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "last_loop_at": None,
    "last_error": None,
    "watch_enabled": False,
    "scheduler_interval_seconds": 5,
    "active_folders": 0,
    "last_detected_files": 0,
    "last_imported_files": 0,
}


def get_csv_watcher_runtime_status() -> Dict[str, Any]:
    return dict(_RUNTIME_STATUS)


def _process_watcher_tick(seen_state: Dict[str, Tuple[float, int]]) -> Dict[str, Any]:
    now = datetime.utcnow()
    detected_total = 0
    imported_total = 0

    conn = get_sync_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT watch_enabled, scheduler_interval_seconds
            FROM csv_watch_settings
            WHERE id = 1
            """
        )
        settings_row = cur.fetchone()
        watch_enabled = bool(settings_row[0]) if settings_row else False
        scheduler_interval_seconds = int(settings_row[1]) if settings_row and settings_row[1] else 5

        cur.execute(
            """
            SELECT id, directory_path, interval_seconds, import_user, last_scan_at
            FROM csv_watch_folders
            WHERE is_active = TRUE
            ORDER BY id
            """
        )
        folders = cur.fetchall()

        if not watch_enabled:
            return {
                "watch_enabled": False,
                "scheduler_interval_seconds": scheduler_interval_seconds,
                "active_folders": len(folders),
                "last_detected_files": 0,
                "last_imported_files": 0,
            }

        for folder_id, directory_path, interval_seconds, import_user, last_scan_at in folders:
            is_due = (
                last_scan_at is None
                or (now - last_scan_at).total_seconds() >= max(int(interval_seconds or 1), 1)
            )
            if not is_due:
                continue

            watch_path = Path(directory_path)
            folder_detected = 0
            folder_imported = 0
            folder_error = None
            csv_files_count = 0

            try:
                if not watch_path.exists() or not watch_path.is_dir():
                    folder_error = f"Directory not available: {watch_path}"
                else:
                    csv_files = sorted(
                        [p for p in watch_path.iterdir() if p.is_file() and p.suffix.lower() == ".csv"]
                    )
                    csv_files_count = len(csv_files)

                    for csv_file in csv_files:
                        stat = csv_file.stat()
                        current_state = (stat.st_mtime, stat.st_size)
                        key = f"{folder_id}:{csv_file.resolve()}"

                        if seen_state.get(key) == current_state:
                            continue

                        folder_detected += 1
                        detected_total += 1

                        content = csv_file.read_bytes()
                        import_file_id, result = import_csv_native(content, csv_file.name, import_user)

                        status = result.get("status")
                        if import_file_id is not None and status == "COMPLETED":
                            folder_imported += 1
                            imported_total += 1
                            logger.info(
                                "CSV watcher COMPLETED: folder=%s file=%s ok=%s errors=%s import_id=%s",
                                directory_path, csv_file.name,
                                result.get("ok_rows"), result.get("error_rows"), import_file_id,
                            )
                        elif status == "ALREADY_PROCESSED":
                            logger.info(
                                "CSV watcher ALREADY_PROCESSED: folder=%s file=%s",
                                directory_path, csv_file.name,
                            )
                        else:
                            logger.warning(
                                "CSV watcher %s: folder=%s file=%s error=%s",
                                status, directory_path, csv_file.name, result.get("error_message"),
                            )

                        seen_state[key] = current_state

            except Exception as folder_exc:
                folder_error = str(folder_exc)
                logger.exception("CSV watcher folder processing failed: %s", folder_exc)

            cur.execute(
                """
                UPDATE csv_watch_folders
                SET last_scan_at = NOW(),
                    last_scan_file_count = %s,
                    last_detected_files = %s,
                    last_imported_files = %s,
                    last_error = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (csv_files_count, folder_detected, folder_imported, folder_error, folder_id),
            )

        conn.commit()

        return {
            "watch_enabled": True,
            "scheduler_interval_seconds": scheduler_interval_seconds,
            "active_folders": len(folders),
            "last_detected_files": detected_total,
            "last_imported_files": imported_total,
        }
    finally:
        cur.close()
        conn.close()


async def run_csv_folder_watcher(loop_sleep_seconds: int = 5):
    """
    Cyklicznie skanuje foldery CSV skonfigurowane w DB.

    Konfiguracja runtime jest pobierana z tabel:
    - csv_watch_settings
    - csv_watch_folders
    """
    seen_state: Dict[str, Tuple[float, int]] = {}

    _RUNTIME_STATUS["running"] = True
    _RUNTIME_STATUS["started_at"] = datetime.utcnow().isoformat()
    logger.info("CSV watcher started (DB-driven)")

    while True:
        try:
            tick_result = await asyncio.to_thread(_process_watcher_tick, seen_state)
            _RUNTIME_STATUS["last_loop_at"] = datetime.utcnow().isoformat()
            _RUNTIME_STATUS["last_error"] = None
            _RUNTIME_STATUS["watch_enabled"] = tick_result["watch_enabled"]
            _RUNTIME_STATUS["active_folders"] = tick_result["active_folders"]
            _RUNTIME_STATUS["last_detected_files"] = tick_result["last_detected_files"]
            _RUNTIME_STATUS["last_imported_files"] = tick_result["last_imported_files"]
            _RUNTIME_STATUS["scheduler_interval_seconds"] = tick_result["scheduler_interval_seconds"]

            await asyncio.sleep(max(int(tick_result["scheduler_interval_seconds"] or loop_sleep_seconds), 1))
        except asyncio.CancelledError:
            _RUNTIME_STATUS["running"] = False
            logger.info("CSV watcher stopped")
            raise
        except Exception as loop_exc:
            _RUNTIME_STATUS["last_error"] = str(loop_exc)
            logger.exception("CSV watcher loop error: %s", loop_exc)
            await asyncio.sleep(max(loop_sleep_seconds, 1))
