"""Shared request helpers: auth, CSRF, flash, template render."""
from __future__ import annotations

import secrets
from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import config
from app.database import db_session, get_user_columns

templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))


def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def require_csrf(request: Request, csrf_token: Optional[str]) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not csrf_token or not secrets.compare_digest(expected, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def current_user(request: Request) -> Optional[dict]:
    user = request.session.get("user")
    if not isinstance(user, dict) or "id" not in user:
        return None
    return user


def require_login(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def require_admin(request: Request) -> dict:
    user = require_login(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def flash(request: Request, message: str, category: str = "info") -> None:
    messages = request.session.get("flash", [])
    messages.append({"message": message, "category": category})
    request.session["flash"] = messages


def pop_flash(request: Request) -> list:
    return request.session.pop("flash", [])


def login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


def render(
    request: Request,
    template_name: str,
    context: Optional[dict[str, Any]] = None,
    status_code: int = 200,
) -> HTMLResponse:
    ctx: dict[str, Any] = {
        "request": request,
        "user": current_user(request),
        "csrf_token": get_csrf_token(request),
        "flash_messages": pop_flash(request),
        "all_columns": config.ALL_COLUMNS,
        "notes_max_len": config.NOTES_MAX_LEN,
        "max_upload_mb": config.MAX_UPLOAD_BYTES // (1024 * 1024),
        "nav_active": "",
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(template_name, ctx, status_code=status_code)


def load_visible_columns(user_id: int) -> list[str]:
    with db_session() as conn:
        return get_user_columns(conn, user_id)
