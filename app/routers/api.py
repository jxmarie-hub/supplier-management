"""JSON API endpoints (tag autocomplete + similarity)."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.database import db_session, find_similar_tag_labels
from app.deps import current_user

router = APIRouter(prefix="/api", tags=["api"])


def _like_contains(q: str) -> str:
    """SQL LIKE substring pattern; use with ESCAPE '\\'."""
    escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f"%{escaped}%"


@router.get("/tags")
def tag_suggestions(request: Request, q: str = Query("", max_length=100)):
    user = current_user(request)
    if not user:
        return JSONResponse({"tags": []}, status_code=401)
    q = (q or "").strip()
    if len(q) < 1:
        return {"tags": []}
    like = _like_contains(q)
    with db_session() as conn:
        # Live Tag 2–4 only — never orphan known_tags or Grouping (tag_1)
        rows = conn.execute(
            """
            SELECT DISTINCT tag FROM (
                SELECT tag_2 AS tag FROM suppliers
                WHERE tag_2 IS NOT NULL AND TRIM(tag_2) != ''
                UNION
                SELECT tag_3 FROM suppliers
                WHERE tag_3 IS NOT NULL AND TRIM(tag_3) != ''
                UNION
                SELECT tag_4 FROM suppliers
                WHERE tag_4 IS NOT NULL AND TRIM(tag_4) != ''
            )
            WHERE tag LIKE ? ESCAPE '\\' COLLATE NOCASE
            ORDER BY tag COLLATE NOCASE
            LIMIT 20
            """,
            (like,),
        ).fetchall()
    return {"tags": [r["tag"] for r in rows]}


@router.get("/tags/similar")
def tag_similar(request: Request, q: str = Query("", max_length=100)):
    """Return existing tags similar to q (for unify prompt)."""
    user = current_user(request)
    if not user:
        return JSONResponse({"similar": []}, status_code=401)
    q = (q or "").strip()
    if len(q) < 1:
        return {"similar": []}
    with db_session() as conn:
        similar = find_similar_tag_labels(conn, q)
    return {"similar": similar, "typed": q}
