from __future__ import annotations

from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from fastapi import HTTPException, status

from zava_shop_api.models import TokenData


class SQLiteTokenStore:
    def __init__(self, database_url: str, token_ttl_minutes: int = 60):
        self.database_url = database_url
        self.token_ttl_minutes = token_ttl_minutes
        self._tokens: dict[str, tuple[TokenData, datetime]] = {}

    async def initialize(self) -> None:
        return None

    async def store_token(self, token: str, token_data: TokenData) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.token_ttl_minutes)
        self._tokens[token] = (token_data, expires_at)

    async def get_token(self, token: str) -> TokenData | None:
        record = self._tokens.get(token)
        if record is None:
            return None
        token_data, expires_at = record
        if expires_at <= datetime.now(timezone.utc):
            self._tokens.pop(token, None)
            return None
        return token_data

    async def delete_token(self, token: str) -> bool:
        return self._tokens.pop(token, None) is not None

    async def delete_user_tokens(self, username: str) -> int:
        keys = [token for token, (token_data, _) in self._tokens.items() if token_data.username == username]
        for token in keys:
            self._tokens.pop(token, None)
        return len(keys)

    async def cleanup_expired_tokens(self) -> int:
        now = datetime.now(timezone.utc)
        expired = [token for token, (_, expires_at) in self._tokens.items() if expires_at <= now]
        for token in expired:
            self._tokens.pop(token, None)
        return len(expired)


USERS: dict[str, tuple[str, TokenData]] = {
    "admin": (
        "admin123",
        TokenData(username="admin", user_role="admin", store_id=None, customer_id=None),
    ),
    "stacey": (
        "stacey123",
        TokenData(username="stacey", user_role="customer", store_id=1, customer_id=4),
    ),
}


token_store = SQLiteTokenStore("sqlite+aiosqlite:///:memory:")


async def authenticate_user(username: str, password: str) -> tuple[str, TokenData]:
    user = USERS.get(username)
    if user is None or user[0] != password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    token = token_urlsafe(24)
    token_data = user[1]
    await token_store.store_token(token, token_data)
    return token, token_data


async def get_current_user_from_token(token: str) -> TokenData:
    token_data = await token_store.get_token(token)
    if token_data is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return token_data


async def logout_user(token: str) -> bool:
    return await token_store.delete_token(token)


async def logout_all_user_sessions(username: str) -> int:
    return await token_store.delete_user_tokens(username)
