"""The response schema sent to Gemini, and its deterministic conversion to schema.py.

Gemini copies values as printed (French formats). Parsing numbers, dates and ICEs is done
here in plain Python, not by the model, so it is testable and never "creative".
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel

from trimatch.schema import Box, DeliveryNote, Field, Invoice, Line, Party, VatBreakdown


class RField(BaseModel):
    text: str | None
    confidence: float
    box: list[int]


class RParty(BaseModel):
    name: RField
    ice: RField
    if_number: RField
    tp_number: RField
    rc: RField


class RLine(BaseModel):
    description: RField
    supplier_ref: RField
    quantity: RField
    unit: RField
    unit_price_ht: RField
    vat_rate: RField
    exemption_ref: RField
    line_total_ht: RField


class RVat(BaseModel):
    rate: RField
    base_ht: RField
    amount: RField


class RDoc(BaseModel):
    doc_type: Literal["invoice", "delivery_note", "other"]
    supplier: RParty
    customer: RParty
    number: RField
    date: RField
    due_date: RField
    payment_terms: RField
    po_ref: RField
    bl_refs: list[RField]
    lines: list[RLine]
    total_ht: RField
    vat: list[RVat]
    total_ttc: RField


# --- parsing of printed values ------------------------------------------------------------

_SPACES = re.compile(r"[\s   ]")


def parse_decimal(s: str | None) -> Decimal | None:
    if s is None:
        return None
    t = _SPACES.sub("", s)
    t = re.sub(r"(?i)(mad|dhs?|%)", "", t)
    if "," in t and "." in t:  # "2.450,00" -> thousands dot, decimal comma
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    try:
        return Decimal(t) if re.fullmatch(r"-?\d+(\.\d+)?", t) else None
    except InvalidOperation:
        return None


def parse_rate(s: str | None) -> Decimal | None:
    if s is None:
        return None
    folded = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().casefold()
    if "exo" in folded:
        return Decimal(0)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%?", s)  # "20 %", "TVA 20 %", "20%"
    return parse_decimal(m[1]) if m else None


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", s)
    try:
        if m:
            return date(int(m[3]), int(m[2]), int(m[1]))
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None
    return None


def parse_ice(s: str | None) -> str | None:
    if s is None:
        return None
    digits = re.sub(r"\D", "", s)
    return digits or None


def parse_text(s: str | None) -> str | None:
    if s is None:
        return None
    t = re.sub(r"\s+", " ", s).strip()
    return t or None


def parse_sentence(s: str | None) -> str | None:
    """Free text such as payment terms: trailing sentence punctuation is not part of it."""
    t = parse_text(s)
    return t.rstrip(" .;:") or None if t else None


def parse_exemption(s: str | None) -> str | None:
    """CGI article reference, normalised to "art. 91-I-A-6°" (stray marks around it dropped)."""
    t = parse_text(s)
    if not t:
        return None
    # The roman part is often OCR'd as "1" or "l" ("91-1-A-10°"): only roman numerals belong there.
    m = re.search(r"(\d+)\s*-\s*([IVX1l]+)\s*-\s*([A-Z])\s*-\s*(\d+)\s*°", t)
    if not m:
        return re.sub(r"\s*CGI\s*$", "", t)
    roman = m[2].replace("1", "I").replace("l", "I")
    return f"art. {m[1]}-{roman}-{m[3]}-{m[4]}°"


def parse_rc(s: str | None) -> str | None:
    """RC number only: the model sometimes keeps the city printed before it."""
    if s is None:
        return None
    m = re.search(r"\d+", s)
    return m[0] if m else None


# --- conversion to schema.py ---------------------------------------------------------------

BoxOf = Callable[[RField], Box | None]


def _box(b: list[int], approximate: bool = True) -> Box | None:
    """Gemini's own [ymin, xmin, ymax, xmax] on 0..1000. An estimate: see extract/snap.py."""
    if len(b) != 4:
        return None
    ymin, xmin, ymax, xmax = (max(0, min(1000, v)) / 1000 for v in b)
    if xmax <= xmin or ymax <= ymin:
        return None
    return Box(page=1, x0=xmin, y0=ymin, x1=xmax, y1=ymax, approximate=approximate)


def model_box(r: RField) -> Box | None:
    return _box(r.box)


def rfields(r: RDoc) -> list[tuple[RField, int | None]]:
    """Every value the model returned, with its table line (None outside the lines)."""
    out: list[tuple[RField, int | None]] = []
    for p in (r.supplier, r.customer):
        out += [(f, None) for f in (p.name, p.ice, p.if_number, p.tp_number, p.rc)]
    out += [(f, None) for f in (r.number, r.date, r.due_date, r.payment_terms, r.po_ref)]
    out += [(f, None) for f in r.bl_refs]
    for i, ln in enumerate(r.lines):
        out += [(f, i) for f in _line_fields(ln)]
    for v in r.vat:
        out += [(f, None) for f in (v.rate, v.base_ht, v.amount)]
    out += [(r.total_ht, None), (r.total_ttc, None)]
    return out


def _line_fields(ln: RLine) -> list[RField]:
    return [
        ln.description,
        ln.supplier_ref,
        ln.quantity,
        ln.unit,
        ln.unit_price_ht,
        ln.vat_rate,
        ln.exemption_ref,
        ln.line_total_ht,
    ]


def _f(r: RField, parse, bx: BoxOf = model_box) -> Field:
    value = parse(r.text)
    conf = max(0.0, min(1.0, r.confidence))
    if r.text is not None and value is None:
        conf = 0.0  # printed but unparseable: never trust it
    return Field(value=value, confidence=conf if value is not None else 0.0, source=bx(r))


def _opt(r: RField, parse, bx: BoxOf = model_box) -> Field | None:
    f = _f(r, parse, bx)
    return f if f.value is not None else None


def _party(p: RParty, bx: BoxOf) -> Party:
    return Party(
        name=_f(p.name, parse_text, bx),
        ice=_f(p.ice, parse_ice, bx),
        if_number=_opt(p.if_number, parse_ice, bx),
        tp_number=_opt(p.tp_number, parse_ice, bx),
        rc=_opt(p.rc, parse_rc, bx),
    )


def _line(ln: RLine, invoice: bool, bx: BoxOf) -> Line:
    return Line(
        description=_f(ln.description, parse_text, bx),
        supplier_ref=_opt(ln.supplier_ref, parse_text, bx),
        quantity=_f(ln.quantity, parse_decimal, bx),
        unit=_opt(ln.unit, parse_text, bx),
        unit_price_ht=_opt(ln.unit_price_ht, parse_decimal, bx) if invoice else None,
        vat_rate=_opt(ln.vat_rate, parse_rate, bx) if invoice else None,
        exemption_ref=_opt(ln.exemption_ref, parse_exemption, bx) if invoice else None,
        line_total_ht=_opt(ln.line_total_ht, parse_decimal, bx) if invoice else None,
    )


def to_document(r: RDoc, box_of: BoxOf = model_box) -> DeliveryNote | Invoice | None:
    """Raw Gemini output -> schema.py document, or None for doc_type 'other'.

    `box_of` gives each value's box: Gemini's own estimate by default, or the snapped
    position (extract/snap.py)."""
    bx = box_of
    if r.doc_type == "delivery_note":
        return DeliveryNote(
            supplier=_party(r.supplier, bx),
            customer=_party(r.customer, bx),
            number=_f(r.number, parse_text, bx),
            date=_f(r.date, parse_date, bx),
            po_ref=_opt(r.po_ref, parse_text, bx),
            lines=[_line(ln, False, bx) for ln in r.lines],
        )
    if r.doc_type == "invoice":
        return Invoice(
            supplier=_party(r.supplier, bx),
            customer=_party(r.customer, bx),
            number=_f(r.number, parse_text, bx),
            date=_f(r.date, parse_date, bx),
            due_date=_opt(r.due_date, parse_date, bx),
            payment_terms=_opt(r.payment_terms, parse_sentence, bx),
            po_ref=_opt(r.po_ref, parse_text, bx),
            bl_refs=[f for f in (_f(b, parse_text, bx) for b in r.bl_refs) if f.value is not None],
            lines=[_line(ln, True, bx) for ln in r.lines],
            total_ht=_f(r.total_ht, parse_decimal, bx),
            vat=[
                VatBreakdown(
                    rate=_f(v.rate, parse_rate, bx),
                    base_ht=_f(v.base_ht, parse_decimal, bx),
                    amount=_f(v.amount, parse_decimal, bx),
                )
                for v in r.vat
            ],
            total_ttc=_f(r.total_ttc, parse_decimal, bx),
        )
    return None
