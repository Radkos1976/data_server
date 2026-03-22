from typing import Dict, Type, Optional
from datetime import datetime
from sqlalchemy import MetaData, inspect
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel, Relationship, create_engine as create_sync_engine, Field
from enum import Enum as PyEnum
from config import DB_URL_ASYNC, DB_URL_SYNC
from type_mapping import SQL_TYPE_MAPPING

async_engine = create_async_engine(DB_URL_ASYNC)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

# Synchronizuje silnik do inspekcji schematu
sync_engine = create_sync_engine(DB_URL_SYNC)
metadata = MetaData()

# Enum dla statusu logów
class TaskStatus(PyEnum):
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"

# Statyczny model dla logów Celery
class Log(SQLModel, table=True):
    __tablename__ = "logs"
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str
    task_name: str
    status: TaskStatus
    message: Optional[str] = None
    username: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)

def get_dynamic_models() -> Dict[str, Type[SQLModel]]:
    metadata.reflect(bind=sync_engine)
    inspector = inspect(sync_engine)
    models = {}

    # Tworzenie klas dynamicznych z annotations wynikającymi ze schematu bazy
    for table_name in metadata.tables.keys():
        # Pomijamy tabele ze statycznymi modelami (zdefiniowanymi wyżej)
        if table_name in ("logs",):
            continue
        class_name = table_name.capitalize().replace("_", "")
        columns = inspector.get_columns(table_name)
        pk_columns = inspector.get_pk_constraint(table_name).get('constrained_columns', [])

        # Tworzenie klasy z annotations i Field() dla kluczy głównych
        annotations = {}
        fields = {}
        for col in columns:
            col_name = col['name']
            col_type = str(col['type']).split('(')[0].upper()
            python_type = SQL_TYPE_MAPPING.get(col_type, str)

            if col_name in pk_columns:
                annotations[col_name] = Optional[python_type]
                fields[col_name] = Field(default=None, primary_key=True)
            elif col.get('nullable', True):
                annotations[col_name] = Optional[python_type]
                fields[col_name] = Field(default=None)
            else:
                annotations[col_name] = python_type
                fields[col_name] = Field()

        class_dict = {
            "__tablename__": table_name,
            "__annotations__": annotations,
            **fields
        }
        ModelClass = type(class_name, (SQLModel,), class_dict, table=True)
        models[table_name] = ModelClass

    # Dodawanie relacji (Foreign Keys)
    for table_name, ModelClass in models.items():
        for fk in inspector.get_foreign_keys(table_name):
            ref_table = fk['referred_table']
            if ref_table in models:
                # Relacja: Dziecko -> Rodzic
                setattr(ModelClass, f"{ref_table}_rel", Relationship())
                # Relacja: Rodzic -> Lista Dzieci
                setattr(models[ref_table], f"{table_name}_list", Relationship())
    return models

# Globalny słownik modeli dostępny dla API i Workera
MODELS = get_dynamic_models()
MODELS["logs"] = Log  # Dodajemy statyczny model logów