from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID


SQL_TYPE_MAPPING = {
    "VARCHAR": str,
    "CHAR": str,
    "CHARACTER": str,
    "CHARACTER VARYING": str,
    "UUID": UUID,
    "TEXT": str,
    "JSON": Any,
    "JSONB": Any,
    "BYTEA": bytes,
    "INTEGER": int,
    "BIGINT": int,
    "SMALLINT": int,
    "BOOLEAN": bool,
    "TIMESTAMP": datetime,
    "TIMESTAMP WITHOUT TIME ZONE": datetime,
    "TIMESTAMP WITH TIME ZONE": datetime,
    "DATE": date,
    "TIME": time,
    "TIME WITHOUT TIME ZONE": time,
    "TIME WITH TIME ZONE": time,
    "FLOAT": float,
    "REAL": float,
    "DOUBLE PRECISION": float,
    "NUMERIC": Decimal,
    "DECIMAL": Decimal,
    "SERIAL": int,
    "BIGSERIAL": int,
}