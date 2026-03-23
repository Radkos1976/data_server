import asyncio
import redis
import logging
from celery import Celery
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import inspect as sa_inspect
from database import MODELS, Log, TaskStatus
from config import REDIS_CELERY_DB, REDIS_SSE_DB, redis_url, DB_URL_ASYNC

celery_app = Celery("tasks", broker=redis_url(REDIS_CELERY_DB))
r_notify = redis.Redis.from_url(redis_url(REDIS_SSE_DB))
logger = logging.getLogger(__name__)

# NullPool — wymagane przy asyncio.run() w Celery (każde wywołanie dostaje świeże połączenie)
_worker_engine = create_async_engine(DB_URL_ASYNC, poolclass=NullPool)
_WorkerSession = async_sessionmaker(_worker_engine, expire_on_commit=False)


async def log_task(task_id: str, task_name: str, status: TaskStatus, message: str = None, username: str = None):
    """Funkcja do logowania zadań Celery do bazy danych."""
    async with _WorkerSession() as session:
        log_entry = Log(task_id=task_id, task_name=task_name, status=status.value, message=message, username=username)
        session.add(log_entry)
        await session.commit()


def _publish(event: str, table_name: str, item_id, task_id: str, extra: str = None):
    msg = f"{event}:{table_name}:{item_id}:{task_id}"
    if extra:
        msg += f":{extra}"
    r_notify.publish("global_updates", msg)


def _coerce_pk_value(ModelClass, raw_item_id):
    """Dopasowuje typ PK do modelu (np. int/smallint/varchar)."""
    mapper = sa_inspect(ModelClass)
    pk_col = mapper.mapper.primary_key[0]
    try:
        py_type = pk_col.type.python_type
    except Exception:
        py_type = str
    if raw_item_id is None:
        return None
    if py_type is str:
        return str(raw_item_id)
    try:
        return py_type(raw_item_id)
    except Exception:
        return raw_item_id


async def _execute_db_task(
    table_name, item_id, task_id, task_name, username,
    start_msg, success_event, success_msg, ok_result, body
):
    try:
        await log_task(task_id, task_name, TaskStatus.STARTED, start_msg, username)
        ModelClass = MODELS[table_name]
        async with _WorkerSession() as session:
            async with session.begin():
                resolved_id = await body(session, ModelClass)
        effective_id = resolved_id if resolved_id is not None else item_id
        _publish(success_event, table_name, effective_id, task_id)
        msg = success_msg(effective_id) if callable(success_msg) else success_msg
        res = ok_result(effective_id) if callable(ok_result) else ok_result
        await log_task(task_id, task_name, TaskStatus.SUCCESS, msg, username)
        return res
    except Exception as e:
        err_msg = str(e) if str(e) else repr(e)
        logger.exception("Celery task failed: %s on table %s pk=%s", task_name, table_name, item_id)
        _publish("ERROR", table_name, item_id, task_id, err_msg)
        await log_task(task_id, task_name, TaskStatus.ERROR, err_msg, username)
        return f"Error: {err_msg}"


async def db_transaction_logic(table_name: str, data: dict, task_id: str, username: str = None):
    async def body(session, ModelClass):
        new_item = ModelClass(**data)
        session.add(new_item)
        await session.flush()
        # PK może być różna (np. unit_code zamiast id) — pobieramy dynamicznie
        mapper = sa_inspect(type(new_item))
        pk_name = mapper.mapper.primary_key[0].name
        return getattr(new_item, pk_name, None)

    return await _execute_db_task(
        table_name, 0, task_id, "process_transaction", username,
        f"Creating record in {table_name}",
        "SUCCESS",
        lambda id: f"Created record {id} in {table_name}",
        lambda id: id,
        body,
    )


async def db_delete_logic(table_name: str, item_id: str, task_id: str, username: str = None):
    async def body(session, ModelClass):
        pk_value = _coerce_pk_value(ModelClass, item_id)
        obj = await session.get(ModelClass, pk_value)
        if not obj:
            raise ValueError(f"Record {item_id} not found")
        await session.delete(obj)

    return await _execute_db_task(
        table_name, item_id, task_id, "process_delete_task", username,
        f"Deleting record {item_id} from {table_name}",
        "DELETED",
        f"Deleted record {item_id} from {table_name}",
        f"Deleted {item_id}",
        body,
    )


async def db_update_logic(table_name: str, item_id: str, data: dict, task_id: str, username: str = None):
    async def body(session, ModelClass):
        pk_value = _coerce_pk_value(ModelClass, item_id)
        obj = await session.get(ModelClass, pk_value)
        if not obj:
            raise ValueError(f"Record {item_id} not found")
        for key, value in data.items():
            setattr(obj, key, value)

    return await _execute_db_task(
        table_name, item_id, task_id, "process_update_task", username,
        f"Updating record {item_id} in {table_name}",
        "UPDATED",
        f"Updated record {item_id} in {table_name}",
        f"Updated {item_id}",
        body,
    )


@celery_app.task(name="process_transaction")
def process_transaction(table_name: str, data: dict, task_id: str, username: str = None):
    return asyncio.run(db_transaction_logic(table_name, data, task_id, username))


@celery_app.task(name="process_delete_task")
def process_delete_task(table_name: str, item_id: str, task_id: str, username: str = None):
    return asyncio.run(db_delete_logic(table_name, item_id, task_id, username))


@celery_app.task(name="process_update_task")
def process_update_task(table_name: str, item_id: str, data: dict, task_id: str, username: str = None):
    return asyncio.run(db_update_logic(table_name, item_id, data, task_id, username))
