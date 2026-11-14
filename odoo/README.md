# Local Odoo 20 for trimatch

Odoo 20 Community (`odoo:20.0-20261112`) and PostgreSQL 16 in Docker, seeded with the fake company from SPEC section 4. Run everything from the repo root. The commands work the same in PowerShell and bash.

## First setup

```
docker compose -f odoo/docker-compose.yml up -d db
docker compose -f odoo/docker-compose.yml run --rm odoo odoo db init trimatch --country MA
docker compose -f odoo/docker-compose.yml run --rm odoo odoo -d trimatch -i purchase_stock,l10n_ma --stop-after-init
docker compose -f odoo/docker-compose.yml run --rm odoo bash -c "odoo shell -d trimatch --no-http < /mnt/trimatch/odoo/seed.py"
docker compose -f odoo/docker-compose.yml up -d odoo
```

1. `db init --country MA` creates the database with a Moroccan main company. The country must be set before `account` is installed, otherwise Odoo loads its generic chart instead of `l10n_ma`.
2. The module install adds Purchase, Inventory, Invoicing and the Moroccan chart (`l10n_ma`, which auto-installs with `account` anyway).
3. The seed (`odoo/seed.py`, data in `odoo/seed_data.yaml`) creates the company details, 3 suppliers, 15 products, 5 confirmed POs with validated receipts (PO-002 short on one line, no backorder), and the `trimatch-bot` user. It prints the bot's API key once: copy the `ODOO_API_KEY=...` line into `.env` at the repo root.
4. Odoo is then on http://localhost:8069 (bound to 127.0.0.1 only).

Check the API path (JSON-2, with the bot's key from `.env`):

```
uv run --project backend python -m trimatch.odoo_adapter --check
```

It prints the company, the suppliers with ICE, and each PO line's ordered vs received quantity, and ends with `CHECK OK`.

## Re-running and keys

- The seed is idempotent (external IDs in module `__trimatch__`). A second run prints "Nothing to do".
- Lost the key? Revoke it and print a new one:
  `docker compose -f odoo/docker-compose.yml run --rm -e TRIMATCH_ROTATE_KEY=1 odoo bash -c "odoo shell -d trimatch --no-http < /mnt/trimatch/odoo/seed.py"`
- The bot's key has no expiration date and scope `rpc`. That is acceptable for a local demo with a fake company only.
- Replay the bill demo: `docker compose -f odoo/docker-compose.yml run --rm odoo bash -c "odoo shell -d trimatch --no-http < /mnt/trimatch/odoo/reset_bills.py"` deletes the draft bills made by trimatch-bot (never posted ones).
- Start over: `docker compose -f odoo/docker-compose.yml down -v` deletes both volumes.

## Security notes (local demo only)

- `db init` creates the UI login `admin` / `admin`. Ports are published on 127.0.0.1, so this is reachable only from this PC. Change it in the UI if you expose Odoo anywhere.
- The database manager is disabled (`list_db = False`). Its master password comes from `ODOO_ADMIN_PASSWD` if set, otherwise a random one per start (`odoo/entrypoint.sh`).
- PostgreSQL uses `odoo`/`odoo` and is not published outside the Docker network.

## Odoo 20 facts this setup relies on

Read from the image's source (`/usr/lib/python3/dist-packages/odoo`), 2026-11-13. See also docs/plan-step1-odoo.md.

- `res.company` has no `company_registry` field in 20. ICE lives in `res.partner.additional_identifiers["MA_ICE"]` (validated with python-stdnum `ma.ice`); the IF goes in `vat` (identifier `MA_TIN`). `is_company` is computed: a partner is a company when it has a VAT/TIN.
- l10n_ma purchase taxes used: `vat_in_20_146` (20%) and `vat_in_10_150` (10%). The seed adds a 0% exempt purchase tax (group `tax_group_vat_0`) and archives the 7% and 14% purchase taxes.
- UoMs in 20 have no categories (`relative_factor`/`relative_uom_id`). carton, pack, sac, bidon and rouleau are created as standalone units.
- Our `odoo.conf` replaces the image's default config, so it must keep `http_interface = 0.0.0.0`. Without it Odoo 20 listens on 127.0.0.1 inside the container and the published port gets no answer.
