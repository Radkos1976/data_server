from fastapi import FastAPI, Depends, Path, HTTPException, Request, Query
from sse_starlette.sse import EventSourceResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter
from sqlalchemy import select, func
from contextlib import asynccontextmanager
import asyncio
from redis import asyncio as aioredis
import uuid
import logging
from database import MODELS, AsyncSessionLocal
from worker import process_transaction, process_delete_task, process_update_task
from auth import require_permission, create_access_token, verify_password
from auth import create_refresh_token, validate_refresh_token
from access_logging import log_access
from config import REDIS_LIMITER_DB, REDIS_SSE_DB, redis_url
from middleware import LoggingMiddleware, SecurityHeadersMiddleware
from query_helpers import build_filters, serialize_row
from import_native_routes import router as import_native_router
from csv_folder_watcher import run_csv_folder_watcher

# Konfiguracja logowania
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    redis = aioredis.from_url(redis_url(REDIS_LIMITER_DB), encoding="utf8")
    await FastAPILimiter.init(redis)
    watcher_task = asyncio.create_task(run_csv_folder_watcher())
    logger.info("CSV watcher scheduled (DB-driven)")

    yield
    # Shutdown
    if watcher_task:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass

    await redis.close()

app = FastAPI(lifespan=lifespan)

# Dodaj middleware
app.add_middleware(LoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# Rejestruj router importu CSV
app.include_router(import_native_router)

# 1. Automatyczne Endpointy (Dynamic CRUD)
# Tworzymy endpointy dla każdej tabeli w bazie danych, korzystając z dynamicznie wygenerowanych modeli SQLModel i relacji. 
# Każdy endpoint jest asynchroniczny, aby nie blokować serwera podczas operacji na bazie danych.
for table_name, ModelClass in MODELS.items():
    def make_routes(name=table_name, model=ModelClass):
        @app.get(f"/{name}", tags=[name], dependencies=[Depends(RateLimiter(times=100, seconds=60))])
        async def list_items(
            page: int = Query(0, ge=0, description="Numer strony (0-based)"),
            limit: int = Query(100, ge=1, le=1000, description="Liczba rekordów na stronę"),
            offset: int = Query(None, ge=0, description="Offset (jeśli podany, ignoruje page)"),
            request: Request = None,
            user: str = Depends(require_permission(name, "GET"))
        ):
            """
            GET /{table_name}
            
            Parametry możliwe do filtrowania:
            - Dokładne dopasowanie: ?field=value
            - Wiele wartości (OR): ?field=value1,value2 lub ?field=value1&field=value2
            - Pattern matching: ?field__like=pattern (obsługuje * jako wildcard)
            - Null filtering: ?field=null
            - Paginacja: ?page=0&limit=100 LUB ?offset=50&limit=100
            
            Przykłady:
            - GET /{name}?username=john&age=30 (username=john AND age=30)
            - GET /{name}?status=active,inactive (status IN [active, inactive])
            - GET /{name}?email__like=*@gmail.com (like '%@gmail.com%')
            - GET /{name}?page=2&limit=20
            """
            async with AsyncSessionLocal() as session:
                query = select(model)
                filters = build_filters(model, request)

                for f in filters:
                    query = query.where(f)

                # Paginacja
                if offset is not None:
                    query = query.offset(offset).limit(limit)
                else:
                    query = query.offset(page * limit).limit(limit)

                result = await session.execute(query)
                items = result.scalars().all()

                # Total count (z tymi samymi filtrami, bez paginacji)
                total_query = select(func.count()).select_from(model)
                for f in filters:
                    total_query = total_query.where(f)
                total = (await session.execute(total_query)).scalar_one()

                return {
                    "page": page if offset is None else None,
                    "limit": limit,
                    "offset": offset,
                    "total": total,
                    "pages": (total + limit - 1) // limit,
                    "data": [serialize_row(item) for item in items]
                }

        @app.post(f"/{name}", tags=[name], status_code=202, dependencies=[Depends(RateLimiter(times=10, seconds=60))])
        async def create_async(data: dict, user: str = Depends(require_permission(name, "POST"))):
            """
            POST /{table_name}
            
            Parametry request body (JSON):
            - data: dict - zawiera wszystkie pola rekordu do utworzenia
            
            Zwraca: task_id i powiadomienie SSE: SUCCESS:{name}:{id}:{task_id}
            """
            task_id = str(uuid.uuid4())
            process_transaction.delay(name, data, task_id, user)
            return {"task_id": task_id, "info": "Przetwarzanie w tle"}
        
        @app.delete(f"/{name}/{{item_id}}", tags=[name], status_code=202, dependencies=[Depends(RateLimiter(times=5, seconds=60))])
        async def delete_async(
            item_id: int = Path(..., description="ID rekordu do usunięcia"),
            user: str = Depends(require_permission(name, "DELETE"))
        ):
            """
            DELETE /{table_name}/{item_id}
            
            Zwraca: task_id i powiadomienie SSE: DELETED:{name}:{item_id}:{task_id}
            """
            task_id = str(uuid.uuid4())
            process_delete_task.delay(name, item_id, task_id, user)
            return {"task_id": task_id, "message": "Zlecono usunięcie rekordu"}
        
        @app.put(f"/{name}/{{item_id}}", tags=[name], status_code=202, dependencies=[Depends(RateLimiter(times=10, seconds=60))])
        async def update_async(
            item_id: int = Path(..., description="ID rekordu do aktualizacji"),
            data: dict = None,
            user: str = Depends(require_permission(name, "PUT"))
        ):
            """
            PUT /{table_name}/{item_id}
            
            Zwraca: task_id i powiadomienie SSE: UPDATED:{name}:{item_id}:{task_id}
            """
            task_id = str(uuid.uuid4())
            process_update_task.delay(name, item_id, data, task_id, user)
            return {"task_id": task_id, "message": "Zlecono aktualizację rekordu"}
            
    make_routes()

# 2. Strumień SSE (Powiadomienia bez "mielenia" procesora)
@app.get("/stream")
async def message_stream():
    async def event_generator():
        async with aioredis.from_url(redis_url(REDIS_SSE_DB)) as rd:
            pubsub = rd.pubsub()
            await pubsub.subscribe("global_updates")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield {"event": "db_change", "data": message["data"].decode()}
    
    return EventSourceResponse(event_generator())

@app.post("/token", tags=["Auth"], dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    logger.info(f"LOGIN ATTEMPT: User {form_data.username}")
    # 1. Pobieramy klasę użytkownika z naszej fabryki
    UsersClass = MODELS["users"]
    
    async with AsyncSessionLocal() as session:
        # 2. Szukamy użytkownika w Postgresie
        result = await session.execute(
            select(UsersClass).where(UsersClass.username == form_data.username)
        )
        user = result.scalar_one_or_none()

    # 3. Weryfikacja (tu sprawdzasz hash hasła)
    if not user or not verify_password(form_data.password, user.hashed_password):
        logger.warning(f"LOGIN FAILED: Invalid credentials for {form_data.username}")
        await log_access(form_data.username, "AUTHN", "/token", None, "Invalid credentials")
        raise HTTPException(status_code=401, detail="Niepoprawny login lub hasło")

    # 4. TO JEST TO MIEJSCE: Tworzymy token i wkładamy username do pola 'sub'
    access_token = create_access_token(data={"sub": user.username})
    
    logger.info(f"LOGIN SUCCESS: User {form_data.username}")
    await log_access(form_data.username, "AUTHN", "/token", None, "Login successful")
    # 5. Zwracamy token do frontendu 
    refresh_token = create_refresh_token(data={"sub": user.username})
    
    logger.info(f"LOGIN SUCCESS: User {form_data.username}")
    await log_access(form_data.username, "AUTHN", "/token", None, "Login successful")
    # 5. Zwracamy oba tokeny do frontendu
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@app.post("/refresh", tags=["Auth"], dependencies=[Depends(RateLimiter(times=10, seconds=60))])
async def refresh_access_token(refresh_token: str):
    """
    Endpoint do odswiezenia access_token.
    
    Request body (JSON):
    - refresh_token: string - token refresh z poprzedniego logowania
    
    Zwraca nowy access_token bez koniecznosci ponownego logowania.
    """
    # Walidujemy refresh token
    username = validate_refresh_token(refresh_token)
    
    # Tworzymy nowy access token
    new_access_token = create_access_token(data={"sub": username})
    
    logger.info(f"TOKEN REFRESHED: User {username}")
    await log_access(username, "AUTHN", "/refresh", None, "Token refreshed")
    
    return {
        "access_token": new_access_token,
        "token_type": "bearer"
    }

@app.get("/access_logs", tags=["Admin"])
async def get_access_logs(
    user: str = Depends(require_permission("access_logs", "GET")),
    page: int = Query(0, ge=0, description="Numer strony (0-based)"),
    limit: int = Query(100, ge=1, le=1000, description="Liczba rekordów na stronę")
):
    offset = page * limit
    async with AsyncSessionLocal() as session:
        # Pobierz total count
        total = (
            await session.execute(
                select(func.count()).select_from(MODELS["access_logs"])
            )
        ).scalar_one()
        
        # Pobierz stronę
        result = await session.execute(
            select(MODELS["access_logs"])
            .order_by(MODELS["access_logs"].timestamp.desc())
            .offset(offset)
            .limit(limit)
        )
        logs = result.scalars().all()
        
        return {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit,  # ceil(total / limit)
            "data": [serialize_row(log) for log in logs]
        }