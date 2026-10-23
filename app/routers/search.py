"""Advanced search, Excel export, saved favorite filters."""
from __future__ import annotations

import io
import json
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from app import config
from app.database import (
    build_search_where,
    db_session,
    format_audit_display,
    get_grouping_options,
    lookups_by_type,
    supplier_tags_display,
    utc_now,
)
from app.deps import (
    current_user,
    flash,
    load_visible_columns,
    login_redirect,
    render,
    require_csrf,
    require_login,
)

router = APIRouter(tags=["search"])

FILTER_LABELS = {
    "q": "Quick / wildcard",
    "factory_trading_name": "Factory name",
    "contact_name": "Contact",
    "email": "Email",
    "city": "City",
    "website": "Website",
    "tel_whatsapp_wechat": "Tel / WhatsApp / WeChat",
    "notes": "Notes",
    "status": "Status",
    "interest_level": "Interest level",
    "meet": "Meet",
    "country": "Country",
    "cn_province": "CN Province",
    "nature_of_product": "Nature of Product",
    "item_group_name": "Item Group",
    "production_method": "Production method",
    "grouping": "Grouping",
    "tag": "Tag",
}

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
    "interest_level",
    "meet",
    "country",
    "cn_province",
    "nature_of_product",
    "item_group_name",
    "production_method",
    "grouping",
    "tag",
]


def _filters_from_request(request: Request) -> dict:
    out = {}
    for k in FILTER_KEYS:
        v = request.query_params.get(k, "")
        if v:
            out[k] = v
    return out



FILTER_TO_COLUMN = {
    "factory_trading_name": "factory_trading_name",
    "contact_name": "contact_name",
    "email": "email",
    "city": "city",
    "website": "website",
    "tel_whatsapp_wechat": "tel_whatsapp_wechat",
    "notes": "notes",
    "status": "status",
    "interest_level": "interest_level",
    "meet": "meet",
    "country": "country",
    "cn_province": "cn_province",
    "nature_of_product": "nature_of_product",
    "item_group_name": "item_group_name",
    "production_method": "production_method",
    "grouping": "tag_1",
    "tag": "tags",
}


def _visible_columns_with_filters(user_columns: list[str], filters: dict) -> list[str]:
    """Keep user column prefs, then append any columns used as active filters."""
    allowed = {k for k, _ in config.ALL_COLUMNS}
    out: list[str] = [c for c in user_columns if c in allowed]
    seen = set(out)
    for key, value in filters.items():
        if not value:
            continue
        col = FILTER_TO_COLUMN.get(key)
        if col and col in allowed and col not in seen:
            out.append(col)
            seen.add(col)
    return out


def _resolve_sort(sort: str, dir: str) -> tuple[str, str, str]:
    """Return (sort_key, sql_column, direction ASC|DESC). tags → tag_1 like Home."""
    if sort == "tags":
        sort_col = "tag_1"
        sort_key = "tags"
    elif sort in {c[0] for c in config.ALL_COLUMNS}:
        sort_col = sort
        sort_key = sort
    else:
        sort_col = "factory_trading_name"
        sort_key = "factory_trading_name"
    direction = "DESC" if (dir or "").lower() == "desc" else "ASC"
    return sort_key, sort_col, direction


def _filter_query_string(filters: dict, sort: str | None = None, dir: str | None = None) -> str:
    """Build query string from active filters (+ optional sort/dir) for sort/export links."""
    params = {k: filters[k] for k in FILTER_KEYS if filters.get(k)}
    if sort:
        params["sort"] = sort
    if dir:
        params["dir"] = dir
    return urlencode(params)


def _username_map(conn, rows: list[dict]) -> dict[int, str]:
    ids = {r.get("created_by") for r in rows} | {r.get("updated_by") for r in rows}
    ids = [i for i in ids if i]
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    return {
        r["id"]: r["username"]
        for r in conn.execute(
            f"SELECT id, username FROM users WHERE id IN ({placeholders})", ids
        ).fetchall()
    }


def _run_search(
    filters: dict,
    sort: str = "factory_trading_name",
    dir: str = "asc",
) -> list[dict]:
    where, params = build_search_where(filters)
    sort_key, sort_col, direction = _resolve_sort(sort, dir)
    with db_session() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM suppliers WHERE {where} ORDER BY {sort_col} COLLATE NOCASE {direction}",
                params,
            ).fetchall()
        ]
        unames = _username_map(conn, rows)
    out = []
    for r in rows:
        item = {**r, "tags": supplier_tags_display(r)}
        item["created_at"] = format_audit_display(
            r.get("created_at"), unames.get(r.get("created_by"))
        )
        item["updated_at"] = format_audit_display(
            r.get("updated_at"), unames.get(r.get("updated_by"))
        )
        out.append(item)
    return out


@router.get("/search")
def search_page(request: Request):
    user = current_user(request)
    if not user:
        return login_redirect()
    filters = _filters_from_request(request)
    sort_param = request.query_params.get("sort", "factory_trading_name")
    dir_param = request.query_params.get("dir", "asc")
    sort_key, _sort_col, direction = _resolve_sort(sort_param, dir_param)
    dir_out = "desc" if direction == "DESC" else "asc"
    results = _run_search(filters, sort=sort_key, dir=dir_out) if filters else []
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
    visible = _visible_columns_with_filters(load_visible_columns(user["id"]), filters)
    active_filters = [
        {"key": k, "label": FILTER_LABELS.get(k, k), "value": filters[k]}
        for k in FILTER_KEYS
        if filters.get(k)
    ]
    filter_qs = _filter_query_string(filters)
    return render(
        request,
        "search.html",
        {
            "filters": {k: filters.get(k, "") for k in FILTER_KEYS},
            "active_filters": active_filters,
            "results": results,
            "lookups": lookups,
            "status_values": config.STATUS_VALUES,
            "interest_level_values": config.INTEREST_LEVEL_VALUES,
            "grouping_options": get_grouping_options(),
            "saved_searches": saved,
            "searched": bool(filters),
            "max_saved": config.MAX_SAVED_SEARCHES,
            "visible_columns": visible,
            "column_labels": dict(config.ALL_COLUMNS),
            "all_columns": config.ALL_COLUMNS,
            "sort": sort_key,
            "dir": dir_out,
            "filter_qs": filter_qs,
            "nav_active": "search",
        },
    )


def _cell_value_for_export(supplier: dict, key: str):
    """Match on-screen search result cell content for Excel."""
    if key == "tags":
        return supplier.get("tags") or ""
    if key == "notes":
        return supplier.get("notes") or ""
    return supplier.get(key) or ""


@router.get("/search/export")
def export_search(request: Request):
    """Excel export: all ALL_COLUMNS fields for the filtered result set; AutoFilter on, widths fitted."""
    user = current_user(request)
    if not user:
        return login_redirect()
    filters = _filters_from_request(request)
    results = _run_search(filters)
    # Every supplier field (ALL_COLUMNS order). Never include numeric id_supplier.
    export_keys = [k for k, _ in config.ALL_COLUMNS]
    headers = [label for _, label in config.ALL_COLUMNS]

    wb = Workbook()
    ws = wb.active
    ws.title = "Suppliers"
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for s in results:
        ws.append([_cell_value_for_export(s, key) for key in export_keys])

    # AutoFilter on header row (ready for Excel column filters)
    last_row = max(1, len(results) + 1)
    last_col = max(1, len(headers))
    ws.auto_filter.ref = f"A1:{get_column_letter(last_col)}{last_row}"

    # Freeze header
    ws.freeze_panes = "A2"

    # Column widths auto-sized to content
    for col_idx in range(1, last_col + 1):
        letter = get_column_letter(col_idx)
        max_len = 0
        for row in ws.iter_rows(min_col=col_idx, max_col=col_idx, min_row=1, max_row=last_row):
            val = row[0].value
            if val is None:
                continue
            max_len = max(max_len, len(str(val)))
        # Cap very wide columns; leave a little padding
        ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 48)

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
