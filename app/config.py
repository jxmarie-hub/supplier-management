"""Application configuration."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT_DIR / "data"))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", ROOT_DIR / "uploads"))
DB_PATH = DATA_DIR / "suppliers.db"
SEED_LOOKUPS_PATH = BASE_DIR / "seed_lookups.json"

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me-in-production-supplier-mgmt")
SESSION_COOKIE = "supplier_mgmt_session"
SESSION_MAX_AGE = 60 * 60 * 12  # 12 hours

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB per file
ALLOWED_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}
ALLOWED_UPLOAD_MIME = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
}

DEFAULT_COUNTRY = "China"
NOTES_MAX_LEN = 200

# Default home-table columns (keys match supplier attribute names)
DEFAULT_VISIBLE_COLUMNS = [
    "short_code",
    "factory_trading_name",
    "contact_name",
    "email",
    "country",
    "status",
    "nature_of_product",
    "tags",
    "notes",
]

# All columns available in the column picker
ALL_COLUMNS = [
    ("short_code", "Code"),
    ("status", "Status"),
    ("interest_level", "Interest level"),
    ("meet", "Meet"),
    ("country", "Country"),
    ("cn_province", "CN Province"),
    ("city", "City"),
    ("factory_trading_name", "Factory Name"),
    ("website", "Website"),
    ("contact_name", "Contact name"),
    ("email", "Email"),
    ("tel_whatsapp_wechat", "Tel / WhatsApp / WeChat"),
    ("nature_of_product", "Nature of Product"),
    ("item_group_name", "Item Group"),
    ("production_method", "Production method"),
    ("tags", "Grouping / Tags"),
    ("notes", "Notes"),
    ("created_at", "Created"),
    ("updated_at", "Updated"),
]

STATUS_VALUES = ["Current", "Prospect", "Inactive"]

# Priority order: Must visit (top) → Interesting → In Case
INTEREST_LEVEL_VALUES = ["Must visit", "Interesting", "In Case"]

ATTACHMENT_TYPES = [
    ("factory_photo", "Factory photo"),
    ("catalog", "Catalog"),
    ("business_card", "Business card"),
    ("other", "Other"),
]

MAX_SAVED_SEARCHES = 3

LOOKUP_TYPES = [
    "country",
    "cn_province",
    "nature_of_product",
    "item_group_name",
    "production_method",
    "meet",
]

LOOKUP_LABELS = {
    "country": "Country",
    "cn_province": "CN Province",
    "nature_of_product": "Nature of Product",
    "item_group_name": "Item Group Name",
    "production_method": "Production Method",
    "meet": "Meet",
}
