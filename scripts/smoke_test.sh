#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE_URL:-http://127.0.0.1:8000}"
COOKIE="$(mktemp)"
SMOKE_NAME="Smoke Test Factory $$"
SMOKE_EMAIL="smoke$$@example.com"
SMOKE_TAG="smoke-tag-$$"
trap 'rm -f "$COOKIE" /tmp/sm_export.xlsx /tmp/sm_ok.pdf /tmp/sm_big.bin /tmp/sm_big.pdf /tmp/sm_home.html' EXIT

echo "== Login page =="
curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/login" | grep -q "Sign in"

echo "== Login =="
CSRF=$(curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/login" | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' | head -1)
test -n "$CSRF"
CODE=$(curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/login" \
  -d "username=admin&password=ChangeMeNow!&csrf_token=$CSRF" \
  -o /dev/null -w "%{http_code}" -D /tmp/sm_login_hdr.txt)
echo "login_http=$CODE"
test "$CODE" = "303"

echo "== Home list (click → read) =="
curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/" -o /tmp/sm_home.html
grep -q "nav-active" /tmp/sm_home.html
grep -q 'data-href="/suppliers/' /tmp/sm_home.html

echo "== CSRF for create =="
CSRF=$(curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/suppliers/new" | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' | head -1)

echo "== Create supplier → read view =="
curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/suppliers/new" \
  -F "csrf_token=$CSRF" \
  -F "short_code=" \
  -F "status=Prospect" \
  -F "interest_level=Must visit" \
  -F "meet=Alibaba" \
  -F "country=China" \
  -F "cn_province=GUANGDONG PROVINCE" \
  -F "city=Shenzhen" \
  -F "factory_trading_name=$SMOKE_NAME" \
  -F "website=" \
  -F "contact_name=Smoke Tester" \
  -F "email=$SMOKE_EMAIL" \
  -F "tel_whatsapp_wechat=" \
  -F "nature_of_product=OEM" \
  -F "item_group_name=LIGHTING" \
  -F "production_method=Casting" \
  -F "tag_1=Battery" \
  -F "tag_2=$SMOKE_TAG" -F "tag_3=" -F "tag_4=" \
  -F "notes=Smoke test note" \
  -F "attachment_type=catalog" \
  -F "tag_resolve_1=" -F "tag_resolve_2=keep" -F "tag_resolve_3=" -F "tag_resolve_4=" \
  -o /tmp/sm_create.html -w "create=%{http_code}\n" -D /tmp/sm_headers.txt
LOC=$(grep -i '^location:' /tmp/sm_headers.txt | awk '{print $2}' | tr -d '\r')
echo "location=$LOC"
test -n "$LOC"
SID=$(echo "$LOC" | sed -n 's|.*/suppliers/\([0-9]*\).*|\1|p')
echo "supplier_id=$SID"
test -n "$SID"
SMOKE_CODE=$(curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/suppliers/$SID/edit" | sed -n 's/.*name="short_code" value="\([^"]*\)".*/\1/p' | head -1)
echo "short_code=$SMOKE_CODE"
test -n "$SMOKE_CODE"
VIEW=$(curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/suppliers/$SID")
echo "$VIEW" | grep -q "Audit"
echo "$VIEW" | grep -q "$SMOKE_NAME"
echo "$VIEW" | grep -q "Edit"

echo "== Tag similarity (Lawnmower vs lawn mower) =="
CSRF=$(curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/suppliers/new" | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' | head -1)
CODE=$(curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/suppliers/new" \
  -F "csrf_token=$CSRF" \
  -F "short_code=" -F "status=Prospect" -F "meet=" \
  -F "country=Vietnam" -F "cn_province=N/A" -F "city=HCMC" \
  -F "factory_trading_name=Tag Unify Smoke Co" \
  -F "website=" -F "contact_name=T" -F "email=tag-unify-smoke@example.com" \
  -F "tel_whatsapp_wechat=" -F "nature_of_product=Finish product" \
  -F "item_group_name=GARDENING MACHINES" -F "production_method=" \
  -F "tag_1=Blade" -F "tag_2=Lawnmower" -F "tag_3=" -F "tag_4=" \
  -F "notes=x" -F "attachment_type=other" \
  -F "tag_resolve_1=" -F "tag_resolve_2=" -F "tag_resolve_3=" -F "tag_resolve_4=" \
  -o /tmp/sm_tag.html -w "%{http_code}")
echo "tag_http=$CODE"
test "$CODE" = "409"
grep -qi "Similar tag" /tmp/sm_tag.html && echo "tag_unify_prompt_ok"

echo "== Wildcard search (filters stay + results) =="
SR=$(curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/search?q=${SMOKE_NAME// /+}")
echo "$SR" | grep -q "$SMOKE_NAME"
echo "$SR" | grep -q 'id="search-form"'
echo "$SR" | grep -q "Run search"
echo "$SR" | grep -q 'data-table'

echo "== Export =="
curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/search/export?country=China" -o /tmp/sm_export.xlsx
python3 - <<'PY'
from openpyxl import load_workbook
wb=load_workbook('/tmp/sm_export.xlsx')
assert wb.active.max_row >= 2
print('export_rows', wb.active.max_row)
PY

echo "== Upload OK via edit =="
printf '%%PDF-1.1 smoke' > /tmp/sm_ok.pdf
CSRF=$(curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/suppliers/$SID/edit" | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' | head -1)
curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/suppliers/$SID/edit" \
  -F "csrf_token=$CSRF" \
  -F "short_code=$SMOKE_CODE" \
  -F "status=Prospect" \
  -F "interest_level=Must visit" \
  -F "meet=Alibaba" \
  -F "country=China" \
  -F "cn_province=GUANGDONG PROVINCE" \
  -F "city=Shenzhen" \
  -F "factory_trading_name=$SMOKE_NAME" \
  -F "contact_name=Smoke Tester" \
  -F "email=$SMOKE_EMAIL" \
  -F "nature_of_product=OEM" \
  -F "item_group_name=LIGHTING" \
  -F "production_method=Casting" \
  -F "tag_1=Battery" \
  -F "tag_2=$SMOKE_TAG" -F "tag_3=" -F "tag_4=" \
  -F "notes=Smoke test note" \
  -F "website=" -F "tel_whatsapp_wechat=" \
  -F "attachment_type=catalog" \
  -F "tag_resolve_1=" -F "tag_resolve_2=keep" -F "tag_resolve_3=" -F "tag_resolve_4=" \
  -F "files=@/tmp/sm_ok.pdf;type=application/pdf" \
  -o /dev/null -D /tmp/sm_up.txt -w "upload=%{http_code}\n"
grep -qi 'location:' /tmp/sm_up.txt

echo "== Upload reject >15MB =="
dd if=/dev/zero of=/tmp/sm_big.bin bs=1M count=16 status=none
mv /tmp/sm_big.bin /tmp/sm_big.pdf
CSRF=$(curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/suppliers/$SID/edit" | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' | head -1)
curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/suppliers/$SID/edit" \
  -F "csrf_token=$CSRF" \
  -F "short_code=$SMOKE_CODE" \
  -F "status=Prospect" \
  -F "interest_level=Must visit" \
  -F "meet=Alibaba" \
  -F "country=China" \
  -F "cn_province=GUANGDONG PROVINCE" \
  -F "city=Shenzhen" \
  -F "factory_trading_name=$SMOKE_NAME" \
  -F "contact_name=Smoke Tester" \
  -F "email=$SMOKE_EMAIL" \
  -F "nature_of_product=OEM" \
  -F "item_group_name=LIGHTING" \
  -F "production_method=Casting" \
  -F "tag_1=Battery" \
  -F "tag_2=$SMOKE_TAG" -F "tag_3=" -F "tag_4=" \
  -F "notes=x" -F "website=" -F "tel_whatsapp_wechat=" \
  -F "attachment_type=other" \
  -F "tag_resolve_1=" -F "tag_resolve_2=keep" -F "tag_resolve_3=" -F "tag_resolve_4=" \
  -F "files=@/tmp/sm_big.pdf;type=application/pdf" \
  -D /tmp/sm_big_hdr.txt -o /dev/null
LOC=$(grep -i '^location:' /tmp/sm_big_hdr.txt | awk '{print $2}' | tr -d '\r')
BODY=$(curl -sS -c "$COOKIE" -b "$COOKIE" "$BASE${LOC}")
echo "$BODY" | grep -qi "15 MB" && echo "size_limit_ok"

echo "== Duplicate warning =="
CSRF=$(curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/suppliers/new" | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' | head -1)
CODE=$(curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/suppliers/new" \
  -F "csrf_token=$CSRF" \
  -F "short_code=SUP-DUP1" \
  -F "status=Current" \
  -F "country=China" \
  -F "cn_province=GUANGDONG PROVINCE" \
  -F "factory_trading_name=$SMOKE_NAME" \
  -F "email=other@example.com" \
  -F "nature_of_product=OEM" \
  -F "production_method=Casting" \
  -F "meet=" -F "city=" -F "website=" -F "contact_name=" -F "tel_whatsapp_wechat=" \
  -F "item_group_name=" -F "tag_1=Battery" -F "tag_2=$SMOKE_TAG" -F "tag_3=" -F "tag_4=" -F "notes=" \
  -F "attachment_type=other" \
  -F "tag_resolve_1=" -F "tag_resolve_2=keep" -F "tag_resolve_3=" -F "tag_resolve_4=" \
  -o /tmp/sm_dup.html -w "%{http_code}")
echo "dup_http=$CODE"
grep -qi "duplicate" /tmp/sm_dup.html && echo "dup_warn_ok"

echo "== Admin lookups =="
curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/admin/lookups?type=meet" | grep -q "Alibaba"

echo "== Delete supplier =="
CSRF=$(curl -fsS -c "$COOKIE" -b "$COOKIE" "$BASE/suppliers/$SID/edit" | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' | head -1)
curl -fsS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/suppliers/$SID/delete" \
  -d "csrf_token=$CSRF" -o /dev/null -w "delete=%{http_code}\n" -D /tmp/sm_del.txt
grep -qi 'location:' /tmp/sm_del.txt

echo "ALL SMOKE CHECKS PASSED"
