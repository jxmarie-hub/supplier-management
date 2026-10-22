"""JSON API endpoints (tag autocomplete + similarity)."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.database import db_session, find_similar_tag_labels
from app.deps import current_user

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/tags")
def tag_suggestions(request: Request, q: str = Query("", max_length=100)):
    user = current_user(request)
    if not user:
        return JSONResponse({"tags": []}, status_code=401)
    q = (q or "").strip()
    if len(q) < 1:
        return {"tags": []}
    like = f"%{q}%"
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT tag FROM (
                SELECT tag FROM known_tags
                UNION
                SELECT tag_1 AS tag FROM suppliers WHERE tag_1 IS NOT NULL AND tag_1 != ''
                UNION SELECT tag_2 FROM suppliers WHERE tag_2 IS NOT NULL AND tag_2 != ''
                UNION SELECT tag_3 FROM suppliers WHERE tag_3 IS NOT NULL AND tag_3 != ''
                UNION SELECT tag_4 FROM suppliers WHERE tag_4 IS NOT NULL AND tag_4 != ''
            )
            WHERE tag LIKE ? COLLATE NOCASE
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
