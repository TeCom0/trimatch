"""UBL 2.1 e-invoices (docs/plan-phase1-ubl.md): schema check, parser, and a writer used by
the generator and the tests.

Structured input needs no model: values are read from the XML, confidence 1.0, and each
value records the element it came from (Field.locator). Where the Moroccan identifiers sit
is an assumption kept in config/ubl_ma.yaml until the DGI publishes its specification.

Security: the parser never resolves entities, loads DTDs or touches the network, and any
DOCTYPE is refused (no XXE, no billion laughs).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path

import yaml
from lxml import etree

from trimatch.checks import Check
from trimatch.config import CONFIG_DIR
from trimatch.schema import Field, Invoice, Line, Party, VatBreakdown

XSD = Path(__file__).parent / "ubl21" / "maindoc" / "UBL-Invoice-2.1.xsd"
NS = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
INV, CAC, CBC = (f"{{{NS[k]}}}" for k in ("inv", "cac", "cbc"))


@dataclass(frozen=True)
class Mapping:
    customization_id: str
    currency: str
    party: dict[str, dict[str, str]]
    vat_category: dict[str, str]
    units: dict[str, str]  # code -> printed unit

    @property
    def unit_codes(self) -> dict[str, str]:
        return {v: k for k, v in self.units.items()}


@cache
def load_mapping(path: Path = CONFIG_DIR / "ubl_ma.yaml") -> Mapping:
    return Mapping(**yaml.safe_load(path.read_text(encoding="utf-8")))


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


class UblError(ValueError):
    pass


def parse_xml(data: bytes) -> etree._Element:
    if b"<!DOCTYPE" in data[:4096].upper():
        raise UblError("DOCTYPE is not allowed in an e-invoice")
    try:
        root = etree.fromstring(data, parser=_parser())
    except etree.XMLSyntaxError as exc:
        raise UblError(f"not well-formed XML: {exc}") from exc
    return root


@cache
def _schema() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(XSD), parser=_parser()))


def schema_errors(data: bytes, limit: int = 5) -> list[str]:
    """[] if the file is a schema-valid UBL 2.1 Invoice, else the first errors."""
    try:
        root = parse_xml(data)
    except UblError as exc:
        return [str(exc)]
    if root.tag != f"{INV}Invoice":
        return [f"root element is {etree.QName(root).localname}, not a UBL Invoice"]
    schema = _schema()
    if schema.validate(root):
        return []
    return [f"line {e.line}: {_short(e.message)}" for e in list(schema.error_log)[:limit]]


def _short(msg: str, max_len: int = 300) -> str:
    """Schema messages with prefixes instead of full namespace URIs."""
    for prefix in ("cbc", "cac", "inv"):
        msg = msg.replace(f"{{{NS[prefix]}}}", "" if prefix == "inv" else f"{prefix}:")
    return msg if len(msg) <= max_len else msg[: max_len - 1] + "…"


def ubl_check(path: Path) -> Check:
    """UBL_INVALID: the file is not a schema-valid UBL 2.1 Invoice (plain validation code)."""
    errors = schema_errors(path.read_bytes())
    return Check("UBL_INVALID", not errors, "; ".join(errors), "invoice")


# --- parser ------------------------------------------------------------------------------


def _q(path: str) -> str:
    return "/".join(path.split("/"))


def _first(node: etree._Element | None, path: str) -> etree._Element | None:
    if node is None:
        return None
    found = node.find(_q(path), NS)
    return found


def _text(node: etree._Element | None, path: str) -> str | None:
    el = _first(node, path)
    if el is None or el.text is None:
        return None
    return " ".join(el.text.split()) or None


def _field(value, locator: str) -> Field:
    return Field(value=value, confidence=1.0 if value is not None else 0.0, locator=locator)


def _dec(s: str | None) -> Decimal | None:
    if s is None:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def _scheme_id(party: etree._Element | None, element: str, scheme: str) -> str | None:
    if party is None:
        return None
    for el in party.findall(_q(element), NS):
        if el.get("schemeID") == scheme and el.text:
            return el.text.strip()
    return None


def _party(root: etree._Element, role: str, m: Mapping) -> Party:
    base = f"cac:{role}/cac:Party"
    p = _first(root, base)

    def ident(key: str) -> Field | None:
        spec = m.party[key]
        v = _scheme_id(p, spec["element"], spec["scheme"])
        loc = f"{base}/{spec['element']}[@schemeID='{spec['scheme']}']"
        return _field(v, loc) if v is not None or key == "ice" else None

    name = _text(p, "cac:PartyLegalEntity/cbc:RegistrationName") or _text(
        p, "cac:PartyName/cbc:Name"
    )
    return Party(
        name=_field(name, f"{base}/cac:PartyLegalEntity/cbc:RegistrationName"),
        ice=ident("ice"),
        if_number=ident("if_number"),
        tp_number=ident("tp_number"),
        rc=ident("rc"),
    )


def _opt(value, locator: str) -> Field | None:
    return _field(value, locator) if value is not None else None


def parse_invoice(data: bytes, m: Mapping | None = None) -> Invoice:
    """Best-effort parse of a UBL 2.1 Invoice. Never guesses: a missing or malformed value
    is None (and the checks flag it); schema problems are reported by ubl_check."""
    m = m or load_mapping()
    try:
        root = parse_xml(data)
    except UblError:
        root = etree.Element(f"{INV}Invoice")  # unreadable: an empty invoice, all None
    lines = []
    for i, ln in enumerate(root.findall("cac:InvoiceLine", NS)):
        base = f"cac:InvoiceLine[{i + 1}]"
        qty_el = _first(ln, "cbc:InvoicedQuantity")
        unit_code = qty_el.get("unitCode") if qty_el is not None else None
        cat = _text(ln, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID")
        pct = _dec(_text(ln, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent"))
        rate = Decimal(0) if cat == m.vat_category["exempt"] else pct
        lines.append(
            Line(
                description=_field(_text(ln, "cac:Item/cbc:Name"), f"{base}/cac:Item/cbc:Name"),
                supplier_ref=_opt(
                    _text(ln, "cac:Item/cac:SellersItemIdentification/cbc:ID"),
                    f"{base}/cac:Item/cac:SellersItemIdentification/cbc:ID",
                ),
                quantity=_field(
                    _dec(_text(ln, "cbc:InvoicedQuantity")), f"{base}/cbc:InvoicedQuantity"
                ),
                unit=_opt(m.units.get(unit_code or ""), f"{base}/cbc:InvoicedQuantity/@unitCode"),
                unit_price_ht=_opt(
                    _dec(_text(ln, "cac:Price/cbc:PriceAmount")),
                    f"{base}/cac:Price/cbc:PriceAmount",
                ),
                vat_rate=_opt(rate, f"{base}/cac:Item/cac:ClassifiedTaxCategory"),
                exemption_ref=_opt(
                    _text(ln, "cac:Item/cac:ClassifiedTaxCategory/cbc:TaxExemptionReason"),
                    f"{base}/cac:Item/cac:ClassifiedTaxCategory/cbc:TaxExemptionReason",
                ),
                line_total_ht=_opt(
                    _dec(_text(ln, "cbc:LineExtensionAmount")), f"{base}/cbc:LineExtensionAmount"
                ),
            )
        )
    vat = []
    for i, st in enumerate(root.findall("cac:TaxTotal/cac:TaxSubtotal", NS)):
        base = f"cac:TaxTotal/cac:TaxSubtotal[{i + 1}]"
        cat = _text(st, "cac:TaxCategory/cbc:ID")
        pct = _dec(_text(st, "cac:TaxCategory/cbc:Percent"))
        vat.append(
            VatBreakdown(
                rate=_field(
                    Decimal(0) if cat == m.vat_category["exempt"] else pct,
                    f"{base}/cac:TaxCategory",
                ),
                base_ht=_field(_dec(_text(st, "cbc:TaxableAmount")), f"{base}/cbc:TaxableAmount"),
                amount=_field(_dec(_text(st, "cbc:TaxAmount")), f"{base}/cbc:TaxAmount"),
            )
        )
    po = _text(root, "cac:OrderReference/cbc:ID")
    bl_refs = [
        _field(" ".join(el.text.split()), f"cac:DespatchDocumentReference[{i + 1}]/cbc:ID")
        for i, el in enumerate(root.findall("cac:DespatchDocumentReference/cbc:ID", NS))
        if el.text and el.text.strip()
    ]
    terms = _text(root, "cac:PaymentTerms/cbc:Note")
    due = _date(_text(root, "cbc:DueDate"))
    return Invoice(
        doc_type="invoice",
        supplier=_party(root, "AccountingSupplierParty", m),
        customer=_party(root, "AccountingCustomerParty", m),
        number=_field(_text(root, "cbc:ID"), "cbc:ID"),
        date=_field(_date(_text(root, "cbc:IssueDate")), "cbc:IssueDate"),
        due_date=_opt(due, "cbc:DueDate"),
        payment_terms=_opt(terms, "cac:PaymentTerms/cbc:Note"),
        po_ref=_opt(po, "cac:OrderReference/cbc:ID"),
        bl_refs=bl_refs,
        currency="MAD",
        lines=lines,
        total_ht=_field(
            _dec(_text(root, "cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount")),
            "cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount",
        ),
        vat=vat,
        total_ttc=_field(
            _dec(_text(root, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount")),
            "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount",
        ),
    )


class UblExtractor:
    """Extractor for .xml files (see extract.get_extractor: XML never goes to a model)."""

    name = "ubl"

    def extract(self, path: Path) -> Invoice:
        return parse_invoice(path.read_bytes())


# --- writer (generator, tests) ---------------------------------------------------------------


def _el(parent, tag: str, text=None, **attrs):
    prefix, local = tag.split(":")
    e = etree.SubElement(parent, f"{{{NS[prefix]}}}{local}", {k: str(v) for k, v in attrs.items()})
    if text is not None:
        e.text = str(text)
    return e


def _amount(parent, tag: str, value: Decimal, m: Mapping):
    return _el(parent, tag, f"{value:.2f}", currencyID=m.currency)


def _write_party(parent, role: str, party: Party, m: Mapping) -> None:
    p = _el(_el(parent, f"cac:{role}"), "cac:Party")
    for key in ("if_number", "tp_number", "rc"):
        f = getattr(party, key)
        if f is not None and f.value is not None:
            spec = m.party[key]
            _el(_el(p, "cac:PartyIdentification"), "cbc:ID", f.value, schemeID=spec["scheme"])
    _el(_el(p, "cac:PartyName"), "cbc:Name", party.name.value)
    le = _el(p, "cac:PartyLegalEntity")
    _el(le, "cbc:RegistrationName", party.name.value)
    _el(le, "cbc:CompanyID", party.ice.value, schemeID=m.party["ice"]["scheme"])


def _tax_category(parent, tag: str, rate: Decimal, exemption: str | None, m: Mapping) -> None:
    c = _el(parent, tag)
    exempt = rate == 0
    _el(c, "cbc:ID", m.vat_category["exempt" if exempt else "standard"])
    _el(c, "cbc:Percent", f"{rate:.0f}" if rate == rate.to_integral() else rate)
    if exempt and exemption:
        _el(c, "cbc:TaxExemptionReason", exemption)
    _el(_el(c, "cac:TaxScheme"), "cbc:ID", "VAT")


def write_invoice(inv: Invoice, m: Mapping | None = None) -> bytes:
    """A schema-valid UBL 2.1 Invoice for a schema.Invoice (element order as in the XSD)."""
    m = m or load_mapping()
    root = etree.Element(
        f"{INV}Invoice", nsmap={None: NS["inv"], "cac": NS["cac"], "cbc": NS["cbc"]}
    )
    _el(root, "cbc:UBLVersionID", "2.1")
    _el(root, "cbc:CustomizationID", m.customization_id)
    _el(root, "cbc:ID", inv.number.value)
    _el(root, "cbc:IssueDate", inv.date.value.isoformat())
    if inv.due_date and inv.due_date.value:
        _el(root, "cbc:DueDate", inv.due_date.value.isoformat())
    _el(root, "cbc:InvoiceTypeCode", "380")
    _el(root, "cbc:DocumentCurrencyCode", m.currency)
    if inv.po_ref and inv.po_ref.value:
        _el(_el(root, "cac:OrderReference"), "cbc:ID", inv.po_ref.value)
    for r in inv.bl_refs:
        _el(_el(root, "cac:DespatchDocumentReference"), "cbc:ID", r.value)
    _write_party(root, "AccountingSupplierParty", inv.supplier, m)
    _write_party(root, "AccountingCustomerParty", inv.customer, m)
    if inv.payment_terms and inv.payment_terms.value:
        _el(_el(root, "cac:PaymentTerms"), "cbc:Note", inv.payment_terms.value)
    tt = _el(root, "cac:TaxTotal")
    _amount(tt, "cbc:TaxAmount", sum((v.amount.value for v in inv.vat), Decimal(0)), m)
    for v in inv.vat:
        st = _el(tt, "cac:TaxSubtotal")
        _amount(st, "cbc:TaxableAmount", v.base_ht.value, m)
        _amount(st, "cbc:TaxAmount", v.amount.value, m)
        exemption = next(
            (
                ln.exemption_ref.value
                for ln in inv.lines
                if ln.exemption_ref and ln.vat_rate and ln.vat_rate.value == v.rate.value
            ),
            None,
        )
        _tax_category(st, "cac:TaxCategory", v.rate.value, exemption, m)
    lmt = _el(root, "cac:LegalMonetaryTotal")
    _amount(
        lmt,
        "cbc:LineExtensionAmount",
        sum((ln.line_total_ht.value for ln in inv.lines), Decimal(0)),
        m,
    )
    _amount(lmt, "cbc:TaxExclusiveAmount", inv.total_ht.value, m)
    _amount(lmt, "cbc:TaxInclusiveAmount", inv.total_ttc.value, m)
    _amount(lmt, "cbc:PayableAmount", inv.total_ttc.value, m)
    codes = m.unit_codes
    for i, ln in enumerate(inv.lines, start=1):
        il = _el(root, "cac:InvoiceLine")
        _el(il, "cbc:ID", i)
        _el(
            il,
            "cbc:InvoicedQuantity",
            ln.quantity.value,
            **({"unitCode": codes[ln.unit.value]} if ln.unit and ln.unit.value in codes else {}),
        )
        _amount(il, "cbc:LineExtensionAmount", ln.line_total_ht.value, m)
        item = _el(il, "cac:Item")
        _el(item, "cbc:Name", ln.description.value)
        if ln.supplier_ref and ln.supplier_ref.value:
            _el(_el(item, "cac:SellersItemIdentification"), "cbc:ID", ln.supplier_ref.value)
        _tax_category(
            item,
            "cac:ClassifiedTaxCategory",
            ln.vat_rate.value,
            ln.exemption_ref.value if ln.exemption_ref else None,
            m,
        )
        _amount(_el(il, "cac:Price"), "cbc:PriceAmount", ln.unit_price_ht.value, m)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
