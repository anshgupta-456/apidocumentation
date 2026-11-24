from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import auth
from app.config import settings

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    username: str = Field("", max_length=200)
    password: str = Field("", max_length=500)


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    if not settings.auth_enabled:
        return {"authenticated": True, "auth_enabled": False, "username": "anonymous"}

    client = request.client.host if request.client else "unknown"
    if auth.rate_limited(client):
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in a few minutes.")
    if not auth.check_credentials(payload.username.strip(), payload.password):
        auth.record_failure(client)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    auth.reset_failures(client)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.create_session_token(settings.ADMIN_USERNAME),
        max_age=settings.SESSION_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return {"authenticated": True, "auth_enabled": True, "username": settings.ADMIN_USERNAME}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"authenticated": False}


@router.get("/me")
def me(request: Request):
    user = auth.current_user(request)
    return {"authenticated": user is not None, "auth_enabled": settings.auth_enabled, "username": user}
