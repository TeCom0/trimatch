# Seeds the fake company into Odoo 20 (SPEC section 4, docs/plan-step1-odoo.md).
#
# Runs INSIDE the Odoo container through `odoo shell`, which provides `env` (superuser):
#   docker compose -f odoo/docker-compose.yml run --rm odoo bash -c "odoo shell -d trimatch --no-http < /mnt/trimatch/odoo/seed.py"
# (The file is read from the mounted repo inside the container. Piping it from PowerShell
# breaks: PowerShell may prepend a BOM, which Python rejects.)
#
# Idempotent: every record it creates gets an external ID in module "__trimatch__". A second
# run finds them and changes nothing. Everything happens in one transaction, committed at the
# end, so a failure leaves the database as it was.
#
# The bot's API key is printed only when it is created. Set TRIMATCH_ROTATE_KEY=1 to revoke
# the existing key and print a new one.
#
# All French text lives in seed_data.yaml, read as UTF-8 from the mounted repo folder.

import os

import yaml

DATA_FILE = "/mnt/trimatch/odoo/seed_data.yaml"
MODULE = "__trimatch__"
EXEMPT_TAX_NAME = "Exonéré 0% (achats)"

with open(DATA_FILE, encoding="utf-8") as f:
    data = yaml.safe_load(f)

created = []


def find(name):
    return env.ref(f"{MODULE}.{name}", raise_if_not_found=False)


def ensure(name, model, vals):
    """Return the record with external ID MODULE.name, creating it from vals if missing."""
    rec = find(name)
    if rec:
        return rec
    rec = env[model].create(vals)
    env["ir.model.data"].create(
        {"module": MODULE, "name": name, "model": model, "res_id": rec.id, "noupdate": True}
    )
    created.append(f"{model} {name}")
    return rec


# --- 1. Company -------------------------------------------------------------------------
company = env.ref("base.main_company")
morocco = env.ref("base.ma")
mad = env.ref("base.MAD")
if company.chart_template != "ma":
    raise SystemExit(
        f"Company chart is {company.chart_template!r}, expected 'ma'. Create the database with "
        "`odoo db init trimatch --country MA` before installing modules (see odoo/README.md)."
    )
if company.currency_id != mad:
    raise SystemExit(f"Company currency is {company.currency_id.name}, expected MAD.")

c = data["company"]
company_vals = {
    "name": c["name"],
    "street": c["street"],
    "city": c["city"],
    "zip": c["zip"],
    "country_id": morocco.id,
    "vat": c["if_number"],
}
if any(company[k] != v for k, v in company_vals.items() if k != "country_id") or company.country_id != morocco:
    company.write(company_vals)
    created.append("res.company main (updated)")
if company.partner_id._get_additional_identifier("MA_ICE") != c["ice"]:
    company.partner_id.additional_identifiers = {
        **(company.partner_id.additional_identifiers or {}),
        "MA_ICE": c["ice"],
    }
    created.append("company ICE")

# --- 2. Suppliers -----------------------------------------------------------------------
suppliers = {}
for s in data["suppliers"]:
    suppliers[s["key"]] = ensure(
        f"supplier_{s['key']}",
        "res.partner",
        {
            "name": s["name"],
            "vat": s["if_number"],  # MA_TIN = IF; Odoo 20 derives is_company from it
            "street": s["street"],
            "city": s["city"],
            "zip": s["zip"],
            "country_id": morocco.id,
            "additional_identifiers": {"MA_ICE": s["ice"]},
            "supplier_rank": 1,
        },
    )

# --- 3. Taxes: 20% and 10% from the l10n_ma chart, our own 0% exempt, 7%/14% archived ---
chart = env["account.chart.template"].with_company(company)
taxes = {
    20: chart.ref("vat_in_20_146"),  # "Domestic purchases other than fixed assets" 20%
    10: chart.ref("vat_in_10_150"),  # same, 10%
}
taxes[0] = ensure(
    "tax_purchase_exempt",
    "account.tax",
    {
        "name": EXEMPT_TAX_NAME,
        "invoice_label": "Exonéré",
        "description": "Purchases exempt under CGI art. 91 (trimatch seed)",
        "amount": 0.0,
        "amount_type": "percent",
        "type_tax_use": "purchase",
        "tax_group_id": chart.ref("tax_group_vat_0").id,
        "company_id": company.id,
        "country_id": morocco.id,
    },
)
obsolete = env["account.tax"].search(
    [
        ("company_id", "=", company.id),
        ("type_tax_use", "=", "purchase"),
        ("amount", "in", [7.0, 14.0]),
    ]
)
if obsolete:
    obsolete.write({"active": False})
    created.append(f"archived {len(obsolete)} obsolete 7%/14% purchase taxes")

# --- 4. Units of measure ---------------------------------------------------------------
uoms = {"kg": env.ref("uom.product_uom_kgm")}
for name in data["uoms"]:
    uoms[name] = ensure(f"uom_{name}", "uom.uom", {"name": name})

# --- 5. Products ------------------------------------------------------------------------
products = {}
for p in data["products"]:
    supplier = suppliers[p["supplier"]]
    tmpl = ensure(
        f"product_{p['code'].replace('-', '_').lower()}",
        "product.template",
        {
            "name": p["name"],
            "default_code": p["code"],
            "type": "consu",
            "is_storable": True,
            "purchase_ok": True,
            "sale_ok": False,
            "uom_id": uoms[p["uom"]].id,
            "purchase_method": "receive",  # bill control on received quantities
            "supplier_taxes_id": [(6, 0, taxes[p["vat"]].ids)],
            "taxes_id": [(6, 0, [])],
            "seller_ids": [
                (
                    0,
                    0,
                    {
                        "partner_id": supplier.id,
                        "price": p["price"],
                        "product_code": p["code"],
                        "currency_id": mad.id,
                    },
                )
            ],
        },
    )
    products[p["code"]] = (tmpl.product_variant_id, p)

# --- 6. Purchase orders, confirmed, with validated receipts -----------------------------
for po_spec in data["purchase_orders"]:
    po = find(f"po_{po_spec['name'].replace('-', '_').lower()}")
    if po:
        continue
    lines = []
    for line in po_spec["lines"]:
        product, p = products[line["product"]]
        lines.append(
            (
                0,
                0,
                {
                    "product_id": product.id,
                    "product_qty": line["qty"],
                    "uom_id": product.uom_id.id,
                    "price_unit": p["price"],
                    "tax_ids": [(6, 0, product.supplier_taxes_id.ids)],
                },
            )
        )
    po = ensure(
        f"po_{po_spec['name'].replace('-', '_').lower()}",
        "purchase.order",
        {
            "name": po_spec["name"],
            "partner_id": suppliers[po_spec["supplier"]].id,
            "date_order": f"{po_spec['date_order']} 09:00:00",
            "currency_id": mad.id,
            "order_line": lines,
        },
    )
    po.button_confirm()
    if po.state != "purchase":
        raise SystemExit(f"{po.name} is in state {po.state} after confirm, expected 'purchase'.")

    received = {l["product"]: l.get("received", l["qty"]) for l in po_spec["lines"]}
    pickings = po.picking_ids.filtered(lambda pk: pk.state not in ("done", "cancel"))
    for picking in pickings:
        for move in picking.move_ids:
            move.quantity = received[move.product_id.default_code]
            move.picked = True
        result = picking.with_context(
            skip_backorder=True, picking_ids_not_to_backorder=picking.ids
        ).button_validate()
        if result is not True or picking.state != "done":
            raise SystemExit(f"Receipt {picking.name} for {po.name} did not validate: {result!r}")
    created.append(f"validated receipt(s) for {po.name}")

# --- 7. Bot user and API key ------------------------------------------------------------
b = data["bot_user"]
bot = ensure(
    "user_bot",
    "res.users",
    {
        "name": b["name"],
        "login": b["login"],
        "company_id": company.id,
        "company_ids": [(6, 0, company.ids)],
        "group_ids": [
            (
                6,
                0,
                [
                    env.ref("base.group_user").id,
                    env.ref("purchase.group_purchase_user").id,
                    env.ref("account.group_account_invoice").id,
                ],
            )
        ],
    },
)

ApiKeys = env["res.users.apikeys"].sudo()
existing = ApiKeys.search([("user_id", "=", bot.id), ("name", "=", b["api_key_name"])])
new_key = None
if existing and os.environ.get("TRIMATCH_ROTATE_KEY") == "1":
    existing.unlink()
    existing = ApiKeys.browse()
if not existing:
    # Persistent key (no expiration): fine for a local demo, documented in odoo/README.md.
    new_key = env["res.users.apikeys"].with_user(bot).sudo()._generate("rpc", b["api_key_name"], None)
    created.append("bot API key")

env.cr.commit()

# --- Report -----------------------------------------------------------------------------
print("\n=== trimatch seed ===")
print(f"Company: {company.name} (ICE {company.partner_id._get_additional_identifier('MA_ICE')})")
if created:
    print("Changed:")
    for item in created:
        print(f"  - {item}")
else:
    print("Nothing to do: everything already exists.")
if new_key:
    print("\nNew API key for trimatch-bot (shown once). Put it in .env as ODOO_API_KEY:")
    print(f"ODOO_API_KEY={new_key}")
else:
    print("API key already exists (set TRIMATCH_ROTATE_KEY=1 to replace it).")
