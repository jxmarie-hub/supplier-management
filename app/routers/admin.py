"""Admin: users, lookup lists, tag merge."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import config
from app.database import db_session, hash_password, merge_known_tags, utc_now
from app.deps import current_user, flash, login_redirect, render, require_admin, require_csrf

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("")
def admin_home(request: Request):
    user = current_user(request)
    if not user:
        return login_redirect()
    if user.get("role") != "admin":
        flash(request, "Admin access required.", "error")
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url="/admin/users", status_code=303)


@router.get("/users")
def users_page(request: Request):
    user = current_user(request)
    if not user or user.get("role") != "admin":
        flash(request, "Admin access required.", "error")
        return RedirectResponse(url="/", status_code=303)
    with db_session() as conn:
        users = [
            dict(r)
            for r in conn.execute(
                "SELECT id, username, role, is_active, created_at FROM users ORDER BY username COLLATE NOCASE"
            ).fetchall()
        ]
    return render(request, "admin_users.html", {"users": users, "nav_active": "users"})


@router.post("/users")
def create_user(
    request: Request,
    csrf_token: str = Form(""),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("standard"),
):
    require_admin(request)
    require_csrf(request, csrf_token)
    username = username.strip()
    role = role if role in ("admin", "standard") else "standard"
    if not username or len(password) < 6:
        flash(request, "Username required; password must be at least 6 characters.", "error")
        return RedirectResponse(url="/admin/users", status_code=303)
    with db_session() as conn:
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
                (username, hash_password(password), role, utc_now()),
            )
        except Exception:
            flash(request, "Username already exists.", "error")
            return RedirectResponse(url="/admin/users", status_code=303)
    flash(request, f"User {username} created.", "success")
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/toggle")
def toggle_user(request: Request, user_id: int, csrf_token: str = Form("")):
    admin = require_admin(request)
    require_csrf(request, csrf_token)
    if user_id == admin["id"]:
        flash(request, "You cannot deactivate your own account.", "error")
        return RedirectResponse(url="/admin/users", status_code=303)
    with db_session() as conn:
        row = conn.execute("SELECT is_active FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            flash(request, "User not found.", "error")
        else:
            conn.execute(
                "UPDATE users SET is_active = ? WHERE id = ?",
                (0 if row["is_active"] else 1, user_id),
            )
            flash(request, "User status updated.", "success")
    return RedirectResponse(url="/admin/users", status_code=303)


@router.get("/lookups")
def lookups_page(request: Request, type: str = "country"):
    user = current_user(request)
    if not user or user.get("role") != "admin":
        flash(request, "Admin access required.", "error")
        return RedirectResponse(url="/", status_code=303)
    if type not in config.LOOKUP_TYPES:
        type = "country"
    with db_session() as conn:
        values = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM lookup_values WHERE lookup_type = ? ORDER BY sort_order, value COLLATE NOCASE",
                (type,),
            ).fetchall()
        ]
    return render(
        request,
        "admin_lookups.html",
        {
            "lookup_type": type,
            "lookup_labels": config.LOOKUP_LABELS,
            "lookup_types": config.LOOKUP_TYPES,
            "values": values,
            "nav_active": "lists",
        },
    )


@router.post("/lookups")
def add_lookup(
    request: Request,
    csrf_token: str = Form(""),
    lookup_type: str = Form(...),
    value: str = Form(...),
):
    require_admin(request)
    require_csrf(request, csrf_token)
    if lookup_type not in config.LOOKUP_TYPES:
        flash(request, "Invalid list type.", "error")
        return RedirectResponse(url="/admin/lookups", status_code=303)
    value = value.strip()
    if not value:
        flash(request, "Value is required.", "error")
        return RedirectResponse(url=f"/admin/lookups?type={lookup_type}", status_code=303)
    with db_session() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM lookup_values WHERE lookup_type = ?",
            (lookup_type,),
        ).fetchone()[0]
        try:
            conn.execute(
                "INSERT INTO lookup_values (lookup_type, value, sort_order, is_active) VALUES (?, ?, ?, 1)",
                (lookup_type, value, max_order + 1),
            )
            flash(request, f'Added "{value}".', "success")
        except Exception:
            flash(request, "Value already exists.", "error")
    return RedirectResponse(url=f"/admin/lookups?type={lookup_type}", status_code=303)


@router.post("/lookups/{value_id}/toggle")
def toggle_lookup(request: Request, value_id: int, csrf_token: str = Form(""), lookup_type: str = Form("country")):
    require_admin(request)
    require_csrf(request, csrf_token)
    with db_session() as conn:
        row = conn.execute("SELECT is_active, lookup_type FROM lookup_values WHERE id = ?", (value_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE lookup_values SET is_active = ? WHERE id = ?",
                (0 if row["is_active"] else 1, value_id),
            )
            lookup_type = row["lookup_type"]
            flash(request, "List value updated.", "success")
    return RedirectResponse(url=f"/admin/lookups?type={lookup_type}", status_code=303)


@router.get("/tags")
def tags_page(request: Request):
    user = current_user(request)
    if not user or user.get("role") != "admin":
        flash(request, "Admin access required.", "error")
        return RedirectResponse(url="/", status_code=303)
    with db_session() as conn:
        tags = [
            dict(r)
            for r in conn.execute(
                "SELECT id, tag, created_at FROM known_tags ORDER BY tag COLLATE NOCASE"
            ).fetchall()
        ]
    return render(request, "admin_tags.html", {"tags": tags, "nav_active": "tags"})


@router.post("/tags/merge")
def tags_merge(
    request: Request,
    csrf_token: str = Form(""),
    source_tag: str = Form(...),
    target_tag: str = Form(...),
):
    require_admin(request)
    require_csrf(request, csrf_token)
    with db_session() as conn:
        n = merge_known_tags(conn, source_tag, target_tag)
    flash(request, f'Merged "{source_tag}" → "{target_tag}" ({n} supplier fields updated).', "success")
    return RedirectResponse(url="/admin/tags", status_code=303)
