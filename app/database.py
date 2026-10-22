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
        _sync_asia_countries(conn)




def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Additive SQLite migrations for existing databases."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(suppliers)").fetchall()}
    if "interest_level" not in cols:
        conn.execute("ALTER TABLE suppliers ADD COLUMN interest_level TEXT")


def _sync_asia_countries(conn: sqlite3.Connection) -> None:
    """Keep country lookup list aligned with Asia-only seed_lookups.json."""
    path = config.SEED_LOOKUPS_PATH
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    allowed = {_clean_lookup_value(v) for v in data.get("countries", []) if str(v).strip()}
    if not allowed:
        return
    rows = conn.execute(
        "SELECT id, value FROM lookup_values WHERE lookup_type = 'country'"
    ).fetchall()
    for row in rows:
        if (row["value"] or "").strip() not in allowed:
            conn.execute("DELETE FROM lookup_values WHERE id = ?", (row["id"],))
    existing = {
        (r["value"] or "").strip()
        for r in conn.execute(
            "SELECT value FROM lookup_values WHERE lookup_type = 'country'"
        ).fetchall()
    }
    order = 0
    for raw in data.get("countries", []):
        value = _clean_lookup_value(raw)
        if not value:
            continue
        if value not in existing:
            conn.execute(
                "INSERT OR IGNORE INTO lookup_values (lookup_type, value, sort_order, is_active) VALUES (?, ?, ?, 1)",
                ("country", value, order),
            )
        order += 1


def _seed_if_empty(conn: sqlite3.Connection) -> None:
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    lookup_count = conn.execute("SELECT COUNT(*) FROM lookup_values").fetchone()[0]
    supplier_count = conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]
    demo_target = 28

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
    else:
        asia = set()
        path = config.SEED_LOOKUPS_PATH
        with open(path, encoding="utf-8") as f:
            asia = {_clean_lookup_value(v) for v in json.load(f).get("countries", []) if str(v).strip()}
        bad = conn.execute(
            "SELECT COUNT(*) FROM suppliers WHERE country IS NOT NULL AND TRIM(country) != '' AND country NOT IN (%s)"
            % (",".join("?" * len(asia)) if asia else "NULL"),
            tuple(asia) if asia else (),
        ).fetchone()[0] if asia else 0
        interest_filled = conn.execute(
            "SELECT COUNT(*) FROM suppliers WHERE interest_level IS NOT NULL AND TRIM(interest_level) != ''"
        ).fetchone()[0]
        missing_interest = supplier_count > 0 and interest_filled == 0
        if supplier_count < demo_target or bad or missing_interest:
            # Demo refresh: replace suppliers when seed grew, non-Asia rows remain, or interest unset.
            conn.execute("DELETE FROM attachments")
            conn.execute("DELETE FROM suppliers")
            conn.execute("DELETE FROM known_tags")
            _seed_sample_suppliers(conn)


def _clean_lookup_value(value: str) -> str:
    return " ".join(str(value).strip().split())


def _seed_lookups(conn: sqlite3.Connection) -> None:
    path = config.SEED_LOOKUPS_PATH
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    mapping = {
        "country": data["countries"],
        "cn_province": data["cn_provinces"],
        "item_group_name": data["item_groups"],
        "production_method": data["production_methods"],
        "nature_of_product": data["natures"],
        "meet": data["meets"],
    }
    if "N/A" not in mapping["production_method"]:
        mapping["production_method"].append("N/A")

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
    now = utc_now()
    admin = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    admin_id = admin["id"] if admin else None
    samples = [
        {
            "status": "Current",
            "meet": "Canton Fair Oct 2026",
            "country": "China",
            "cn_province": "GUANGDONG PROVINCE",
            "city": "Foshan",
            "factory_trading_name": "Guangdong LED Lighting Co.",
            "website": "https://example-led.cn",
            "contact_name": "Zhang Wei",
            "email": "sales@example-led.cn",
            "tel_whatsapp_wechat": "+86 138 0000 1111",
            "nature_of_product": "OEM",
            "item_group_name": "LIGHTING",
            "production_method": "Injection plastique",
            "tag_1": "LED trailer",
            "tag_2": "UFO LED",
            "tag_3": "galvanized barrier",
            "tag_4": "LED*",
            "notes": "Met at Canton Fair — strong OEM capacity.",
        },
        {
            "status": "Current",
            "meet": "Alibaba",
            "country": "China",
            "cn_province": "ZHEJIANG PROVINCE",
            "city": "Ningbo",
            "factory_trading_name": "Ningbo Garden Tools Trading",
            "website": "https://example-garden.cn",
            "contact_name": "Li Ming",
            "email": "li@example-garden.cn",
            "tel_whatsapp_wechat": "+86 139 2222 3333",
            "nature_of_product": "Finish product",
            "item_group_name": "GARDENING MACHINES",
            "production_method": "N/A",
            "tag_1": "lawn mower",
            "tag_2": "battery powered",
            "tag_3": None,
            "tag_4": None,
            "notes": "Finish product catalog — good packaging.",
        },
        {
            "status": "Prospect",
            "meet": "Made in China",
            "country": "Vietnam",
            "cn_province": "N/A",
            "city": "Ho Chi Minh City",
            "factory_trading_name": "Saigon Hardware Export",
            "website": "",
            "contact_name": "Nguyen Anh",
            "email": "anh@saigon-hw.vn",
            "tel_whatsapp_wechat": "+84 90 555 6666",
            "nature_of_product": "OEM",
            "item_group_name": "HARDWARE",
            "production_method": "Forging",
            "tag_1": "welding",
            "tag_2": "hand tools",
            "tag_3": None,
            "tag_4": None,
            "notes": "Prospect — non-China OEM forging.",
        },
        {
            "status": "Current",
            "meet": "1688",
            "country": "China",
            "cn_province": "JIANGSU PROVINCE",
            "city": "Suzhou",
            "factory_trading_name": "Suzhou Industrial Components Ltd",
            "website": "https://example-sic.cn",
            "contact_name": "Chen Hao",
            "email": "chen@example-sic.cn",
            "tel_whatsapp_wechat": "WeChat: chenhao_sic",
            "nature_of_product": "OEM",
            "item_group_name": "INDUSTRIAL COMPONENT",
            "production_method": "Machining",
            "tag_1": "CNC",
            "tag_2": "LED housing",
            "tag_3": "precision parts",
            "tag_4": "ISO9001",
            "notes": "CNC specialist, flexible MOQ.",
        },
        {
            "status": "Current",
            "meet": "Canton Fair April 2027",
            "country": "Thailand",
            "cn_province": "N/A",
            "city": "Bangkok",
            "factory_trading_name": "Bangkok Power Tools Co.",
            "website": "https://example-bpt.th",
            "contact_name": "Somchai P.",
            "email": "sales@example-bpt.th",
            "tel_whatsapp_wechat": "+66 81 777 8888",
            "nature_of_product": "Finish product",
            "item_group_name": "POWER TOOLS",
            "production_method": "N/A",
            "tag_1": "cordless drill",
            "tag_2": None,
            "tag_3": None,
            "tag_4": None,
            "notes": "SE Asia finish-product option.",
        },
        {
            "status": "Prospect",
            "meet": "Alibaba",
            "country": "China",
            "cn_province": "SHANDONG PROVINCE",
            "city": "Qingdao",
            "factory_trading_name": "Qingdao Agri Parts Works",
            "website": "",
            "contact_name": "Wang Fang",
            "email": "fang@qd-agri.cn",
            "tel_whatsapp_wechat": "",
            "nature_of_product": "OEM",
            "item_group_name": "AGRI PARTS",
            "production_method": "Casting",
            "tag_1": "casting",
            "tag_2": "tractor parts",
            "tag_3": None,
            "tag_4": None,
            "notes": "Email only — casting samples pending.",
        },
        {
            "status": "Prospect",
            "meet": "Canton Fair Oct 2027",
            "country": "China",
            "cn_province": "FUJIAN PROVINCE",
            "city": "Xiamen",
            "factory_trading_name": "Xiamen Battery Solutions",
            "website": "https://xm-battery.cn",
            "contact_name": "Huang Jie",
            "email": "",
            "tel_whatsapp_wechat": "+86 159 8888 1010",
            "nature_of_product": "Finish product",
            "item_group_name": "BATTERIES",
            "production_method": "N/A",
            "tag_1": "battery",
            "tag_2": "Li-ion",
            "tag_3": None,
            "tag_4": None,
            "notes": "Phone only contact.",
        },
        {
            "status": "Inactive",
            "meet": "1688",
            "country": "China",
            "cn_province": "HEBEI PROVINCE",
            "city": "Cangzhou",
            "factory_trading_name": "Cangzhou Steel Hardware Old Co",
            "website": "",
            "contact_name": "Zhao Lei",
            "email": "zhao@cz-steel.cn",
            "tel_whatsapp_wechat": "+86 137 4444 5555",
            "nature_of_product": "OEM",
            "item_group_name": "HARDWARE",
            "production_method": "Forging",
            "tag_1": "forging",
            "tag_2": None,
            "tag_3": None,
            "tag_4": None,
            "notes": "Inactive — quality issues 2025.",
        },
        {
            "status": "Current",
            "meet": "Canton Fair Oct 2026",
            "country": "China",
            "cn_province": "SHANGHAI MUNICIPALITY",
            "city": "Shanghai",
            "factory_trading_name": "Shanghai Precision Machining",
            "website": "https://sh-pm.cn",
            "contact_name": "Sun Yi",
            "email": "yi@sh-pm.cn",
            "tel_whatsapp_wechat": "+86 21 6000 7788",
            "nature_of_product": "OEM",
            "item_group_name": "OEM INDUSTRIAL PARTS",
            "production_method": "Machining",
            "tag_1": "CNC",
            "tag_2": "tolerance",
            "tag_3": "aluminum",
            "tag_4": None,
            "notes": "Tight tolerances, fast samples.",
        },
        {
            "status": "Prospect",
            "meet": "Made in China",
            "country": "India",
            "cn_province": "N/A",
            "city": "Pune",
            "factory_trading_name": "Pune Power Machinery Traders",
            "website": "",
            "contact_name": "Rajesh K.",
            "email": "rajesh@pune-pm.in",
            "tel_whatsapp_wechat": "+91 98 2000 3344",
            "nature_of_product": "Finish product",
            "item_group_name": "POWER MACHINERY",
            "production_method": "N/A",
            "tag_1": "generator",
            "tag_2": None,
            "tag_3": None,
            "tag_4": None,
            "notes": "",
        },
        {
            "status": "Current",
            "meet": "Alibaba",
            "country": "China",
            "cn_province": "BEIJING MUNICIPALITY",
            "city": "Beijing",
            "factory_trading_name": "Beijing Road Safety Gear",
            "website": "https://bj-road.cn",
            "contact_name": "Liu Na",
            "email": "na@bj-road.cn",
            "tel_whatsapp_wechat": "+86 10 8888 2222",
            "nature_of_product": "Finish product",
            "item_group_name": "ROAD SAFETY ITEMS",
            "production_method": "N/A",
            "tag_1": "traffic cone",
            "tag_2": "LED*",
            "tag_3": "reflective",
            "tag_4": None,
            "notes": "Finish catalog for EU markets.",
        },
        {
            "status": "Current",
            "meet": "Canton Fair April 2028",
            "country": "Japan",
            "cn_province": "N/A",
            "city": "Stuttgart",
            "factory_trading_name": "Stuttgart Werkzeug Handel",
            "website": "https://stuttgart-wt.de",
            "contact_name": "Hans M.",
            "email": "hans@stuttgart-wt.de",
            "tel_whatsapp_wechat": "+49 711 555 010",
            "nature_of_product": "Finish product",
            "item_group_name": "HAND TOOLS",
            "production_method": "N/A",
            "tag_1": None,
            "tag_2": None,
            "tag_3": None,
            "tag_4": None,
            "notes": "EU distribution partner.",
        },
        {
            "status": "Prospect",
            "meet": "1688",
            "country": "China",
            "cn_province": "ANHUI PROVINCE",
            "city": "Hefei",
            "factory_trading_name": "Hefei Lawncare OEM Factory",
            "website": "",
            "contact_name": "Xu Peng",
            "email": "peng@hf-lawn.cn",
            "tel_whatsapp_wechat": "+86 551 6666 1212",
            "nature_of_product": "OEM",
            "item_group_name": "GARDENING MACHINES",
            "production_method": "Injection plastique",
            "tag_1": "Lawnmower",
            "tag_2": "battery",
            "tag_3": None,
            "tag_4": None,
            "notes": "Fuzzy tag twin of lawn mower.",
        },
        {
            "status": "Inactive",
            "meet": "Canton Fair Oct 2028",
            "country": "China",
            "cn_province": "HUBEI PROVINCE",
            "city": "Wuhan",
            "factory_trading_name": "Wuhan Plastic Housewares",
            "website": "https://wh-plastic.cn",
            "contact_name": "Gao Rui",
            "email": "rui@wh-plastic.cn",
            "tel_whatsapp_wechat": "",
            "nature_of_product": "OEM",
            "item_group_name": "HOUSEHOLD APPLIANCES",
            "production_method": "Injection plastique",
            "tag_1": "plastic housing",
            "tag_2": None,
            "tag_3": None,
            "tag_4": None,
            "notes": "Inactive after ownership change.",
        },
        {
            "status": "Current",
            "meet": "Made in China",
            "country": "Turkey",
            "cn_province": "N/A",
            "city": "Istanbul",
            "factory_trading_name": "Istanbul Hardware Metals AS",
            "website": "https://ist-hw.tr",
            "contact_name": "Mehmet Y.",
            "email": "mehmet@ist-hw.tr",
            "tel_whatsapp_wechat": "+90 212 444 7788",
            "nature_of_product": "OEM",
            "item_group_name": "HARDWARE",
            "production_method": "Forging",
            "tag_1": "welding",
            "tag_2": "bolts",
            "tag_3": None,
            "tag_4": None,
            "notes": "Near-EU forging option.",
        },
        {
            "status": "Current",
            "meet": "Alibaba",
            "country": "China",
            "cn_province": "GUANGDONG PROVINCE",
            "city": "Dongguan",
            "factory_trading_name": "Dongguan LED Strip Works",
            "website": "https://dg-ledstrip.cn",
            "contact_name": "Tang Bo",
            "email": "bo@dg-ledstrip.cn",
            "tel_whatsapp_wechat": "WeChat: tangbo_led",
            "nature_of_product": "OEM",
            "item_group_name": "LIGHTING",
            "production_method": "Injection plastique",
            "tag_1": "LED*",
            "tag_2": "flexible strip",
            "tag_3": "waterproof",
            "tag_4": "RGB",
            "notes": "All four tags filled.",
        },
        {
            "status": "Prospect",
            "meet": "Canton Fair April 2029",
            "country": "Taiwan, P.R.China",
            "cn_province": "N/A",
            "city": "Taichung",
            "factory_trading_name": "Milano Componenti Industriali",
            "website": "",
            "contact_name": "Marco R.",
            "email": "marco@milano-ci.it",
            "tel_whatsapp_wechat": "",
            "nature_of_product": "OEM",
            "item_group_name": "INDUSTRIAL COMPONENT",
            "production_method": "Machining",
            "tag_1": "CNC",
            "tag_2": None,
            "tag_3": None,
            "tag_4": None,
            "notes": "Email only — EU machining.",
        },
        {
            "status": "Current",
            "meet": "1688",
            "country": "China",
            "cn_province": "ZHEJIANG PROVINCE",
            "city": "Yiwu",
            "factory_trading_name": "Yiwu Corporate Gifts Hub",
            "website": "https://yw-gifts.cn",
            "contact_name": "Jin Hua",
            "email": "hua@yw-gifts.cn",
            "tel_whatsapp_wechat": "+86 579 8888 3344",
            "nature_of_product": "Finish product",
            "item_group_name": "CORPORATE GIFTS",
            "production_method": "N/A",
            "tag_1": None,
            "tag_2": None,
            "tag_3": None,
            "tag_4": None,
            "notes": "",
        },
        {
            "status": "Current",
            "meet": "Canton Fair Oct 2029",
            "country": "South Korea",
            "cn_province": "N/A",
            "city": "Busan",
            "factory_trading_name": "Busan Electric Components",
            "website": "https://busan-ec.kr",
            "contact_name": "Park Ji",
            "email": "ji@busan-ec.kr",
            "tel_whatsapp_wechat": "+82 51 700 2211",
            "nature_of_product": "OEM",
            "item_group_name": "ELECTRIC/TRONIC COMP",
            "production_method": "Machining",
            "tag_1": "PCB",
            "tag_2": "connectors",
            "tag_3": None,
            "tag_4": None,
            "notes": "Korea OEM electronics.",
        },
        {
            "status": "Prospect",
            "meet": "Made in China",
            "country": "Malaysia",
            "cn_province": "N/A",
            "city": "Penang",
            "factory_trading_name": "Penang Workshop Equip Sdn Bhd",
            "website": "",
            "contact_name": "Aisha R.",
            "email": "",
            "tel_whatsapp_wechat": "+60 12 345 6789",
            "nature_of_product": "Finish product",
            "item_group_name": "WORKSHOP EQUIPMENT",
            "production_method": "N/A",
            "tag_1": "bench vise",
            "tag_2": None,
            "tag_3": None,
            "tag_4": None,
            "notes": "Phone only — prospect SE Asia.",
        },
        {
            "status": "Current",
            "meet": "Alibaba",
            "country": "China",
            "cn_province": "GUANGDONG PROVINCE",
            "city": "Zhongshan",
            "factory_trading_name": "Zhongshan Sanitary Bath OEM",
            "website": "https://zs-bath.cn",
            "contact_name": "Liang Xin",
            "email": "xin@zs-bath.cn",
            "tel_whatsapp_wechat": "+86 760 2222 9090",
            "nature_of_product": "OEM",
            "item_group_name": "SANITARY BATH EQUIP",
            "production_method": "Casting",
            "tag_1": "faucet",
            "tag_2": "casting",
            "tag_3": None,
            "tag_4": None,
            "notes": "Casting + finishing lines.",
        },
        {
            "status": "Current",
            "meet": "Canton Fair April 2030",
            "country": "Indonesia",
            "cn_province": "N/A",
            "city": "Jakarta",
            "factory_trading_name": "Jakarta Tyre & Wheel Supply",
            "website": "https://jkt-tyre.id",
            "contact_name": "Budi S.",
            "email": "budi@jkt-tyre.id",
            "tel_whatsapp_wechat": "+62 812 3333 4444",
            "nature_of_product": "Finish product",
            "item_group_name": "TYRE/TUBES/WHEELS",
            "production_method": "N/A",
            "tag_1": "wheel",
            "tag_2": "tube",
            "tag_3": None,
            "tag_4": None,
            "notes": "Stock finish products.",
        },
        {
            "status": "Prospect",
            "meet": "1688",
            "country": "China",
            "cn_province": "JIANGSU PROVINCE",
            "city": "Wuxi",
            "factory_trading_name": "Wuxi New Energy Packs",
            "website": "",
            "contact_name": "Zhou Min",
            "email": "min@wx-nep.cn",
            "tel_whatsapp_wechat": "+86 510 7777 1616",
            "nature_of_product": "OEM",
            "item_group_name": "NEW ENERGY RESOURCES",
            "production_method": "Machining",
            "tag_1": "battery",
            "tag_2": "solar mount",
            "tag_3": "CNC",
            "tag_4": None,
            "notes": "Prospect for solar mounts.",
        },
        {
            "status": "Current",
            "meet": "Canton Fair Oct 2030",
            "country": "Singapore",
            "cn_province": "N/A",
            "city": "Poznan",
            "factory_trading_name": "Poznan Packaging Solutions",
            "website": "https://poznan-pack.pl",
            "contact_name": "Anna K.",
            "email": "anna@poznan-pack.pl",
            "tel_whatsapp_wechat": "+48 61 222 3344",
            "nature_of_product": "Finish product",
            "item_group_name": "PACKING/PACKAGING",
            "production_method": "N/A",
            "tag_1": "carton",
            "tag_2": None,
            "tag_3": None,
            "tag_4": None,
            "notes": "EU packaging partner.",
        },
        {
            "status": "Current",
            "meet": "Made in China",
            "country": "China",
            "cn_province": "SHANDONG PROVINCE",
            "city": "Weifang",
            "factory_trading_name": "Weifang Agri Machines Co",
            "website": "https://wf-agri.cn",
            "contact_name": "Ma Jun",
            "email": "jun@wf-agri.cn",
            "tel_whatsapp_wechat": "+86 536 1111 2222",
            "nature_of_product": "Finish product",
            "item_group_name": "AGRI MACHINES",
            "production_method": "N/A",
            "tag_1": "harvester",
            "tag_2": "spare parts",
            "tag_3": None,
            "tag_4": None,
            "notes": "Finish machines + aftersales.",
        },
        {
            "status": "Inactive",
            "meet": "Alibaba",
            "country": "Vietnam",
            "cn_province": "N/A",
            "city": "Hanoi",
            "factory_trading_name": "Hanoi Pet Products Export",
            "website": "",
            "contact_name": "Tran Hoa",
            "email": "hoa@hn-pet.vn",
            "tel_whatsapp_wechat": "+84 24 5555 6666",
            "nature_of_product": "Finish product",
            "item_group_name": "PET PRODUCTS",
            "production_method": "N/A",
            "tag_1": None,
            "tag_2": None,
            "tag_3": None,
            "tag_4": None,
            "notes": "Inactive — stopped exporting.",
        },
        {
            "status": "Current",
            "meet": "Canton Fair Oct 2026",
            "country": "China",
            "cn_province": "FUJIAN PROVINCE",
            "city": "Quanzhou",
            "factory_trading_name": "Quanzhou Fishing Gear Factory",
            "website": "https://qz-fish.cn",
            "contact_name": "Cai Rong",
            "email": "rong@qz-fish.cn",
            "tel_whatsapp_wechat": "+86 595 3333 7788",
            "nature_of_product": "OEM",
            "item_group_name": "FISHING ITEMS",
            "production_method": "Injection plastique",
            "tag_1": "reel",
            "tag_2": "plastic mold",
            "tag_3": None,
            "tag_4": None,
            "notes": "OEM plastic fishing parts.",
        },
        {
            "status": "Prospect",
            "meet": "1688",
            "country": "China",
            "cn_province": "GUANGDONG PROVINCE",
            "city": "Shenzhen",
            "factory_trading_name": "Shenzhen Vehicle Access Trade",
            "website": "",
            "contact_name": "He Lin",
            "email": "lin@sz-va.cn",
            "tel_whatsapp_wechat": "+86 755 8888 9999",
            "nature_of_product": "Finish product",
            "item_group_name": "VEHICULE ACCESSORIES",
            "production_method": "N/A",
            "tag_1": "LED*",
            "tag_2": "car light",
            "tag_3": "12V",
            "tag_4": None,
            "notes": "Prospect auto accessories.",
        },
        {
            "status": "Current",
            "meet": "Canton Fair April 2027",
            "country": "Thailand",
            "cn_province": "N/A",
            "city": "Chonburi",
            "factory_trading_name": "Chonburi Casting Parts Co",
            "website": "https://chon-cast.th",
            "contact_name": "Niran T.",
            "email": "niran@chon-cast.th",
            "tel_whatsapp_wechat": "+66 38 222 1111",
            "nature_of_product": "OEM",
            "item_group_name": "OEM INDUSTRIAL PARTS",
            "production_method": "Casting",
            "tag_1": "casting",
            "tag_2": "iron",
            "tag_3": "welding",
            "tag_4": None,
            "notes": "Thai casting for industrial OEM.",
        },
        {
            "status": "Current",
            "meet": "Made in China",
            "country": "China",
            "cn_province": "ZHEJIANG PROVINCE",
            "city": "Hangzhou",
            "factory_trading_name": "Hangzhou Furniture Components",
            "website": "https://hz-furn.cn",
            "contact_name": "Ye Qing",
            "email": "qing@hz-furn.cn",
            "tel_whatsapp_wechat": "+86 571 6666 4545",
            "nature_of_product": "OEM",
            "item_group_name": "FURNITURES",
            "production_method": "Machining",
            "tag_1": "CNC",
            "tag_2": "wood metal",
            "tag_3": None,
            "tag_4": None,
            "notes": "Furniture hardware OEM.",
        },
    ]
    cols = [
        "short_code", "status", "interest_level", "meet", "country", "cn_province", "city",
        "factory_trading_name", "website", "contact_name", "email",
        "tel_whatsapp_wechat", "nature_of_product", "item_group_name",
        "production_method", "tag_1", "tag_2", "tag_3", "tag_4", "notes",
        "created_at", "updated_at", "created_by", "updated_by",
    ]
    interest_cycle = config.INTEREST_LEVEL_VALUES  # Must visit, Interesting, In Case
    for i, s in enumerate(samples, start=1):
        s = dict(s)
        s["short_code"] = f"SUP-{i:04d}"
        if not s.get("interest_level"):
            s["interest_level"] = interest_cycle[(i - 1) % len(interest_cycle)]
        values = [s.get(c) for c in cols[:-4]] + [now, now, admin_id, admin_id]
        placeholders = ",".join("?" * len(cols))
        conn.execute(
            f"INSERT INTO suppliers ({','.join(cols)}) VALUES ({placeholders})",
            values,
        )
        for ti in range(1, 5):
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

    nature = (data.get("nature_of_product") or "").strip()
    if nature and nature not in lookups.get("nature_of_product", []):
        errors.append("Nature of Product must be chosen from the list.")

    method = (data.get("production_method") or "").strip()
    cn_province = (data.get("cn_province") or "").strip()

    if nature == "OEM":
        if not method or method == "N/A":
            errors.append("Production Method is required when Nature of Product is OEM.")
        elif method not in lookups.get("production_method", []):
            errors.append("Production Method must be chosen from the list.")

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
        out["production_method"] = "N/A"
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


def list_all_known_tag_labels(conn) -> list[str]:
    """All distinct tags from known_tags + live supplier tag fields."""
    rows = conn.execute(
        """
        SELECT DISTINCT tag FROM (
            SELECT tag FROM known_tags
            UNION SELECT tag_1 AS tag FROM suppliers WHERE tag_1 IS NOT NULL AND tag_1 != ''
            UNION SELECT tag_2 FROM suppliers WHERE tag_2 IS NOT NULL AND tag_2 != ''
            UNION SELECT tag_3 FROM suppliers WHERE tag_3 IS NOT NULL AND tag_3 != ''
            UNION SELECT tag_4 FROM suppliers WHERE tag_4 IS NOT NULL AND tag_4 != ''
        )
        WHERE tag IS NOT NULL AND tag != ''
        ORDER BY tag COLLATE NOCASE
        """
    ).fetchall()
    return [r["tag"] for r in rows]


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
    for label in list_all_known_tag_labels(conn):
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
