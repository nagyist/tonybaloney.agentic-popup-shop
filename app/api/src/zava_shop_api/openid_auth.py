import logging
from fastapi import Header, HTTPException, status
from keycloak import KeycloakOpenID
from keycloak.exceptions import KeycloakAuthenticationError
from zava_shop_api.models import TokenData

from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    keycloak_server_url: str = Field(..., env="KEYCLOAK_SERVER_URL")
    keycloak_realm: str = Field(..., env="KEYCLOAK_REALM")
    keycloak_client_id: str = Field(..., env="KEYCLOAK_CLIENT_ID")
    keycloak_client_secret: str = Field(..., env="KEYCLOAK_CLIENT_SECRET")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

logger = logging.getLogger(__name__)


settings = Settings()

keycloak_openid = KeycloakOpenID(
    server_url=settings.keycloak_server_url,
    realm_name=settings.keycloak_realm,
    client_id=settings.keycloak_client_id,
    client_secret_key=settings.keycloak_client_secret,
)

class AuthService:
    # TODO: Make this async
    @staticmethod
    def authenticate_user(username: str, password: str) -> tuple[str, TokenData]:
        """
        Authenticate the user using Keycloak and return an access token.
        """
        try:
            token = keycloak_openid.token(username, password)
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid username or password",
                )
            # Fetch user info to get roles or other details
            logger.warning(f"token: {token}")
            # TODO: Find a way of joining these.
            user_info = keycloak_openid.userinfo(token["access_token"])
            return token["access_token"], TokenData(username=username, user_role=user_info.get("role", "customer"))
        except KeycloakAuthenticationError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

    # TODO: Make this async
    @staticmethod
    def verify_token(token: str) -> TokenData:
        """
        Verify the given token and return user information.
        """
        try:
            user_info = keycloak_openid.userinfo(token)
            if not user_info:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
                )
            return TokenData(
                username=user_info["username"],
                user_role=user_info.get("role", "customer"),
            )
        except KeycloakAuthenticationError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )

async def get_current_user(authorization: str = Header(...)) -> TokenData:
    """
    Dependency to get current user from bearer token.
    Raises HTTPException if token is invalid or missing.
    """
    if not authorization.startswith("Bearer "):
        logger.warning("Missing or invalid Authorization header (not bearer)")
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.replace("Bearer ", "")

    token_data = AuthService.verify_token(token)
    if token_data is None:
        logger.warning("Invalid or expired token")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token_data


async def get_current_user_from_token(token: str) -> TokenData:
    """Get user data from a token string directly."""
    token_data = AuthService.verify_token(token)
    if token_data is None:
        logger.warning("Invalid or expired token for user retrieval")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token_data

async def logout_user(token: str) -> None:
    # TODO
    pass