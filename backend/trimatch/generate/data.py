"""Builds the documents' data (ground truth + print context) from seed_data.yaml and a seed.

Pure Python, no I/O besides reading the YAML. Every random choice uses a Random seeded
from (split seed, document key), so the output only depends on the seed and the YAML.
"""

from __future__ import annotations

import calendar
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from trimatch.money import line_total, q2, totals
from trimatch.schema import DeliveryNote, Invoice, Line, Party, VatBreakdown, truth

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_DATA = REPO_ROOT / "odoo" / "seed_data.yaml"

SPLIT_SEEDS = {"dev": 1, "test": 2, "e2e": 3}
VARIANTS = ["clean", "rot", "blur", "stamp", "handwriting"]
DEGRADED = VARIANTS[1:]
ORDERS_PER_SPLIT = 20

# Visual identity per supplier (fictitious).
BRANDING = {
    "alwaha": {"color": "#8c1c13", "initials": "AW", "shape": "circle"},
    "anfa": {"color": "#1d4e89", "initials": "DA", "shape": "square"},
    "hygipro": {"color": "#1b7f5b", "initials": "HP", "shape": "hexagon"},
}


@dataclass
class GenDoc:
    doc_id: str
    split: str
    kind: str  # "bl" | "invoice"
    variant: str
    po_ref: str
    scenario: str
    label: DeliveryNote | Invoice
    ctx: dict[str, Any] = field(default_factory=dict)  # extra print data (addresses, branding...)
    rng_key: str = ""  # seeds the degradation of this document


@dataclass
class OrderLine:
    product: dict
    qty_invoiced: Decimal
    qty_delivered: Decimal
    price: Decimal  # invoiced unit price HT


def load_seed_data(path: Path = SEED_DATA) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _party(p: dict, full: bool) -> Party:
    return Party(
        name=truth(p["name"]),
        ice=truth(p["ice"]),
        if_number=truth(p["if_number"]) if full else None,
        tp_number=truth(p["tp_number"]) if full else None,
        rc=truth(p["rc"]) if full else None,
    )


def _due_date(inv_date: date, supplier: dict) -> date:
    due = inv_date + timedelta(days=supplier["payment_days"])
    if supplier.get("end_of_month"):
        due = due.replace(day=calendar.monthrange(due.year, due.month)[1])
    return due


def amount_in_words(x: Decimal) -> str:
    from num2words import num2words

    dirhams = int(x)
    cents = int((x - dirhams) * 100)
    words = f"{num2words(dirhams, lang='fr')} dirhams"
    if cents:
        words += f" et {num2words(cents, lang='fr')} centimes"
    return words


def build_order_docs(
    *,
    split: str,
    key: str,
    data: dict,
    supplier: dict,
    lines: list[OrderLine],
    po_ref: str,
    po_date: date,
    scenario: str,
    rng: random.Random,
) -> tuple[DeliveryNote, Invoice, dict]:
    """One order -> (BL label, invoice label, shared print context)."""
    bl_date = po_date + timedelta(days=rng.randint(1, 2))
    inv_date = bl_date + timedelta(days=rng.randint(0, 3))
    year = inv_date.year
    bl_no = f"BL-{supplier['doc_prefix']}-{year}-{rng.randint(100, 999):04d}"
    inv_no = f"FA-{supplier['doc_prefix']}-{year}-{rng.randint(100, 999):04d}"

    sup = _party(supplier, full=True)
    cust = _party(data["company"], full=False)

    bl_lines, inv_lines = [], []
    for ol in lines:
        p = ol.product
        unit = p["uom"]
        bl_lines.append(
            Line(
                description=truth(p["name"]),
                supplier_ref=truth(p["code"]),
                quantity=truth(ol.qty_delivered),
                unit=truth(unit),
            )
        )
        rate = Decimal(p["vat"])
        inv_lines.append(
            Line(
                description=truth(p["name"]),
                supplier_ref=truth(p["code"]),
                quantity=truth(ol.qty_invoiced),
                unit=truth(unit),
                unit_price_ht=truth(ol.price),
                vat_rate=truth(rate),
                exemption_ref=truth(p["exemption_ref"]) if rate == 0 else None,
                line_total_ht=truth(line_total(ol.qty_invoiced, ol.price)),
            )
        )

    total_ht, vat, total_ttc = totals(
        (ln.vat_rate.value, ln.line_total_ht.value) for ln in inv_lines
    )
    bl = DeliveryNote(
        supplier=sup,
        customer=cust,
        number=truth(bl_no),
        date=truth(bl_date),
        po_ref=truth(po_ref),
        lines=bl_lines,
    )
    inv = Invoice(
        supplier=sup,
        customer=cust,
        number=truth(inv_no),
        date=truth(inv_date),
        due_date=truth(_due_date(inv_date, supplier)),
        payment_terms=truth(supplier["payment_terms"]),
        po_ref=truth(po_ref),
        bl_refs=[truth(bl_no)],
        lines=inv_lines,
        total_ht=truth(total_ht),
        vat=[VatBreakdown(rate=truth(r), base_ht=truth(b), amount=truth(a)) for r, b, a in vat],
        total_ttc=truth(total_ttc),
    )
    ctx = {
        "supplier": supplier,
        "company": data["company"],
        "branding": BRANDING[supplier["key"]],
        "amount_words": amount_in_words(total_ttc),
        "city": supplier["city"],
    }
    return bl, inv, ctx


def _docs_for_order(
    split: str,
    key: str,
    bl: DeliveryNote,
    inv: Invoice,
    ctx: dict,
    po_ref: str,
    scenario: str,
    variants_bl: list[str],
    variants_inv: list[str],
) -> list[GenDoc]:
    out = []
    for kind, label, variants in (("bl", bl, variants_bl), ("invoice", inv, variants_inv)):
        for v in variants:
            doc_id = f"{split}_{key}_{kind}_{v}"
            out.append(GenDoc(doc_id, split, kind, v, po_ref, scenario, label, ctx, rng_key=doc_id))
    return out


def build_e2e(data: dict, seed: int) -> list[GenDoc]:
    """The 5 seeded POs: BL + invoice, clean + one degraded variant each (SPEC 8)."""
    suppliers = {s["key"]: s for s in data["suppliers"]}
    products = {p["code"]: p for p in data["products"]}
    docs: list[GenDoc] = []
    for cycle, po in enumerate(data["purchase_orders"]):
        rng = random.Random(f"{seed}-{po['name']}")
        change = po.get("invoice_price_change")
        lines = []
        for ln in po["lines"]:
            p = products[ln["product"]]
            price = Decimal(str(p["price"]))
            if change and change["product"] == ln["product"]:
                price = q2(price * (1 + Decimal(change["pct"]) / 100))
            lines.append(
                OrderLine(
                    product=p,
                    qty_invoiced=Decimal(str(ln["qty"])),  # invoice bills the ordered qty
                    qty_delivered=Decimal(str(ln.get("received", ln["qty"]))),
                    price=price,
                )
            )
        supplier = suppliers[po["supplier"]]
        bl, inv, ctx = build_order_docs(
            split="e2e",
            key=po["name"],
            data=data,
            supplier=supplier,
            lines=lines,
            po_ref=po["name"],
            po_date=date.fromisoformat(po["date_order"]),
            scenario=po["scenario"],
            rng=rng,
        )
        v_bl, v_inv = DEGRADED[cycle % 4], DEGRADED[(cycle + 1) % 4]
        docs += _docs_for_order(
            "e2e",
            po["name"],
            bl,
            inv,
            ctx,
            po["name"],
            po["scenario"],
            ["clean", v_bl],
            ["clean", v_inv],
        )
    return docs


def _random_qty(rng: random.Random, unit: str) -> Decimal:
    if unit == "kg":
        return Decimal(rng.randint(10, 120)) / 2  # 5 to 60 in 0.5 steps
    return Decimal(rng.randint(1, 50))


def build_random(split: str, data: dict, seed: int, n: int = ORDERS_PER_SPLIT) -> list[GenDoc]:
    """dev/test: random orders (not in Odoo) for extraction accuracy, all 5 variants."""
    suppliers = data["suppliers"]
    docs: list[GenDoc] = []
    for i in range(n):
        key = f"{i:04d}"
        rng = random.Random(f"{seed}-{split}-{key}")
        supplier = rng.choice(suppliers)
        catalogue = [p for p in data["products"] if p["supplier"] == supplier["key"]]
        chosen = rng.sample(catalogue, rng.randint(2, min(6, len(catalogue))))
        lines = []
        for p in chosen:
            qty = _random_qty(rng, p["uom"])
            price = q2(Decimal(str(p["price"])) * Decimal(rng.randint(900, 1100)) / 1000)
            lines.append(OrderLine(product=p, qty_invoiced=qty, qty_delivered=qty, price=price))
        po_ref = f"PO-{rng.randint(100, 999)}"
        po_date = date(2026, 9, 1) + timedelta(days=rng.randint(0, 70))
        bl, inv, ctx = build_order_docs(
            split=split,
            key=key,
            data=data,
            supplier=supplier,
            lines=lines,
            po_ref=po_ref,
            po_date=po_date,
            scenario="random",
            rng=rng,
        )
        docs += _docs_for_order(split, key, bl, inv, ctx, po_ref, "random", VARIANTS, VARIANTS)
    return docs


def build_split(split: str, data: dict | None = None) -> list[GenDoc]:
    data = data or load_seed_data()
    seed = SPLIT_SEEDS[split]
    if split == "e2e":
        return build_e2e(data, seed)
    return build_random(split, data, seed)
