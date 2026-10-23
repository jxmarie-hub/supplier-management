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
DEFAULT_STATUS = "Prospect"
NOTES_MAX_LEN = 200

# Default home-table columns = all fields in Jean's display order
ALL_COLUMNS = [
    ("short_code", "Code"),
    ("status", "Status"),
    ("interest_level", "Interest Level"),
    ("factory_trading_name", "Factory Name"),
    ("country", "Country"),
    ("cn_province", "CN Province"),
    ("city", "City"),
    ("nature_of_product", "Nature of product"),
    ("production_method", "Production Method"),
    ("item_group_name", "Item Group"),
    ("tags", "Grouping / Tags"),
    ("meet", "Meet"),
    ("contact_name", "Contact Name"),
    ("email", "Email"),
    ("website", "Website"),
    ("tel_whatsapp_wechat", "Tel"),
    ("notes", "Notes"),
    ("created_at", "Created"),
    ("updated_at", "Updated"),
]

DEFAULT_VISIBLE_COLUMNS = [key for key, _label in ALL_COLUMNS]

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
