import logging
from typing import Optional

from sqlalchemy import text

from database import AsyncSessionLocal


logger = logging.getLogger(__name__)


async def log_access(
    username: str,
    method: str,
    path: str,
    status_code: Optional[int],
    detail: str = None,
    ip: str = None,
    user_agent: str = None,
):
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO access_logs (
                        username, method, path, status_code, user_agent, ip_address, detail
                    )
                    VALUES (
                        :username, :method, :path, :status_code, :user_agent,
                        CAST(:ip AS INET), :detail
                    )
                    """
                ),
                {
                    "username": username,
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "user_agent": user_agent,
                    "ip": ip,
                    "detail": detail,
                },
            )
            await session.commit()
    except Exception as exc:
        logger.error(f"Failed to log access: {exc}")
