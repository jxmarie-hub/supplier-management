"""Advanced search, Excel export, saved favorite filters."""
from __future__ import annotations

import io
import json
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from openpyxl import Workbook

from app import config
from app.database import (
    build_search_where,
    db_session,
    lookups_by_type,
    supplier_tags_display,
    utc_now,
)
from app.deps import current_user, flash, login_redirect, render, require_csrf, require_login

router = APIRouter(tags=["search"])

FILTER_KEYS = [
    "q",
    "factory_trading_name",
    "contact_name",
    "email",
    "city",
    "website",
    "tel_whatsapp_wechat",
    "notes",
    "status",
    "meet",
    "country",
    "cn_province",
    "nature_of_product",
    "item_group_name",
    "production_method",
    "tag",
]


def _filters_from_request(request: Request) -> dict:
    out = {}
    for k in FILTER_KEYS:
        v = request.query_params.get(k, "")
        if v:
            out[k] = v
    return out


def _run_search(filters: dict) -> list[dict]:
    where, params = build_search_where(filters)
    with db_session() as conn:
        rows = conn.execute(
            f"SELECT * FROM suppliers WHERE {where} ORDER BY factory_trading_name COLLATE NOCASE",
            params,
        ).fetchall()
    return [{**dict(r), "tags": supplier_tags_display(dict(r))} for r in rows]


@router.get("/search")
def search_page(request: Request):
    user = current_user(request)
    if not user:
        return login_redirect()
    filters = _filters_from_request(request)
    results = _run_search(filters) if filters else []
    with db_session() as conn:
        lookups = lookups_by_type(conn)
        saved = []
        for r in conn.execute(
            "SELECT id, name, filters_json, created_at FROM saved_searches WHERE user_id = ? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall():
            d = dict(r)
            try:
                d["filters"] = json.loads(d["filters_json"])
            except Exception:
                d["filters"] = {}
            saved.append(d)
    return render(
        request,
        "search.html",
        {
            "filters": {k: filters.get(k, "") for k in FILTER_KEYS},
            "results": results,
            "lookups": lookups,
            "status_values": config.STATUS_VALUES,
            "saved_searches": saved,
            "searched": bool(filters),
            "max_saved": config.MAX_SAVED_SEARCHES,
            "nav_active": "search",
        },
    )


@router.get("/search/export")
def export_search(request: Request):
    user = current_user(request)
    if not user:
        return login_redirect()
    filters = _filters_from_request(request)
    results = _run_search(filters)
    wb = Workbook()
    ws = wb.active
    ws.title = "Suppliers"
    headers = [
        "ID", "Code", "Status", "Meet", "Country", "CN Province", "City",
        "Factory / Trading Name", "Website", "Contact name", "Email",
        "Tel / WhatsApp / WeChat", "Nature of Product", "Item Group",
        "Production method", "Tag 1", "Tag 2", "Tag 3", "Tag 4", "Notes",
        "Created", "Updated",
    ]
    ws.append(headers)
    for s in results:
        ws.append([
            s.get("id_supplier"), s.get("short_code"), s.get("status"), s.get("meet"),
            s.get("country"), s.get("cn_province"), s.get("city"),
            s.get("factory_trading_name"), s.get("website"), s.get("contact_name"),
            s.get("email"), s.get("tel_whatsapp_wechat"), s.get("nature_of_product"),
            s.get("item_group_name"), s.get("production_method"),
            s.get("tag_1"), s.get("tag_2"), s.get("tag_3"), s.get("tag_4"),
            s.get("notes"), s.get("created_at"), s.get("updated_at"),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=suppliers_export.xlsx"},
    )


@router.post("/search/favorites")
def save_favorite(
    request: Request,
    csrf_token: str = Form(""),
    name: str = Form(...),
    filters_json: str = Form(...),
):
    user = require_login(request)
    require_csrf(request, csrf_token)
    name = name.strip()[:80]
    if not name:
        flash(request, "Favorite name is required.", "error")
        return RedirectResponse(url="/search", status_code=303)
    try:
        filters = json.loads(filters_json)
        if not isinstance(filters, dict):
            raise ValueError("invalid")
    except Exception:
        flash(request, "Invalid filter payload.", "error")
        return RedirectResponse(url="/search", status_code=303)
    # keep only known keys
    clean = {k: str(v) for k, v in filters.items() if k in FILTER_KEYS and v}
    with db_session() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM saved_searches WHERE user_id = ?", (user["id"],)
        ).fetchone()[0]
        if count >= config.MAX_SAVED_SEARCHES:
            flash(
                request,
                f"You already have {config.MAX_SAVED_SEARCHES} saved searches. Delete one first.",
                "error",
            )
            return RedirectResponse(url="/search?" + urlencode(clean), status_code=303)
        conn.execute(
            "INSERT INTO saved_searches (user_id, name, filters_json, created_at) VALUES (?, ?, ?, ?)",
            (user["id"], name, json.dumps(clean), utc_now()),
        )
    flash(request, f'Saved search "{name}".', "success")
    return RedirectResponse(url="/search?" + urlencode(clean), status_code=303)


@router.post("/search/favorites/{fav_id}/delete")
def delete_favorite(request: Request, fav_id: int, csrf_token: str = Form("")):
    user = require_login(request)
    require_csrf(request, csrf_token)
    with db_session() as conn:
        conn.execute(
            "DELETE FROM saved_searches WHERE id = ? AND user_id = ?",
            (fav_id, user["id"]),
        )
    flash(request, "Saved search deleted.", "success")
    return RedirectResponse(url="/search", status_code=303)
