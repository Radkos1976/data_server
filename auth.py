from datetime import datetime, timedelta, timezone
from typing import Optional
import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select

from access_logging import log_access
from config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, SECRET_KEY
from config import REFRESH_TOKEN_EXPIRE_DAYS

logger = logging.getLogger(__name__)

#hierarchia ról (im wyższa, tym większe uprawnienia)
# ROLE_HIERARCHY = {
#     "admin": 100,
#     "manager": 50,
#     "user": 10,
#     "guest": 0
# }

# Schemat OAuth2 - mówi FastAPI, skąd brać token (nagłówek Authorization)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Konfiguracja hashowania haseł
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- NARZĘDZIA DO HASEŁ ---

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

# --- LOGIKA JWT ---

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    # Tutaj używamy SECRET_KEY do stworzenia podpisu cyfrowego
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict) -> str:
    """Tworzy refresh token z dluzszym czasem wygasniecia (domyslnie 7 dni)."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# --- LOGIKA UŻYTKOWNIKA I UPRAWNIEŃ ---

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Wyciąga użytkownika z tokena i weryfikuje go."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nie można zweryfikować poświadczeń",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Dekodowanie tokena przy użyciu SECRET_KEY
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            logger.warning(f"FAILED AUTH: Invalid token payload")
            await log_access("unknown", "AUTHN", "/token", None, "Invalid token payload")
            raise credentials_exception
    except JWTError:
        logger.warning(f"FAILED AUTH: JWT decode error")
        await log_access("unknown", "AUTHN", "/token", None, "JWT decode error")
        raise credentials_exception
    logger.info(f"SUCCESS AUTH: User {username} authenticated")
    await log_access(username, "AUTHN", "/token", None, "Authenticated")
    return username

def validate_refresh_token(token: str) -> str:
    """Waliduje refresh token i zwraca username. Rzuca HTTPException jesli token niepoprawny."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Niepoprawny lub wygasly refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # Sprawdzamy czy to refresh token
        if payload.get("type") != "refresh":
            logger.warning(f"FAILED REFRESH: Token is not refresh token")
            raise credentials_exception
        username: str = payload.get("sub")
        if username is None:
            logger.warning(f"FAILED REFRESH: Invalid token payload")
            raise credentials_exception
        return username
    except JWTError:
        logger.warning(f"FAILED REFRESH: JWT decode error")
        raise credentials_exception

# Zaimportuj MODELS i AsyncSessionLocal tutaj lub wewnątrz funkcji, by uniknąć circular import
from database import MODELS, AsyncSessionLocal, sync_engine
from sqlalchemy import select

# Ładowanie hierarchii ról z bazy danych
def get_role_hierarchy():
    RoleClass = MODELS.get("roles")
    if not RoleClass:
        return {}
    
    with sync_engine.connect() as conn:
        result = conn.execute(select(RoleClass.name, RoleClass.power))
        return {row[0]: row[1] for row in result}

#hierarchia ról (im wyższa, tym większe uprawnienia)
ROLE_HIERARCHY = get_role_hierarchy()

# Ładowanie słownika permissions z bazy danych
def load_permissions_dict():
    PermissionClass = MODELS.get("permissions")
    if not PermissionClass:
        return {}
    
    with sync_engine.connect() as conn:
        result = conn.execute(select(PermissionClass.table_name, PermissionClass.action, PermissionClass.required_role))
        return {(row[0], row[1]): row[2] for row in result}

PERMISSIONS_DICT = load_permissions_dict()

async def user_has_role(username: str, required_role: str) -> bool:
    UserClass = MODELS.get("users")
    RoleClass = MODELS.get("roles")
    if not UserClass or not RoleClass:
        return False

    async with AsyncSessionLocal() as session:
        statement = select(UserClass).where(UserClass.username == username)
        result = await session.execute(statement)
        user = result.scalar_one_or_none()
        
        if not user:
            return False
        
        if not user.is_active:
            return False
        
        # Jeśli użytkownik nie ma roli, traktuj jako guest
        if user.role_id is None:
            user_power = 0
        else:
            # Pobierz nazwę roli użytkownika na podstawie role_id
            role_statement = select(RoleClass.name, RoleClass.power).where(RoleClass.id == user.role_id)
            role_result = await session.execute(role_statement)
            role_row = role_result.first()
            if not role_row:
                # Jeśli rola nie istnieje w bazie, traktuj jako guest
                user_power = 0
            else:
                _, user_power = role_row
        
        # Pobieramy wagę wymaganej roli dla endpointu
        required_power = ROLE_HIERARCHY.get(required_role, 0)
        
        # LOGIKA HIERARCHII: Czy użytkownik ma moc większą lub równą wymaganej?
        return user_power >= required_power

def get_required_role_for_action(table_name: str, action: str) -> str:
    required_role = PERMISSIONS_DICT.get((table_name, action))
    if required_role:
        return required_role

    # Domyślny enum, gdy tabela/akcja brak w permissions
    default_roles = {"GET": "guest", "POST": "user", "PUT": "user", "DELETE": "manager"}
    return default_roles.get(action, "admin")


def require_permission(table_name: str, action: str):
    """Dependency do sprawdzania uprawnień per tabela/akcja."""
    async def permission_checker(
        request: Request,
        username: str = Depends(get_current_user)
    ):
        required_role = get_required_role_for_action(table_name, action)
        if not await user_has_role(username, required_role):
            logger.warning(f"ACCESS DENIED: User {username} tried {action} on {table_name}, required {required_role}")
            await log_access(
                username,
                "AUTHZ",
                request.url.path,
                None,
                f"Access denied for {action}, required {required_role}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Brak uprawnień dla {action} na tabeli {table_name}. Wymagano: {required_role}"
            )
        logger.info(f"ACCESS GRANTED: User {username} {action} on {table_name}")
        request.state.username = username
        await log_access(
            username,
            "AUTHZ",
            request.url.path,
            None,
            f"Access granted for {action}, required {required_role}"
        )
        return username
    return permission_checker
