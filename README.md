# Supplier Management

**Version:** v2

Internal web app for recording, searching, and exporting suppliers met at trade fairs or found online.

**UI language:** English  
**Stack:** FastAPI + Jinja2 + SQLite + Docker

## Features

- Password login with **Admin** and **Standard** roles (no public registration)
- Supplier CRUD with Excel-aligned fields and dropdown lists
- Status: **Current / Prospect / Inactive**
- Auto ID + optional short code `SUP-XXXX`
- Conditional rules: China → CN Province; OEM → Production method; Finish product → N/A
- 4 tag fields with autocomplete + Admin tag merge
- Multiple attachments (photos/PDF), max **15 MB** each, typed as factory photo / catalog / business card / other
- Duplicate warning (same factory+country or same email) with confirm to save
- Home table with column show/hide preferences per user
- Advanced search with wildcards (`LED*`, `*LED*`), Excel export
- Up to **3** saved favorite searches per user
- Audit fields: created_by / updated_by / created_at / updated_at
- Mobile-friendly create/edit form (large controls, camera-friendly file input)
- **v2:** Click home row → read-only master data; Edit via explicit button; after create → read view
- **v2:** Tag similarity check before save (e.g. Lawnmower vs Lawn mower) with unify / keep prompt
- **v2:** Search results page shows results only + **New search** button
- **v2:** Active nav section highlighted in green

## Quick start (Docker)

```bash
cd supplier-management
docker compose up --build
```

Open http://localhost:8000

## Quick start (local Python)

```bash
cd supplier-management
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Default credentials

| Username | Password       | Role  |
|----------|----------------|-------|
| admin    | ChangeMeNow!   | Admin |

**Change this password immediately** after first login (create a new admin user, then deactivate the default if desired — password change UI can be added later; for now create a new admin and disable `admin`).

## Roles

| Action | Admin | Standard |
|--------|-------|----------|
| Create / edit / delete suppliers | Yes | Yes |
| Search / export / attachments / columns / favorites | Yes | Yes |
| Manage dropdown lists | Yes | No |
| Manage users | Yes | No |
| Merge tags | Yes | No |

## Data

- Database: `data/suppliers.db` (created on first start, seeded from Excel lists)
- Uploads: `uploads/<supplier_id>/`
- Reference Excel/Word copies: `reference/`

## Hosting (TBD)

Hosting target is not decided yet. Options that fit this stack:

1. **Company PC / LAN** — Docker Compose as above; access via local IP
2. **VPS (DigitalOcean, Hetzner, …)** — Docker Compose + reverse proxy (Caddy/Nginx) with HTTPS + strong `SECRET_KEY`
3. **NAS (Synology/QNAP)** — Container Manager / Docker, map `data` and `uploads` volumes, reverse proxy HTTPS

Always: change default password, set `SECRET_KEY`, prefer HTTPS, restrict who can reach the URL (VPN or firewall if needed).

## Smoke test

```bash
./scripts/smoke_test.sh
```

(Requires the app running on http://127.0.0.1:8000)


## Deferred (by request)

- Change-password UI (create a new admin user for now)
- Admin DB backup/download
- Excel bulk import button
- Products/MOQ, certificates, business-card OCR (later)

## Dropdown cleanup (seed)

Seeded lists are trimmed and de-duplicated. Minor Excel typos corrected at seed time (e.g. `Eqypt` → `Egypt`, `Macodonia` → `Macedonia`, `CHONGQIN` → `CHONGQING`). Nature of Product keeps Excel labels **OEM** / **Finish product**. Duplicate `Congo` rows collapsed to one.
