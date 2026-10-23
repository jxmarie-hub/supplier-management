"""SQLite database layer: schema, seed, helpers."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

import bcrypt

from app import config


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")



def first_name_from_username(username: str | None) -> str:
    """First token of username (e.g. 'Jean Marie' → 'Jean'; 'Utilisateur1' as-is)."""
    value = (username or "").strip()
    if not value:
        return ""
    return value.split()[0]


def format_audit_display(ts: str | None, username: str | None = None) -> str:
    """Date-only + first name for Created/Updated display (DB keeps full timestamps)."""
    raw = (str(ts).strip() if ts is not None else "")
    date_part = raw[:10] if raw else ""
    name = first_name_from_username(username)
    if date_part and name:
        return f"{date_part} {name}"
    return date_part or name or ""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def get_connection() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'standard')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lookup_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lookup_type TEXT NOT NULL,
    value TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(lookup_type, value)
);

CREATE TABLE IF NOT EXISTS known_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suppliers (
    id_supplier INTEGER PRIMARY KEY AUTOINCREMENT,
    short_code TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'Current'
        CHECK(status IN ('Current', 'Prospect', 'Inactive')),
    interest_level TEXT,
    meet TEXT,
    country TEXT NOT NULL,
    cn_province TEXT,
    city TEXT,
    factory_trading_name TEXT NOT NULL,
    website TEXT,
    contact_name TEXT,
    email TEXT,
    tel_whatsapp_wechat TEXT,
    nature_of_product TEXT,
    item_group_name TEXT,
    production_method TEXT,
    tag_1 TEXT,
    tag_2 TEXT,
    tag_3 TEXT,
    tag_4 TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    updated_by INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id_supplier) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    content_type TEXT,
    size_bytes INTEGER NOT NULL,
    attachment_type TEXT NOT NULL DEFAULT 'other'
        CHECK(attachment_type IN ('factory_photo', 'catalog', 'business_card', 'other')),
    uploaded_at TEXT NOT NULL,
    uploaded_by INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS user_column_prefs (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    columns_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    filters_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_suppliers_factory ON suppliers(factory_trading_name);
CREATE INDEX IF NOT EXISTS idx_suppliers_country ON suppliers(country);
CREATE INDEX IF NOT EXISTS idx_suppliers_status ON suppliers(status);
CREATE INDEX IF NOT EXISTS idx_suppliers_email ON suppliers(email);
CREATE INDEX IF NOT EXISTS idx_suppliers_short_code ON suppliers(short_code);
CREATE INDEX IF NOT EXISTS idx_lookup_type ON lookup_values(lookup_type);
CREATE INDEX IF NOT EXISTS idx_known_tags ON known_tags(tag);
CREATE INDEX IF NOT EXISTS idx_saved_searches_user ON saved_searches(user_id);
"""


def init_db() -> None:
    with db_session() as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_schema(conn)
        _seed_if_empty(conn)
        _sync_lookups_from_seed(conn)
        _migrate_grouping_list(conn)
        _migrate_column_prefs_full(conn)
        # Drop orphan known_tags so Admin list matches live usage;
        # create/edit suggestions already ignore known_tags entirely.
        prune_unused_known_tags(conn)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Additive SQLite migrations for existing databases."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(suppliers)").fetchall()}
    if "interest_level" not in cols:
        conn.execute("ALTER TABLE suppliers ADD COLUMN interest_level TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def _migrate_grouping_list(conn: sqlite3.Connection) -> None:
    """Remap/clear supplier tag_1 to match Jean's current Grouping list (no DELETE)."""
    allowed = get_grouping_options()
    allowed_cf = {v.casefold(): v for v in allowed}
    # Preferred remaps for known renames (case-insensitive).
    remaps = {
        "fencing": "Animal husbandry / Livestock accessories",
        "animal husbandry / fencing": "Animal husbandry / Livestock accessories",
    }
    rows = conn.execute(
        "SELECT id_supplier, tag_1 FROM suppliers "
        "WHERE tag_1 IS NOT NULL AND TRIM(tag_1) != ''"
    ).fetchall()
    for row in rows:
        raw = (row["tag_1"] or "").strip()
        if not raw:
            continue
        key = raw.casefold()
        if key in allowed_cf:
            canonical = allowed_cf[key]
            if canonical != raw:
                conn.execute(
                    "UPDATE suppliers SET tag_1 = ? WHERE id_supplier = ?",
                    (canonical, row["id_supplier"]),
                )
            continue
        if key in remaps:
            conn.execute(
                "UPDATE suppliers SET tag_1 = ? WHERE id_supplier = ?",
                (remaps[key], row["id_supplier"]),
            )
            continue
        # Unknown old value: clear (OEM may stay empty; Finish product re-picked on edit).
        conn.execute(
            "UPDATE suppliers SET tag_1 = '' WHERE id_supplier = ?",
            (row["id_supplier"],),
        )


def _migrate_column_prefs_full(conn: sqlite3.Connection) -> None:
    """One-shot: reset saved column prefs to Jean's full default order."""
    row = conn.execute(
        "SELECT value FROM app_meta WHERE key = 'column_prefs_version'"
    ).fetchone()
    if row and row["value"] == "full_v1":
        return
    payload = json.dumps(list(config.DEFAULT_VISIBLE_COLUMNS))
    for pref in conn.execute("SELECT user_id FROM user_column_prefs").fetchall():
        conn.execute(
            "UPDATE user_column_prefs SET columns_json = ? WHERE user_id = ?",
            (payload, pref["user_id"]),
        )
    conn.execute(
        """
        INSERT INTO app_meta (key, value) VALUES ('column_prefs_version', 'full_v1')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """
    )


def _load_seed_data() -> dict:
    path = config.SEED_LOOKUPS_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_grouping_options() -> list[str]:
    """Fixed Grouping dropdown from Jean's seed list (tag_1)."""
    data = _load_seed_data()
    out: list[str] = []
    seen: set[str] = set()
    for raw in data.get("groupings", []):
        value = _clean_lookup_value(raw)
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _sync_lookups_from_seed(conn: sqlite3.Connection) -> None:
    """Replace lookup_values so live DB matches seed_lookups.json exactly."""
    data = _load_seed_data()
    mapping = {
        "country": data.get("countries", []),
        "cn_province": data.get("cn_provinces", []),
        "item_group_name": data.get("item_groups", []),
        "production_method": data.get("production_methods", []),
        "nature_of_product": data.get("natures", []),
        "meet": data.get("meets", []),
    }
    for lookup_type, values in mapping.items():
        wanted: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = _clean_lookup_value(raw)
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            wanted.append(value)
        allowed = set(wanted)
        rows = conn.execute(
            "SELECT id, value FROM lookup_values WHERE lookup_type = ?",
            (lookup_type,),
        ).fetchall()
        for row in rows:
            if (row["value"] or "").strip() not in allowed:
                conn.execute("DELETE FROM lookup_values WHERE id = ?", (row["id"],))
        existing = {
            (r["value"] or "").strip(): r
            for r in conn.execute(
                "SELECT id, value, sort_order FROM lookup_values WHERE lookup_type = ?",
                (lookup_type,),
            ).fetchall()
        }
        for order, value in enumerate(wanted):
            if value in existing:
                if existing[value]["sort_order"] != order:
                    conn.execute(
                        "UPDATE lookup_values SET sort_order = ?, is_active = 1 WHERE id = ?",
                        (order, existing[value]["id"]),
                    )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO lookup_values (lookup_type, value, sort_order, is_active) VALUES (?, ?, ?, 1)",
                    (lookup_type, value, order),
                )


def _seed_if_empty(conn: sqlite3.Connection) -> None:
    """First-install seed only. Never wipe suppliers on an existing database.

    Sample suppliers (~50) are created only when there are no users yet
    (fresh empty DB). Later startups leave supplier rows untouched — even if
    the count is below 50 or some rows have incomplete lookup values.
    Lookup dropdown lists are refreshed separately by _sync_lookups_from_seed.
    """
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    lookup_count = conn.execute("SELECT COUNT(*) FROM lookup_values").fetchone()[0]

    if lookup_count == 0:
        _seed_lookups(conn)

    if user_count == 0:
        now = utc_now()
        conn.execute(
            "INSERT INTO users (username, password_hash, role, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
            ("admin", hash_password("ChangeMeNow!"), "admin", now),
        )
        conn.execute(
            "INSERT INTO users (username, password_hash, role, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
            ("Utilisateur1", hash_password("EssayeCa"), "standard", now),
        )
        _seed_sample_suppliers(conn)


def _clean_lookup_value(value: str) -> str:
    return " ".join(str(value).strip().split())


def _seed_lookups(conn: sqlite3.Connection) -> None:
    data = _load_seed_data()
    mapping = {
        "country": data["countries"],
        "cn_province": data["cn_provinces"],
        "item_group_name": data["item_groups"],
        "production_method": data["production_methods"],
        "nature_of_product": data["natures"],
        "meet": data["meets"],
    }
    for lookup_type, values in mapping.items():
        seen: set[str] = set()
        order = 0
        for raw in values:
            value = _clean_lookup_value(raw)
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            conn.execute(
                "INSERT OR IGNORE INTO lookup_values (lookup_type, value, sort_order, is_active) VALUES (?, ?, ?, 1)",
                (lookup_type, value, order),
            )
            order += 1


def _seed_sample_suppliers(conn: sqlite3.Connection) -> None:
    """Demo set (~50) covering Jean's lookup combinations."""
    now = utc_now()
    admin = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    admin_id = admin["id"] if admin else None
    data = _load_seed_data()
    countries = [_clean_lookup_value(v) for v in data["countries"]]
    provinces = [v for v in (_clean_lookup_value(x) for x in data["cn_provinces"]) if v != "N/A"]
    item_groups = [_clean_lookup_value(v) for v in data["item_groups"]]
    groupings = [_clean_lookup_value(v) for v in data["groupings"]]
    methods = [_clean_lookup_value(v) for v in data["production_methods"]]
    natures = [_clean_lookup_value(v) for v in data["natures"]]
    meets = [_clean_lookup_value(str(v)) for v in data["meets"]]
    statuses = list(config.STATUS_VALUES)
    interests = list(config.INTEREST_LEVEL_VALUES)

    city_by_country = {
        "China": ["Foshan", "Ningbo", "Suzhou", "Qingdao", "Dongguan", "Wenzhou", "Hefei", "Shanghai"],
        "Taiwan": ["Taipei", "Taichung", "Kaohsiung"],
        "Vietnam": ["Ho Chi Minh City", "Hanoi", "Da Nang"],
        "Thailand": ["Bangkok", "Chonburi", "Chiang Mai"],
        "Philippines": ["Manila", "Cebu", "Davao"],
        "Japan": ["Osaka", "Nagoya", "Tokyo"],
        "India": ["Pune", "Ahmedabad", "Chennai"],
        "Indonesia": ["Jakarta", "Surabaya", "Bandung"],
        "Malaysia": ["Kuala Lumpur", "Penang", "Johor Bahru"],
        "South Korea": ["Seoul", "Busan", "Incheon"],
        "Hong Kong": ["Kowloon", "Tsuen Wan", "Sha Tin"],
    }
    free_tag_pool = [
        "cordless", "heavy duty", "OEM grade", "export pack", "CE certified",
        "galvanized", "battery powered", "quick ship", "custom mold", "after sales",
        "lawn mower", "LED strip", "carbide tip", "PTO shaft", "Inner tube",
        "workshop bench", "fencing mesh", "plastic housing", "forged head", "CNC part",
    ]
    first_names = [
        "Wei", "Ming", "Anh", "Somchai", "Hao", "Fang", "Rajesh", "Budi", "Ji", "Mei",
        "Kenji", "Priya", "Lin", "Siti", "Min", "Yuki", "Arjun", "Tran", "Park", "Chen",
    ]
    last_names = [
        "Zhang", "Li", "Nguyen", "Wang", "Patel", "Kim", "Tanaka", "Santoso", "Chen", "Liu",
        "Huang", "Suzuki", "Singh", "Garcia", "Wong", "Lim", "Choi", "Yamamoto", "Das", "Ho",
    ]
    company_words = [
        "Lighting", "Garden", "Hardware", "Agri", "Tools", "Machinery", "Battery", "Auto",
        "Industrial", "Precision", "Export", "Trading", "OEM", "Parts", "Workshop", "Metal",
        "Plastic", "Forge", "Casting", "Electric", "Fence", "Wheel", "Blade", "Power", "Gift",
    ]

    samples: list[dict] = []
    for i in range(1, 51):
        country = countries[(i - 1) % len(countries)]
        nature = natures[(i - 1) % len(natures)]
        grouping = groupings[(i - 1) % len(groupings)]
        meet = meets[(i - 1) % len(meets)]
        item_group = item_groups[(i - 1) % len(item_groups)]
        method = methods[(i - 1) % len(methods)]
        status = statuses[(i - 1) % len(statuses)]
        interest = interests[(i - 1) % len(interests)]
        cities = city_by_country.get(country, ["City"])
        city = cities[(i - 1) % len(cities)]
        if country == "China":
            cn_province = provinces[(i - 1) % len(provinces)]
        else:
            cn_province = "N/A"

        # Finish product needs item group; clear production method.
        # OEM needs production method; still set item group for demo coverage.
        if nature == "Finish product":
            production_method = None
            item_group_name = item_group
        else:
            production_method = method
            item_group_name = item_group if i % 3 else None

        has_website = i % 3 != 0
        contact_mode = i % 3  # 0 email only, 1 phone only, 2 both
        email = f"sales{i:02d}@demo-supplier.example" if contact_mode != 1 else ""
        tel = f"+86 138 {1000 + i:04d} {2000 + i:04d}" if contact_mode != 0 else ""
        if country == "Vietnam" and tel:
            tel = f"+84 90 {100 + i:03d} {200 + i:03d}"
        elif country == "India" and tel:
            tel = f"+91 98 {1000 + i:04d} {i:04d}"
        elif country == "Japan" and tel:
            tel = f"+81 90 {1000 + i:04d} {i:04d}"
        elif country == "Thailand" and tel:
            tel = f"+66 81 {100 + i:03d} {200 + i:03d}"

        tag2 = free_tag_pool[(i - 1) % len(free_tag_pool)]
        tag3 = free_tag_pool[(i + 7) % len(free_tag_pool)] if i % 2 == 0 else None
        tag4 = free_tag_pool[(i + 13) % len(free_tag_pool)] if i % 5 == 0 else None

        fn = first_names[(i - 1) % len(first_names)]
        ln = last_names[(i * 3) % len(last_names)]
        cw1 = company_words[(i - 1) % len(company_words)]
        cw2 = company_words[(i * 5) % len(company_words)]
        factory = f"{city} {cw1} {cw2} Co. #{i:02d}"

        samples.append(
            {
                "status": status,
                "interest_level": interest,
                "meet": meet,
                "country": country,
                "cn_province": cn_province,
                "city": city,
                "factory_trading_name": factory,
                "website": f"https://demo-{i:02d}.example.com" if has_website else "",
                "contact_name": f"{fn} {ln}",
                "email": email,
                "tel_whatsapp_wechat": tel,
                "nature_of_product": nature,
                "item_group_name": item_group_name,
                "production_method": production_method,
                "tag_1": grouping,
                "tag_2": tag2,
                "tag_3": tag3,
                "tag_4": tag4,
                "notes": f"Demo supplier {i}/50 — {nature}, {grouping}, {country}.",
            }
        )

    cols = [
        "short_code", "status", "interest_level", "meet", "country", "cn_province", "city",
        "factory_trading_name", "website", "contact_name", "email",
        "tel_whatsapp_wechat", "nature_of_product", "item_group_name",
        "production_method", "tag_1", "tag_2", "tag_3", "tag_4", "notes",
        "created_at", "updated_at", "created_by", "updated_by",
    ]
    for i, s in enumerate(samples, start=1):
        s = dict(s)
        s["short_code"] = f"SUP-{i:04d}"
        values = [s.get(c) for c in cols[:-4]] + [now, now, admin_id, admin_id]
        placeholders = ",".join("?" * len(cols))
        conn.execute(
            f"INSERT INTO suppliers ({','.join(cols)}) VALUES ({placeholders})",
            values,
        )
        # Free tags (2–4) feed similarity; Grouping stays on the fixed list.
        for ti in range(2, 5):
            tag = s.get(f"tag_{ti}")
            if tag:
                conn.execute(
                    "INSERT OR IGNORE INTO known_tags (tag, created_at) VALUES (?, ?)",
                    (tag, now),
                )


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


def get_lookups(conn: sqlite3.Connection, lookup_type: Optional[str] = None, active_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM lookup_values"
    params: list[Any] = []
    clauses = []
    if lookup_type:
        clauses.append("lookup_type = ?")
        params.append(lookup_type)
    if active_only:
        clauses.append("is_active = 1")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY sort_order, value COLLATE NOCASE"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def lookups_by_type(conn: sqlite3.Connection) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {t: [] for t in config.LOOKUP_TYPES}
    for row in get_lookups(conn):
        t = row["lookup_type"]
        if t in result:
            result[t].append(row["value"])
    return result


def get_user_columns(conn: sqlite3.Connection, user_id: int) -> list[str]:
    row = conn.execute(
        "SELECT columns_json FROM user_column_prefs WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return list(config.DEFAULT_VISIBLE_COLUMNS)
    try:
        cols = json.loads(row["columns_json"])
        allowed = {c[0] for c in config.ALL_COLUMNS}
        filtered = [c for c in cols if c in allowed]
        return filtered or list(config.DEFAULT_VISIBLE_COLUMNS)
    except Exception:
        return list(config.DEFAULT_VISIBLE_COLUMNS)


def set_user_columns(conn: sqlite3.Connection, user_id: int, columns: list[str]) -> None:
    allowed = {c[0] for c in config.ALL_COLUMNS}
    filtered = [c for c in columns if c in allowed]
    if not filtered:
        filtered = list(config.DEFAULT_VISIBLE_COLUMNS)
    payload = json.dumps(filtered)
    conn.execute(
        """
        INSERT INTO user_column_prefs (user_id, columns_json) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET columns_json = excluded.columns_json
        """,
        (user_id, payload),
    )


def supplier_tags_display(supplier: dict) -> str:
    tags = [supplier.get(f"tag_{i}") for i in range(1, 5)]
    return ", ".join(t for t in tags if t)


def wildcard_to_like(pattern: str) -> str:
    """Convert user wildcard (* and ?) to SQL LIKE with ESCAPE."""
    raw = (pattern or "").strip()
    if not raw:
        return ""
    escaped = raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    if "*" in escaped or "?" in escaped:
        like = escaped.replace("*", "%").replace("?", "_")
    else:
        like = f"%{escaped}%"
    return like


def build_search_where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    text_fields = [
        "factory_trading_name", "contact_name", "email", "city",
        "website", "tel_whatsapp_wechat", "notes",
    ]
    for field in text_fields:
        val = (filters.get(field) or "").strip()
        if val:
            like = wildcard_to_like(val)
            clauses.append(f"{field} LIKE ? ESCAPE '\\'")
            params.append(like)

    exact_fields = [
        "status", "interest_level", "meet", "country", "cn_province",
        "nature_of_product", "item_group_name", "production_method",
    ]
    for field in exact_fields:
        val = (filters.get(field) or "").strip()
        if val:
            clauses.append(f"LOWER({field}) = LOWER(?)")
            params.append(val)

    grouping = (filters.get("grouping") or "").strip()
    if grouping:
        clauses.append("LOWER(tag_1) = LOWER(?)")
        params.append(grouping)

    tag = (filters.get("tag") or "").strip()
    if tag:
        like = wildcard_to_like(tag)
        clauses.append(
            "(tag_1 LIKE ? ESCAPE '\\' OR tag_2 LIKE ? ESCAPE '\\' "
            "OR tag_3 LIKE ? ESCAPE '\\' OR tag_4 LIKE ? ESCAPE '\\')"
        )
        params.extend([like, like, like, like])

    q = (filters.get("q") or "").strip()
    if q:
        like = wildcard_to_like(q)
        clauses.append(
            "("
            "factory_trading_name LIKE ? ESCAPE '\\' OR "
            "contact_name LIKE ? ESCAPE '\\' OR "
            "email LIKE ? ESCAPE '\\' OR "
            "country LIKE ? ESCAPE '\\' OR "
            "city LIKE ? ESCAPE '\\' OR "
            "nature_of_product LIKE ? ESCAPE '\\' OR "
            "item_group_name LIKE ? ESCAPE '\\' OR "
            "notes LIKE ? ESCAPE '\\' OR "
            "tag_1 LIKE ? ESCAPE '\\' OR tag_2 LIKE ? ESCAPE '\\' OR "
            "tag_3 LIKE ? ESCAPE '\\' OR tag_4 LIKE ? ESCAPE '\\'"
            ")"
        )
        params.extend([like] * 12)

    if not clauses:
        return "1=1", []
    return " AND ".join(clauses), params


def validate_supplier_payload(data: dict[str, Any], lookups: dict[str, list[str]]) -> list[str]:
    errors: list[str] = []
    name = (data.get("factory_trading_name") or "").strip()
    if not name:
        errors.append("Factory / Trading Name is required.")

    country = (data.get("country") or "").strip()
    if not country:
        errors.append("Country is required.")
    elif country not in lookups.get("country", []):
        errors.append("Country must be chosen from the list.")

    email = (data.get("email") or "").strip()
    tel = (data.get("tel_whatsapp_wechat") or "").strip()
    if not email and not tel:
        errors.append("Enter an email or a Tel / WhatsApp / WeChat number (at least one is required).")

    nature = (data.get("nature_of_product") or "").strip()
    if not nature:
        errors.append("Nature of Product is required.")
    elif nature not in lookups.get("nature_of_product", []):
        errors.append("Nature of Product must be chosen from the list.")

    method = (data.get("production_method") or "").strip()
    item_group = (data.get("item_group_name") or "").strip()
    cn_province = (data.get("cn_province") or "").strip()

    # Exact seed values: "OEM" and "Finish product"
    if nature == "OEM":
        if not method:
            errors.append("Production Method is required when Nature of Product is OEM.")
        elif method not in lookups.get("production_method", []):
            errors.append("Production Method must be chosen from the list.")
    elif method and method not in lookups.get("production_method", []):
        errors.append("Production Method must be chosen from the list.")

    if nature == "Finish product":
        if not item_group:
            errors.append("Item Group is required when Nature of Product is Finish product.")
        elif item_group not in lookups.get("item_group_name", []):
            errors.append("Item Group must be chosen from the list.")

    if country == "China":
        if not cn_province:
            errors.append("CN Province is required when Country is China.")
        elif cn_province not in lookups.get("cn_province", []):
            errors.append("CN Province must be chosen from the list.")
    else:
        if cn_province and cn_province != "N/A":
            errors.append("CN Province must be N/A when Country is not China.")

    notes = data.get("notes") or ""
    if len(notes) > config.NOTES_MAX_LEN:
        errors.append(f"Notes must be at most {config.NOTES_MAX_LEN} characters.")

    status = (data.get("status") or "Current").strip()
    if status not in ("Current", "Prospect", "Inactive"):
        errors.append("Status must be Current, Prospect, or Inactive.")

    interest = (data.get("interest_level") or "").strip()
    if interest and interest not in config.INTEREST_LEVEL_VALUES:
        errors.append("Interest level must be Must visit, Interesting, or In Case.")

    grouping = (data.get("tag_1") or "").strip()
    # Grouping compulsory only for Finish product; optional for OEM
    if nature == "Finish product":
        if not grouping:
            errors.append("Grouping is required when Nature of Product is Finish product.")
        elif grouping not in get_grouping_options():
            errors.append("Grouping must be chosen from the list.")
    elif grouping and grouping not in get_grouping_options():
        errors.append("Grouping must be chosen from the list.")

    free_tags = [
        (data.get("tag_2") or "").strip(),
        (data.get("tag_3") or "").strip(),
        (data.get("tag_4") or "").strip(),
    ]
    if not any(free_tags):
        errors.append("Enter at least one Tag (Tag 2, 3, or 4).")

    for field, key in [("meet", "meet"), ("item_group_name", "item_group_name")]:
        val = (data.get(field) or "").strip()
        if val and val not in lookups.get(key, []):
            errors.append(f"{field.replace('_', ' ').title()} must be chosen from the list.")

    return errors


def normalize_supplier_payload(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    country = (out.get("country") or "").strip() or config.DEFAULT_COUNTRY
    nature = (out.get("nature_of_product") or "").strip()
    out["country"] = country
    status = (out.get("status") or "Current").strip()
    if status not in ("Current", "Prospect", "Inactive"):
        status = "Current"
    out["status"] = status
    interest = (out.get("interest_level") or "").strip()
    if interest not in config.INTEREST_LEVEL_VALUES:
        interest = ""
    out["interest_level"] = interest or None
    sc = (out.get("short_code") or "").strip().upper()
    out["short_code"] = sc or None

    if nature == "Finish product":
        out["production_method"] = None
    if country != "China":
        out["cn_province"] = "N/A"

    notes = (out.get("notes") or "").strip()
    if len(notes) > config.NOTES_MAX_LEN:
        notes = notes[: config.NOTES_MAX_LEN]
    out["notes"] = notes or None

    for key in (
        "meet", "cn_province", "city", "website", "contact_name", "email",
        "tel_whatsapp_wechat", "nature_of_product", "item_group_name",
        "production_method", "tag_1", "tag_2", "tag_3", "tag_4",
        "factory_trading_name",
    ):
        val = out.get(key)
        if isinstance(val, str):
            val = val.strip()
            out[key] = val or None
    out["factory_trading_name"] = (out.get("factory_trading_name") or "").strip()
    return out


def next_short_code(conn) -> str:
    max_n = 0
    for r in conn.execute("SELECT short_code FROM suppliers WHERE short_code IS NOT NULL").fetchall():
        code = (r["short_code"] or "").upper()
        if code.startswith("SUP-"):
            try:
                max_n = max(max_n, int(code.split("-", 1)[1]))
            except ValueError:
                pass
    return f"SUP-{max_n + 1:04d}"


def find_duplicate_suppliers(
    conn, factory_name: str, country: str, email: str, exclude_id: int | None = None
) -> list[dict]:
    factory_name = (factory_name or "").strip()
    country = (country or "").strip()
    email = (email or "").strip()
    found: dict[int, dict] = {}
    if factory_name and country:
        sql = """
            SELECT id_supplier, short_code, factory_trading_name, country, email, status
            FROM suppliers
            WHERE LOWER(factory_trading_name) = LOWER(?) AND LOWER(country) = LOWER(?)
        """
        params: list = [factory_name, country]
        if exclude_id:
            sql += " AND id_supplier != ?"
            params.append(exclude_id)
        for r in conn.execute(sql, params).fetchall():
            found[r["id_supplier"]] = dict(r)
            found[r["id_supplier"]]["match_reason"] = "factory+country"
    if email:
        sql = """
            SELECT id_supplier, short_code, factory_trading_name, country, email, status
            FROM suppliers
            WHERE email IS NOT NULL AND email != '' AND LOWER(email) = LOWER(?)
        """
        params = [email]
        if exclude_id:
            sql += " AND id_supplier != ?"
            params.append(exclude_id)
        for r in conn.execute(sql, params).fetchall():
            d = found.get(r["id_supplier"], dict(r))
            if "match_reason" in d and d["match_reason"] != "email":
                d["match_reason"] = "factory+country and email"
            else:
                d["match_reason"] = "email"
            found[r["id_supplier"]] = d
    return list(found.values())


def register_tags(conn, tags: list[str | None]) -> None:
    now = utc_now()
    for tag in tags:
        if tag and str(tag).strip():
            conn.execute(
                "INSERT OR IGNORE INTO known_tags (tag, created_at) VALUES (?, ?)",
                (str(tag).strip(), now),
            )


def merge_known_tags(conn, source_tag: str, target_tag: str) -> int:
    source_tag = source_tag.strip()
    target_tag = target_tag.strip()
    if not source_tag or not target_tag or source_tag.lower() == target_tag.lower():
        return 0
    updated = 0
    for col in ("tag_1", "tag_2", "tag_3", "tag_4"):
        cur = conn.execute(
            f"UPDATE suppliers SET {col} = ? WHERE {col} = ? COLLATE NOCASE",
            (target_tag, source_tag),
        )
        updated += cur.rowcount
    conn.execute("DELETE FROM known_tags WHERE tag = ? COLLATE NOCASE", (source_tag,))
    conn.execute(
        "INSERT OR IGNORE INTO known_tags (tag, created_at) VALUES (?, ?)",
        (target_tag, utc_now()),
    )
    return updated


def normalize_tag_key(tag: str) -> str:
    """Lowercase and strip spaces/punctuation for tag comparison."""
    import re

    return re.sub(r"[^a-z0-9]", "", (tag or "").lower())


def list_live_free_tag_labels(conn) -> list[str]:
    """Distinct Tag 2–4 values currently present on at least one supplier.

    Used for create/edit autocomplete and similarity. Does NOT include
    orphan known_tags or Grouping (tag_1). Admin merge still uses known_tags.
    """
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
        WHERE tag IS NOT NULL AND TRIM(tag) != ''
        ORDER BY tag COLLATE NOCASE
        """
    ).fetchall()
    return [r["tag"] for r in rows]


def list_all_known_tag_labels(conn) -> list[str]:
    """Backward-compatible alias: live free tags only (not known_tags orphans)."""
    return list_live_free_tag_labels(conn)


def prune_unused_known_tags(conn) -> int:
    """Remove known_tags entries that are not currently on any supplier Tag 2–4."""
    cur = conn.execute(
        """
        DELETE FROM known_tags
        WHERE NOT EXISTS (
            SELECT 1 FROM suppliers s
            WHERE (s.tag_2 IS NOT NULL AND TRIM(s.tag_2) != '' AND s.tag_2 = known_tags.tag COLLATE NOCASE)
               OR (s.tag_3 IS NOT NULL AND TRIM(s.tag_3) != '' AND s.tag_3 = known_tags.tag COLLATE NOCASE)
               OR (s.tag_4 IS NOT NULL AND TRIM(s.tag_4) != '' AND s.tag_4 = known_tags.tag COLLATE NOCASE)
        )
        """
    )
    return cur.rowcount


def find_similar_tag_labels(conn, typed: str) -> list[str]:
    """
    Return existing tags similar to `typed` but not an exact case-insensitive match.
    Similarity: same normalize_tag_key, or high fuzzy ratio (difflib).
    """
    from difflib import SequenceMatcher

    typed = (typed or "").strip()
    if not typed:
        return []
    typed_key = normalize_tag_key(typed)
    typed_lower = typed.lower()
    if not typed_key:
        return []

    candidates: list[str] = []
    for label in list_live_free_tag_labels(conn):
        if label.lower() == typed_lower:
            continue  # exact (case-insensitive) — not a "similar" conflict
        other_key = normalize_tag_key(label)
        if typed_key and other_key and typed_key == other_key:
            candidates.append(label)
            continue
        # Fuzzy: lawnmower vs lawn-mower already caught; catch near typos
        ratio = SequenceMatcher(None, typed_key, other_key).ratio()
        if ratio >= 0.86 and abs(len(typed_key) - len(other_key)) <= 3:
            candidates.append(label)
    return candidates


def resolve_tag_similarities(
    conn, payload: dict, resolve_map: dict[str, str]
) -> tuple[dict, list[dict]]:
    """
    Check tag_1..tag_4 for similar existing tags.
    resolve_map: field -> 'keep' | 'use:<existing label>'
    Returns (updated_payload, unresolved_issues).
    Each issue: {field, typed, candidates: [str, ...]}
    """
    out = dict(payload)
    issues: list[dict] = []
    for i in range(1, 5):
        field = f"tag_{i}"
        typed = (out.get(field) or "").strip()
        if not typed:
            out[field] = None
            continue
        # Grouping (tag_1) is a controlled dropdown — no fuzzy unify prompt
        if i == 1:
            out[field] = typed
            continue
        decision = (resolve_map.get(field) or "").strip()
        if decision.startswith("use:"):
            chosen = decision[4:].strip()
            if chosen:
                out[field] = chosen
                continue
        if decision == "keep":
            out[field] = typed
            continue
        similar = find_similar_tag_labels(conn, typed)
        if similar:
            issues.append({"field": field, "typed": typed, "candidates": similar})
        else:
            out[field] = typed
    return out, issues
