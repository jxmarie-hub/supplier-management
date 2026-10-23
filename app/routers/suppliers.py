"""Supplier CRUD, home table, attachments, column prefs."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from app import config
from app.database import (
    db_session,
    find_duplicate_suppliers,
    lookups_by_type,
    next_short_code,
    normalize_supplier_payload,
    register_tags,
    resolve_tag_similarities,
    set_user_columns,
    supplier_tags_display,
    utc_now,
    validate_supplier_payload,
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

router = APIRouter(tags=["suppliers"])

SUPPLIER_FIELDS = [
    "short_code",
    "status",
    "interest_level",
    "meet",
    "country",
    "cn_province",
    "city",
    "factory_trading_name",
    "website",
    "contact_name",
    "email",
    "tel_whatsapp_wechat",
    "nature_of_product",
    "item_group_name",
    "production_method",
    "tag_1",
    "tag_2",
    "tag_3",
    "tag_4",
    "notes",
]


def _form_to_payload(**kwargs) -> dict:
    return {k: kwargs.get(k, "") for k in SUPPLIER_FIELDS}


def _enrich(supplier: dict) -> dict:
    s = dict(supplier)
    s["tags"] = supplier_tags_display(s)
    return s


def _tag_resolve_map(
    tag_resolve_1: str,
    tag_resolve_2: str,
    tag_resolve_3: str,
    tag_resolve_4: str,
) -> dict[str, str]:
    return {
        "tag_1": tag_resolve_1 or "",
        "tag_2": tag_resolve_2 or "",
        "tag_3": tag_resolve_3 or "",
        "tag_4": tag_resolve_4 or "",
    }


def _username_map(conn, *user_ids) -> dict[int, str]:
    ids = [i for i in user_ids if i]
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, username FROM users WHERE id IN ({placeholders})", ids
    ).fetchall()
    return {r["id"]: r["username"] for r in rows}


def _enrich_attachments(attachments: list[dict]) -> list[dict]:
    """Mark previewable image / PDF attachments for templates."""
    out = []
    for a in attachments:
        item = dict(a)
        ct = (item.get("content_type") or "").lower()
        name = (item.get("filename") or "").lower()
        ext = Path(name).suffix
        is_image = ct.startswith("image/") or ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        is_pdf = ct == "application/pdf" or ext == ".pdf"
        item["is_image"] = is_image
        item["is_pdf"] = is_pdf
        item["can_preview"] = is_image or is_pdf
        out.append(item)
    return out


def _grouping_options(conn, current: str | None = None) -> list[str]:
    """Fixed Grouping dropdown from Jean's seed list."""
    from app.database import get_grouping_options

    opts = get_grouping_options()
    cur = (current or "").strip()
    if cur and cur not in opts:
        opts = [cur] + opts
    return opts


def _form_context(
    mode: str,
    supplier: dict,
    lookups,
    attachments,
    errors,
    duplicates,
    *,
    need_duplicate_confirm: bool = False,
    tag_issues: list | None = None,
    need_tag_confirm: bool = False,
    grouping_options: list | None = None,
) -> dict:
    return {
        "mode": mode,
        "supplier": supplier,
        "lookups": lookups,
        "attachments": _enrich_attachments(attachments),
        "errors": errors,
        "duplicates": duplicates,
        "status_values": config.STATUS_VALUES,
        "interest_level_values": config.INTEREST_LEVEL_VALUES,
        "attachment_types": config.ATTACHMENT_TYPES,
        "need_duplicate_confirm": need_duplicate_confirm,
        "tag_issues": tag_issues or [],
        "need_tag_confirm": need_tag_confirm,
        "grouping_options": grouping_options or [],
        "nav_active": "create" if mode == "create" else "home",
    }


@router.get("/")
def home(
    request: Request,
    sort: str = Query("factory_trading_name"),
    dir: str = Query("asc"),
):
    user = current_user(request)
    if not user:
        return login_redirect()

    if sort == "tags":
        sort_col = "tag_1"
    elif sort in {c[0] for c in config.ALL_COLUMNS}:
        sort_col = sort
    else:
        sort_col = "factory_trading_name"
    direction = "DESC" if dir.lower() == "desc" else "ASC"

    sql = f"SELECT * FROM suppliers ORDER BY {sort_col} COLLATE NOCASE {direction}"
    with db_session() as conn:
        rows = [dict(r) for r in conn.execute(sql).fetchall()]
        visible = load_visible_columns(user["id"])

    return render(
        request,
        "home.html",
        {
            "suppliers": [_enrich(r) for r in rows],
            "sort": sort,
            "dir": "desc" if direction == "DESC" else "asc",
            "visible_columns": visible,
            "column_labels": dict(config.ALL_COLUMNS),
            "nav_active": "home",
        },
    )


@router.post("/columns")
def save_columns(
    request: Request,
    csrf_token: str = Form(""),
    columns: list[str] = Form([]),
    next: str = Form(""),
):
    user = require_login(request)
    require_csrf(request, csrf_token)
    if isinstance(columns, str):
        columns = [columns]
    with db_session() as conn:
        set_user_columns(conn, user["id"], list(columns))
    flash(request, "Column preferences saved.", "success")
    dest = (next or "").strip()
    if not dest.startswith("/") or dest.startswith("//"):
        dest = "/"
    return RedirectResponse(url=dest, status_code=303)


@router.get("/suppliers/new")
def new_supplier_form(request: Request):
    user = current_user(request)
    if not user:
        return login_redirect()
    with db_session() as conn:
        lookups = lookups_by_type(conn)
        suggested = next_short_code(conn)
        grouping_options = _grouping_options(conn)
    blank = {f: "" for f in SUPPLIER_FIELDS}
    blank["country"] = config.DEFAULT_COUNTRY
    blank["status"] = config.DEFAULT_STATUS
    blank["short_code"] = suggested
    return render(
        request,
        "supplier_form.html",
        _form_context("create", blank, lookups, [], [], [], grouping_options=grouping_options),
    )


@router.post("/suppliers/new")
async def create_supplier(
    request: Request,
    csrf_token: str = Form(""),
    short_code: str = Form(""),
    status: str = Form(config.DEFAULT_STATUS),
    interest_level: str = Form(""),
    meet: str = Form(""),
    country: str = Form("China"),
    cn_province: str = Form(""),
    city: str = Form(""),
    factory_trading_name: str = Form(""),
    website: str = Form(""),
    contact_name: str = Form(""),
    email: str = Form(""),
    tel_whatsapp_wechat: str = Form(""),
    nature_of_product: str = Form(""),
    item_group_name: str = Form(""),
    production_method: str = Form(""),
    tag_1: str = Form(""),
    tag_2: str = Form(""),
    tag_3: str = Form(""),
    tag_4: str = Form(""),
    notes: str = Form(""),
    confirm_duplicate: str = Form(""),
    tag_resolve_1: str = Form(""),
    tag_resolve_2: str = Form(""),
    tag_resolve_3: str = Form(""),
    tag_resolve_4: str = Form(""),
    attachment_type: str = Form("other"),
    files: list[UploadFile] = File(default=[]),
):
    user = require_login(request)
    require_csrf(request, csrf_token)
    payload = _form_to_payload(
        short_code=short_code, status=status, interest_level=interest_level, meet=meet, country=country,
        cn_province=cn_province, city=city, factory_trading_name=factory_trading_name,
        website=website, contact_name=contact_name, email=email,
        tel_whatsapp_wechat=tel_whatsapp_wechat, nature_of_product=nature_of_product,
        item_group_name=item_group_name, production_method=production_method,
        tag_1=tag_1, tag_2=tag_2, tag_3=tag_3, tag_4=tag_4, notes=notes,
    )
    payload = normalize_supplier_payload(payload)
    resolve_map = _tag_resolve_map(tag_resolve_1, tag_resolve_2, tag_resolve_3, tag_resolve_4)

    with db_session() as conn:
        lookups = lookups_by_type(conn)
        grouping_options = _grouping_options(conn, payload.get("tag_1"))
        if not payload.get("short_code"):
            payload["short_code"] = next_short_code(conn)
        errors = validate_supplier_payload(payload, lookups)
        existing_code = conn.execute(
            "SELECT id_supplier FROM suppliers WHERE short_code = ? COLLATE NOCASE",
            (payload["short_code"],),
        ).fetchone()
        if existing_code:
            errors.append(f"Short code {payload['short_code']} is already in use.")

        payload, tag_issues = resolve_tag_similarities(conn, payload, resolve_map)
        if tag_issues:
            return render(
                request,
                "supplier_form.html",
                _form_context(
                    "create", payload, lookups, [], errors, [],
                    tag_issues=tag_issues, need_tag_confirm=True,
                    grouping_options=grouping_options,
                ),
                status_code=409,
            )

        duplicates = find_duplicate_suppliers(
            conn, payload.get("factory_trading_name") or "", payload.get("country") or "",
            payload.get("email") or "",
        )
        if duplicates and confirm_duplicate != "1":
            return render(
                request,
                "supplier_form.html",
                _form_context(
                    "create", payload, lookups, [], errors, duplicates,
                    need_duplicate_confirm=True,
                    grouping_options=grouping_options,
                ),
                status_code=409,
            )
        if errors:
            return render(
                request,
                "supplier_form.html",
                _form_context("create", payload, lookups, [], errors, duplicates, grouping_options=grouping_options),
                status_code=400,
            )
        now = utc_now()
        cols = SUPPLIER_FIELDS + ["created_at", "updated_at", "created_by", "updated_by"]
        values = [payload.get(c) for c in SUPPLIER_FIELDS] + [now, now, user["id"], user["id"]]
        cur = conn.execute(
            f"INSERT INTO suppliers ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            values,
        )
        supplier_id = cur.lastrowid
        register_tags(conn, [payload.get(f"tag_{i}") for i in range(1, 5)])
        upload_errors = await _save_uploads(conn, supplier_id, user["id"], files, attachment_type)

    if upload_errors:
        flash(request, "Supplier created, but some files were rejected: " + "; ".join(upload_errors), "error")
    else:
        flash(request, "Supplier created.", "success")
    return RedirectResponse(url=f"/suppliers/{supplier_id}", status_code=303)


@router.get("/suppliers/{supplier_id}")
def view_supplier(request: Request, supplier_id: int):
    """Read-only master-data view."""
    user = current_user(request)
    if not user:
        return login_redirect()
    with db_session() as conn:
        row = conn.execute("SELECT * FROM suppliers WHERE id_supplier = ?", (supplier_id,)).fetchone()
        if not row:
            flash(request, "Supplier not found.", "error")
            return RedirectResponse(url="/", status_code=303)
        supplier = _enrich(dict(row))
        attachments = _enrich_attachments(
            [
                dict(a)
                for a in conn.execute(
                    "SELECT * FROM attachments WHERE supplier_id = ? ORDER BY uploaded_at",
                    (supplier_id,),
                ).fetchall()
            ]
        )
        uploader_ids = [a.get("uploaded_by") for a in attachments]
        unames = _username_map(
            conn, supplier.get("created_by"), supplier.get("updated_by"), *uploader_ids
        )
        supplier["created_by_name"] = unames.get(supplier.get("created_by"), "—")
        supplier["updated_by_name"] = unames.get(supplier.get("updated_by"), "—")
        for a in attachments:
            a["uploaded_by_name"] = unames.get(a.get("uploaded_by"), "—")

    return render(
        request,
        "supplier_view.html",
        {
            "supplier": supplier,
            "attachments": attachments,
            "attachment_types": dict(config.ATTACHMENT_TYPES),
            "nav_active": "home",
        },
    )


@router.get("/suppliers/{supplier_id}/edit")
def edit_supplier_form(request: Request, supplier_id: int):
    user = current_user(request)
    if not user:
        return login_redirect()
    with db_session() as conn:
        row = conn.execute("SELECT * FROM suppliers WHERE id_supplier = ?", (supplier_id,)).fetchone()
        if not row:
            flash(request, "Supplier not found.", "error")
            return RedirectResponse(url="/", status_code=303)
        lookups = lookups_by_type(conn)
        supplier = dict(row)
        grouping_options = _grouping_options(conn, supplier.get("tag_1"))
        attachments = [
            dict(a)
            for a in conn.execute(
                "SELECT * FROM attachments WHERE supplier_id = ? ORDER BY uploaded_at",
                (supplier_id,),
            ).fetchall()
        ]
    return render(
        request,
        "supplier_form.html",
        _form_context("edit", supplier, lookups, attachments, [], [], grouping_options=grouping_options),
    )


@router.post("/suppliers/{supplier_id}/edit")
async def update_supplier(
    request: Request,
    supplier_id: int,
    csrf_token: str = Form(""),
    short_code: str = Form(""),
    status: str = Form("Current"),
    interest_level: str = Form(""),
    meet: str = Form(""),
    country: str = Form("China"),
    cn_province: str = Form(""),
    city: str = Form(""),
    factory_trading_name: str = Form(""),
    website: str = Form(""),
    contact_name: str = Form(""),
    email: str = Form(""),
    tel_whatsapp_wechat: str = Form(""),
    nature_of_product: str = Form(""),
    item_group_name: str = Form(""),
    production_method: str = Form(""),
    tag_1: str = Form(""),
    tag_2: str = Form(""),
    tag_3: str = Form(""),
    tag_4: str = Form(""),
    notes: str = Form(""),
    confirm_duplicate: str = Form(""),
    tag_resolve_1: str = Form(""),
    tag_resolve_2: str = Form(""),
    tag_resolve_3: str = Form(""),
    tag_resolve_4: str = Form(""),
    attachment_type: str = Form("other"),
    files: list[UploadFile] = File(default=[]),
):
    user = require_login(request)
    require_csrf(request, csrf_token)
    payload = _form_to_payload(
        short_code=short_code, status=status, interest_level=interest_level, meet=meet, country=country,
        cn_province=cn_province, city=city, factory_trading_name=factory_trading_name,
        website=website, contact_name=contact_name, email=email,
        tel_whatsapp_wechat=tel_whatsapp_wechat, nature_of_product=nature_of_product,
        item_group_name=item_group_name, production_method=production_method,
        tag_1=tag_1, tag_2=tag_2, tag_3=tag_3, tag_4=tag_4, notes=notes,
    )
    payload = normalize_supplier_payload(payload)
    resolve_map = _tag_resolve_map(tag_resolve_1, tag_resolve_2, tag_resolve_3, tag_resolve_4)

    with db_session() as conn:
        existing = conn.execute(
            "SELECT id_supplier FROM suppliers WHERE id_supplier = ?", (supplier_id,)
        ).fetchone()
        if not existing:
            flash(request, "Supplier not found.", "error")
            return RedirectResponse(url="/", status_code=303)
        lookups = lookups_by_type(conn)
        grouping_options = _grouping_options(conn, payload.get("tag_1"))
        errors = validate_supplier_payload(payload, lookups)
        if payload.get("short_code"):
            clash = conn.execute(
                "SELECT id_supplier FROM suppliers WHERE short_code = ? COLLATE NOCASE AND id_supplier != ?",
                (payload["short_code"], supplier_id),
            ).fetchone()
            if clash:
                errors.append(f"Short code {payload['short_code']} is already in use.")

        payload, tag_issues = resolve_tag_similarities(conn, payload, resolve_map)
        attachments = [
            dict(a)
            for a in conn.execute(
                "SELECT * FROM attachments WHERE supplier_id = ? ORDER BY uploaded_at",
                (supplier_id,),
            ).fetchall()
        ]
        payload["id_supplier"] = supplier_id
        if tag_issues:
            return render(
                request,
                "supplier_form.html",
                _form_context(
                    "edit", payload, lookups, attachments, errors, [],
                    tag_issues=tag_issues, need_tag_confirm=True,
                    grouping_options=grouping_options,
                ),
                status_code=409,
            )

        duplicates = find_duplicate_suppliers(
            conn,
            payload.get("factory_trading_name") or "",
            payload.get("country") or "",
            payload.get("email") or "",
            exclude_id=supplier_id,
        )
        if duplicates and confirm_duplicate != "1":
            return render(
                request,
                "supplier_form.html",
                _form_context(
                    "edit", payload, lookups, attachments, errors, duplicates,
                    need_duplicate_confirm=True,
                    grouping_options=grouping_options,
                ),
                status_code=409,
            )
        if errors:
            return render(
                request,
                "supplier_form.html",
                _form_context("edit", payload, lookups, attachments, errors, duplicates, grouping_options=grouping_options),
                status_code=400,
            )
        sets = ", ".join(f"{c} = ?" for c in SUPPLIER_FIELDS)
        values = [payload.get(c) for c in SUPPLIER_FIELDS] + [utc_now(), user["id"], supplier_id]
        conn.execute(
            f"UPDATE suppliers SET {sets}, updated_at = ?, updated_by = ? WHERE id_supplier = ?",
            values,
        )
        register_tags(conn, [payload.get(f"tag_{i}") for i in range(1, 5)])
        upload_errors = await _save_uploads(conn, supplier_id, user["id"], files, attachment_type)

    if upload_errors:
        flash(request, "Supplier updated, but some files were rejected: " + "; ".join(upload_errors), "error")
    else:
        flash(request, "Supplier updated.", "success")
    return RedirectResponse(url=f"/suppliers/{supplier_id}", status_code=303)


@router.post("/suppliers/{supplier_id}/delete")
def delete_supplier(request: Request, supplier_id: int, csrf_token: str = Form("")):
    require_login(request)
    require_csrf(request, csrf_token)
    with db_session() as conn:
        atts = conn.execute(
            "SELECT stored_path FROM attachments WHERE supplier_id = ?", (supplier_id,)
        ).fetchall()
        conn.execute("DELETE FROM suppliers WHERE id_supplier = ?", (supplier_id,))
    for a in atts:
        path = config.UPLOAD_DIR / a["stored_path"]
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
    flash(request, "Supplier deleted.", "success")
    return RedirectResponse(url="/", status_code=303)


@router.post("/attachments/{attachment_id}/delete")
def delete_attachment(request: Request, attachment_id: int, csrf_token: str = Form("")):
    require_login(request)
    require_csrf(request, csrf_token)
    with db_session() as conn:
        row = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
        if not row:
            flash(request, "Attachment not found.", "error")
            return RedirectResponse(url="/", status_code=303)
        supplier_id = row["supplier_id"]
        conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
    path = config.UPLOAD_DIR / row["stored_path"]
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass
    flash(request, "Attachment deleted.", "success")
    return RedirectResponse(url=f"/suppliers/{supplier_id}/edit", status_code=303)


@router.get("/attachments/{attachment_id}/download")
def download_attachment(request: Request, attachment_id: int):
    user = current_user(request)
    if not user:
        return login_redirect()
    with db_session() as conn:
        row = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    if not row:
        flash(request, "Attachment not found.", "error")
        return RedirectResponse(url="/", status_code=303)
    path = config.UPLOAD_DIR / row["stored_path"]
    if not path.is_file():
        flash(request, "File missing on disk.", "error")
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(
        path,
        filename=row["filename"],
        media_type=row["content_type"] or "application/octet-stream",
    )


@router.get("/attachments/{attachment_id}/preview")
def preview_attachment(request: Request, attachment_id: int):
    """Inline preview for images and PDFs (Content-Disposition: inline)."""
    user = current_user(request)
    if not user:
        return login_redirect()
    with db_session() as conn:
        row = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    if not row:
        flash(request, "Attachment not found.", "error")
        return RedirectResponse(url="/", status_code=303)
    path = config.UPLOAD_DIR / row["stored_path"]
    if not path.is_file():
        flash(request, "File missing on disk.", "error")
        return RedirectResponse(url="/", status_code=303)
    media = row["content_type"] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media,
        filename=row["filename"],
        content_disposition_type="inline",
    )


async def _save_uploads(conn, supplier_id: int, user_id: int, files, attachment_type: str) -> list[str]:
    errors: list[str] = []
    if not files:
        return errors
    if isinstance(files, UploadFile):
        files = [files]
    att_type = attachment_type if attachment_type in {t[0] for t in config.ATTACHMENT_TYPES} else "other"
    dest_dir = config.UPLOAD_DIR / str(supplier_id)
    dest_dir.mkdir(parents=True, exist_ok=True)

    for f in files:
        if not f or not f.filename:
            continue
        original = Path(f.filename).name
        ext = Path(original).suffix.lower()
        if ext not in config.ALLOWED_UPLOAD_EXTENSIONS:
            errors.append(f"{original}: type not allowed")
            continue
        content = await f.read()
        size = len(content)
        if size == 0:
            continue
        if size > config.MAX_UPLOAD_BYTES:
            errors.append(f"{original}: exceeds 15 MB limit")
            continue
        ctype = f.content_type or ""
        stored_name = f"{uuid.uuid4().hex}{ext}"
        rel_path = f"{supplier_id}/{stored_name}"
        (config.UPLOAD_DIR / rel_path).write_bytes(content)
        conn.execute(
            """
            INSERT INTO attachments
            (supplier_id, filename, stored_path, content_type, size_bytes, attachment_type, uploaded_at, uploaded_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (supplier_id, original, rel_path, ctype or None, size, att_type, utc_now(), user_id),
        )
    return errors
