from datetime import date, datetime, time

from fastapi import Request
from sqlalchemy import String, cast, or_


def parse_filter_value(column, raw_value: str):
    try:
        python_type = column.type.python_type
    except (AttributeError, NotImplementedError):
        return raw_value

    if raw_value == "null":
        return None

    try:
        if python_type is bool:
            normalized = raw_value.strip().lower()
            if normalized in {"true", "1", "yes", "y", "on"}:
                return True
            if normalized in {"false", "0", "no", "n", "off"}:
                return False
            return raw_value

        if python_type is int:
            return int(raw_value)

        if python_type is float:
            return float(raw_value)

        if python_type is datetime:
            return datetime.fromisoformat(raw_value)

        if python_type is date:
            return date.fromisoformat(raw_value)

        if python_type is time:
            return time.fromisoformat(raw_value)

        if hasattr(python_type, "__mro__") and any(base.__name__ == "Enum" for base in python_type.__mro__):
            return python_type(raw_value)
    except (TypeError, ValueError):
        return raw_value

    return raw_value


def build_filters(model, request: Request):
    reserved = {"page", "limit", "offset"}
    filters = []

    for raw_key in set(request.query_params.keys()):
        if raw_key in reserved:
            continue

        op = "eq"
        field_name = raw_key

        if raw_key.endswith("__like"):
            op = "like"
            field_name = raw_key[:-6]

        if not hasattr(model, field_name):
            continue

        column = getattr(model, field_name)
        raw_values = request.query_params.getlist(raw_key)

        values = []
        for raw_value in raw_values:
            parts = [part.strip() for part in raw_value.split(",") if part.strip()]
            values.extend(parts if parts else [raw_value])

        if not values:
            continue

        if op == "like":
            conditions = []
            for value in values:
                pattern = value.replace("*", "%")
                if "%" not in pattern and "_" not in pattern:
                    pattern = f"%{pattern}%"
                conditions.append(cast(column, String).ilike(pattern))
        else:
            typed_values = [parse_filter_value(column, value) for value in values]
            conditions = [column == value for value in typed_values]

        filters.append(or_(*conditions))

    return filters


def serialize_row(item):
    return {
        key: value
        for key, value in item.__dict__.items()
        if not key.startswith("_")
    }
