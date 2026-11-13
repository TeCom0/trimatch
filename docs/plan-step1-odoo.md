# Build step 1: Odoo 20 in Docker + seed (plan)

Status: APPROVED, 2026-11-13. Covers SPEC section 9, item 1. Nothing else.

Facts below were read from Odoo's own source: branch `20.0`, commit `fa28f4b` (13 Nov 2026), cloned from github.com/odoo/odoo. Each fact gives the file it comes from.

## Facts that shape the plan

| Fact | Source | Consequence |
|---|---|---|
| Odoo 20 refuses PostgreSQL < 16 (`MIN_PG_VERSION = 16`) | `odoo/release.py` | Use `postgres:16`. The Docker Hub examples still show `postgres:15`, which would fail. |
| Demo data is off by default (`--with-demo` is opt-in) | `odoo/tools/config.py` | No flag needed. |
| `/xmlrpc` and `/jsonrpc` still exist in 20: "deprecated in Odoo 19 and scheduled for removal in Odoo 22" | `addons/rpc/controllers/__init__.py` | Settles yesterday's conflict: the blogs were right, the 19.0 docs were wrong. We still use JSON-2 only. |
| JSON-2 routes use `auth='bearer'`, `bearer_scope='rpc'` | `addons/rpc/controllers/json2.py` | The bot's API key must have scope `rpc`. |
| `res.users.apikeys._generate(scope, name, expiration_date)`. Expiration is optional when called with sudo/system rights ("for a persistent key, no value for expiration date") | `odoo/addons/base/models/res_users.py` | The seed script can create a non-expiring key for the bot from `odoo shell`. That's fine for a local demo, and we document it. |
| ICE is stored in `res.partner.additional_identifiers` (JSON) under key `MA_ICE`, read with `_get_additional_identifier('MA_ICE')` | `addons/l10n_ma/models/base_document_layout.py`, `odoo/addons/base/models/res_partner.py` | Seed writes ICE there. Supplier lookup by ICE in the adapter: read suppliers and match in Python (JSON-field domains are not reliable). |
| `l10n_ma` is in Community, auto-installs with `account`, sets default purchase tax `vat_in_20_146` | `addons/l10n_ma/__manifest__.py`, `models/template_ma.py` | Install `l10n_ma` explicitly so the chart is Moroccan. |
| `l10n_ma` still ships 20%, 14%, 10% and 7% purchase taxes (e.g. 7% "Household soap", "Refined sugar") | `addons/l10n_ma/data/template/account.tax-ma.csv` | Odoo's chart has not caught up with the 2026 reform described by secondary sources, or 7% survives. This is **not** legal authority; the CGI PDF still decides. |
| `product.template.purchase_method`: `'purchase'` (ordered qty) or `'receive'` (received qty) | `addons/purchase/models/product.py` | Seed all products with `'receive'`, so Odoo's own bill control uses received quantities. |
| `purchase.order.action_create_invoice(attachment_ids=False)` exists | `addons/purchase/models/purchase_order.py:820` | Used in step 3 (draft creation), not here. |
| Odoo computes its own per-line mismatch hint on bills (`purchase_matching_issue_msg`, price ⬆/⬇ and qty ⚠ against received) | `addons/purchase/models/account_invoice.py:715-730` | "Don't rebuild Odoo": our matcher stays the deterministic authority, but the review entry can also show Odoo's own flag. Good interview point. |

## Proposed SPEC change

SPEC section 9.1 says `uv run python odoo/seed.py` (an external script over the API). I propose seeding **inside the container with `odoo shell`** instead:
- The seed must create the bot user and its API key, so it can't use that key to authenticate itself.
- The ORM gives transactions, external IDs (idempotency) and receipt validation for free. Over JSON-2, receipt validation means driving wizards.
- The pipeline (`trimatch process`) still talks to Odoo only through JSON-2, which is the part worth showing.

## Files

```
odoo/
  docker-compose.yml   # db: postgres:16 ; odoo: odoo:20.0-<dated tag, pinned on the day we pull>
  odoo.conf            # dbfilter=^trimatch$, list_db=False, admin_passwd from env, proxy_mode off
  seed.py              # runs in `odoo shell`; idempotent via external IDs in module "__trimatch__"
  seed_data.yaml       # company, suppliers, products, POs, receipts (the data from SPEC section 4)
```

Commands (from repo root; as built and tested 2026-11-13, see odoo/README.md):

```powershell
docker compose -f odoo/docker-compose.yml up -d db
docker compose -f odoo/docker-compose.yml run --rm odoo odoo db init trimatch --country MA
docker compose -f odoo/docker-compose.yml run --rm odoo odoo -d trimatch -i purchase_stock,l10n_ma --stop-after-init
docker compose -f odoo/docker-compose.yml run --rm odoo bash -c "odoo shell -d trimatch --no-http < /mnt/trimatch/odoo/seed.py"
docker compose -f odoo/docker-compose.yml up -d odoo
```

Two changes from the approved draft, found while building: (1) `db init --country MA` first, because `account` picks the generic chart when the company has no country at install time (`addons/account/models/ir_module.py`); (2) the seed is read from the mounted repo instead of piped with `Get-Content`, because PowerShell prepended a BOM that Python rejected.

The seed prints the bot's API key **only when it creates it**. You paste it into `.env` (`ODOO_API_KEY`). Re-running the seed changes nothing and prints "key already exists". `TRIMATCH_ROTATE_KEY=1` makes a new one.

## What seed.py creates (from SPEC section 4)

1. The company **Riad Atlas Hospitality SARL**: country MA, currency MAD, `l10n_ma` chart, ICE in `additional_identifiers.MA_ICE`.
2. Three suppliers with ICE, IF, RC and address.
3. Fifteen products: `purchase_method='receive'`, default supplier, supplier price (`product.supplierinfo`), units (kg, botte, pack, carton, rouleau as UoMs), and purchase tax per SPEC section 4 (verified CGI 2026). The seed creates a 0% exempt purchase tax (the l10n_ma chart has none) and archives the obsolete 7% and 14% purchase taxes.
4. Five POs, confirmed (`button_confirm`).
5. Receipts validated: PO-002 has one line at ~70%, with the backorder cancelled (no backorder), so `qty_received` < ordered. All others are full.
6. Bot user `trimatch-bot`: Purchase user + Billing (Accountant not needed for drafts), plus an API key with scope `rpc`.

## Check that step 1 is done

A tiny script (`uv run python -m trimatch.odoo_adapter --check`, the first piece of the adapter) calls JSON-2 with the key and prints:
- the company name and ICE,
- 3 suppliers with ICE,
- 5 POs with state `purchase` and, per line, ordered vs received qty (PO-002 shows the shortfall).

That proves the API path works before any extraction code exists.

## Out of this step

Document generation, extraction, matching and bill creation.
