"""
Simple admin auth endpoints.
"""
from fastapi import APIRouter, Cookie, Response
from pydantic import BaseModel

from app.auth import (
    ADMIN_COOKIE_NAME,
    ADMIN_SESSION_MAX_AGE,
    create_admin_session,
    verify_admin_session,
)
from app.config import settings

router = APIRouter()


class AdminLoginRequest(BaseModel):
    password: str


@router.post("/login")
async def admin_login(body: AdminLoginRequest, response: Response):
    if body.password != settings.admin_password:
        return {"success": False, "message": "Invalid password"}
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=create_admin_session(),
        httponly=True,
        samesite="lax",
        max_age=ADMIN_SESSION_MAX_AGE,
        secure=False,
    )
    return {"success": True}


@router.post("/logout")
async def admin_logout(response: Response):
    response.delete_cookie(ADMIN_COOKIE_NAME)
    return {"success": True}


@router.get("/session")
async def admin_session(
    response: Response,
    admin_session: str | None = Cookie(default=None, alias=ADMIN_COOKIE_NAME),
):
    is_authenticated = verify_admin_session(admin_session)
    if not is_authenticated and admin_session:
        response.delete_cookie(ADMIN_COOKIE_NAME)
    return {"authenticated": is_authenticated}
