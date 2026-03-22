import logging
from typing import Optional

from sqlalchemy import insert

from database import AsyncSessionLocal, MODELS


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
                insert(MODELS["access_logs"]).values(
                    username=username,
                    method=method,
                    path=path,
                    status_code=status_code,
                    detail=detail,
                    ip_address=ip,
                    user_agent=user_agent,
                )
            )
            await session.commit()
    except Exception as exc:
        logger.error(f"Failed to log access: {exc}")