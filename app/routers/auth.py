"""Login / logout routes."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.database import db_session, verify_password
from app.deps import current_user, flash, get_csrf_token, render, require_csrf

router = APIRouter(tags=["auth"])


@router.get("/login")
def login_page(request: Request):
    if current_user(request):
        return RedirectResponse(url="/", status_code=303)
    return render(request, "login.html")


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(""),
):
    require_csrf(request, csrf_token)
    with db_session() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, role, is_active FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
    if not row or not row["is_active"] or not verify_password(password, row["password_hash"]):
        flash(request, "Invalid username or password.", "error")
        return render(request, "login.html", {"username": username}, status_code=401)

    # Rotate CSRF on login
    request.session["csrf_token"] = get_csrf_token(request)
    request.session["user"] = {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
    }
    flash(request, f"Welcome, {row['username']}.", "success")
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form("")):
    require_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
