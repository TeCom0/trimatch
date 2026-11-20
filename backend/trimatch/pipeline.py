"""The `trimatch process` flow (plan-step3-match-and-draft.md): extract, group, validate,
match, decide, then a draft bill in Odoo or a review entry. Nothing is ever posted."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from trimatch.checks import Check
from trimatch.config import REPO_ROOT, MatchConfig, load_config
from trimatch.decide import Decision, confidence_check, decide
from trimatch.duplicates import KnownInvoice, duplicate_check, known_from
from trimatch.extract import Extractor
from trimatch.match import LinePair, PoSnapshot, match_order
from trimatch.odoo_adapter import OdooClient
from trimatch.schema import DeliveryNote, Invoice
from trimatch.validate import OdooRefs, validate_bl, validate_invoice

REVIEW_DIR = REPO_ROOT / "data" / "review"
TOL = Decimal("0.01")


@dataclass
class Extracted:
    path: Path
    doc: DeliveryNote | Invoice
    error: str | None = None  # extraction failed: doc is an empty invoice, case to review


@dataclass
class Result:
    invoice_file: str
    bl_file: str | None
    supplier: str
    invoice_number: str
    po_ref: str | None
    decision: Decision
    bill: dict | None = None
    review_file: str | None = None
    duplicates: list[str] = field(default_factory=list)


def _key(doc: DeliveryNote | Invoice) -> tuple:
    return (doc.doc_type, doc.supplier.ice.value, doc.number.value)


def group(
    items: list[Extracted],
) -> tuple[list[tuple[Extracted, Extracted | None, list[Path]]], list[Extracted]]:
    """-> ([(invoice, bl or None, duplicate copies)], unused BLs).

    Copies of the same document (same type, supplier ICE and number) are processed once.
    An invoice takes the BL named in its bl_refs, else the BL with the same PO and supplier.
    """
    firsts: dict[tuple, Extracted] = {}
    dups: dict[tuple, list[Path]] = {}
    for it in sorted(items, key=lambda x: x.path.name):
        k = _key(it.doc)
        if k in firsts:
            dups.setdefault(k, []).append(it.path)
        else:
            firsts[k] = it
    invoices = [e for e in firsts.values() if isinstance(e.doc, Invoice)]
    bls = [e for e in firsts.values() if isinstance(e.doc, DeliveryNote)]
    used: set[int] = set()
    groups = []
    for inv in invoices:
        d: Invoice = inv.doc
        refs = {r.value for r in d.bl_refs}
        cand = [
            b
            for b in bls
            if b.doc.number.value in refs and b.doc.supplier.ice.value == d.supplier.ice.value
        ]
        if not cand:
            cand = [
                b
                for b in bls
                if b.doc.supplier.ice.value == d.supplier.ice.value
                and d.po_ref
                and b.doc.po_ref
                and b.doc.po_ref.value == d.po_ref.value
            ]
        bl = cand[0] if cand else None
        if bl:
            used.add(id(bl))
        all_dups = dups.get(_key(d), []) + (dups.get(_key(bl.doc), []) if bl else [])
        groups.append((inv, bl, all_dups))
    return groups, [b for b in bls if id(b) not in used]


def _money(x: float) -> Decimal:
    return Decimal(str(round(x, 2))).quantize(TOL)


def _jsonable(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(type(obj))


# --- pure part: the same code runs for `trimatch process` and for the review screen -------


@dataclass
class Evaluation:
    checks: list[Check]
    pairs: list[LinePair]
    decision: Decision
    partner_id: int | None


def supplier_partner_id(inv: Invoice, refs: OdooRefs) -> int | None:
    sup = [s for s in refs.suppliers if s["ice"] == inv.supplier.ice.value]
    return sup[0]["id"] if len(sup) == 1 else None


def po_ref_of(inv: Invoice, bl: DeliveryNote | None) -> str | None:
    if inv.po_ref and inv.po_ref.value:
        return inv.po_ref.value
    return bl.po_ref.value if bl and bl.po_ref else None


def evaluate(
    inv: Invoice,
    bl: DeliveryNote | None,
    po: PoSnapshot | None,
    refs: OdooRefs,
    cfg: MatchConfig,
    known: list[KnownInvoice] | None = None,
    file_checks: list[Check] | None = None,
) -> Evaluation:
    """Validation + three-way match + decision. Pure: Odoo data comes in as arguments.

    `known`: invoices already in Odoo, in the review store or earlier in this run, for the
    duplicate check (duplicates.py). `file_checks`: checks on the file itself, e.g.
    UBL_INVALID for an e-invoice (see file_checks())."""
    partner_id = supplier_partner_id(inv, refs)
    checks: list[Check] = validate_invoice(inv, refs, cfg)
    checks.append(confidence_check(inv, cfg, "invoice"))
    checks.append(duplicate_check(inv, known or []))
    checks += file_checks or []
    if bl:
        checks += validate_bl(bl, refs)
        checks.append(confidence_check(bl, cfg, "bl"))
    match_checks, pairs = match_order(inv, bl, po, partner_id, cfg)
    checks += match_checks
    return Evaluation(checks, pairs, decide(checks), partner_id)


# --- Odoo side effects ------------------------------------------------------------------


def create_checked_draft(
    client: OdooClient,
    po: PoSnapshot,
    inv: Invoice,
    pairs: list[LinePair],
    files: list[Path],
) -> tuple[dict | None, Check | None]:
    """Draft bill + totals safety check + attachments. -> (bill, None) or (None, failed check).

    If Odoo's totals differ from the invoice, the draft created here is deleted again and
    the case goes to review with BILL_TOTAL_MISMATCH. Nothing is ever posted.
    """
    bill = client.create_draft_bill(po, inv, pairs)
    vat_total = sum((v.amount.value for v in inv.vat), Decimal(0))
    diffs = [
        f"{name}: Odoo {_money(bill[f])} vs invoice {want}"
        for name, f, want in (
            ("untaxed", "amount_untaxed", inv.total_ht.value),
            ("tax", "amount_tax", vat_total),
            ("total", "amount_total", inv.total_ttc.value),
        )
        if abs(_money(bill[f]) - want) > TOL
    ]
    if diffs:
        client.delete_own_draft(bill["id"])
        return None, Check("BILL_TOTAL_MISMATCH", False, "; ".join(diffs))
    att_ids = client.attach("account.move", bill["id"], files)
    # Show the invoice (not the BL) in Odoo's document preview.
    client.call(
        "account.move", "write", ids=[bill["id"]], vals={"message_main_attachment_id": att_ids[0]}
    )
    return bill, None


# --- review queue -----------------------------------------------------------------------


def review_entry(res: Result, inv: Extracted, bl: Extracted | None, po: PoSnapshot | None) -> dict:
    """One review case as plain JSON: the format of the store and of `data/review/*.json`."""
    entry = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "decision": "review",
        "reason_codes": res.decision.codes,
        "reasons": [c.to_dict() for c in res.decision.reasons],
        "files": {"invoice": str(inv.path), "bl": str(bl.path) if bl else None},
        "invoice": inv.doc.model_dump(mode="json"),
        "bl": bl.doc.model_dump(mode="json") if bl else None,
        "odoo_po": asdict(po) if po else None,
    }
    return json.loads(json.dumps(entry, ensure_ascii=False, default=_jsonable))


class ReviewSink(Protocol):
    def __call__(self, entry: dict) -> str: ...


class JsonReviewSink:
    """Writes `<dir>/<supplier ICE>_<invoice no>.json` (the Phase 0 format)."""

    def __init__(self, review_dir: Path = REVIEW_DIR):
        self.review_dir = review_dir

    def __call__(self, entry: dict) -> str:
        self.review_dir.mkdir(parents=True, exist_ok=True)
        number = entry["invoice"]["number"]["value"] or "unknown"
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in number)
        path = self.review_dir / f"{entry['invoice']['supplier']['ice']['value']}_{safe}.json"
        path.write_text(json.dumps(entry, indent=1, ensure_ascii=False), encoding="utf-8")
        return str(path)


def process_group(
    inv_x: Extracted,
    bl_x: Extracted | None,
    client: OdooClient,
    refs: OdooRefs,
    cfg: MatchConfig,
    dry_run: bool,
    review_sink: ReviewSink,
    seen: list[KnownInvoice] | None = None,
    prior: PriorCases | None = None,
) -> Result:
    inv: Invoice = inv_x.doc
    bl = bl_x.doc if bl_x else None
    partner_id = supplier_partner_id(inv, refs)
    po_ref = po_ref_of(inv, bl)
    res = Result(
        inv_x.path.name,
        bl_x.path.name if bl_x else None,
        inv.supplier.name.value or "?",
        inv.number.value or "?",
        po_ref,
        Decision("review"),
    )

    if partner_id and inv.number.value:
        existing = client.find_bill(partner_id, inv.number.value)
        if existing:
            res.decision = Decision(
                "skip",
                [
                    Check(
                        "ALREADY_DRAFTED",
                        False,
                        f"Odoo bill id {existing[0]['id']} "
                        f"({existing[0]['state']}) already has ref {inv.number.value}",
                    )
                ],
            )
            res.bill = existing[0]
            return res

    po = client.po_snapshot(po_ref) if po_ref else None
    known = list(seen or [])
    known += odoo_known(client, partner_id, inv)
    if prior is not None:
        known += prior(inv)
    extra = file_checks(inv_x.path)
    if inv_x.error:
        extra.append(Check("EXTRACTION_FAILED", False, inv_x.error, "invoice"))
    ev = evaluate(inv, bl, po, refs, cfg, known, extra)
    res.decision = ev.decision

    if res.decision.action == "draft" and not dry_run:
        files = [inv_x.path] + ([bl_x.path] if bl_x else [])
        bill, failure = create_checked_draft(client, po, inv, ev.pairs, files)
        if failure:
            res.decision = Decision("review", [failure])
        res.bill = bill

    if res.decision.action == "review" and not dry_run:
        res.review_file = review_sink(review_entry(res, inv_x, bl_x, po))
    return res


def process(
    paths: list[Path],
    extractor: Extractor,
    client: OdooClient,
    dry_run: bool = False,
    review_sink: ReviewSink | None = None,
    prior: PriorCases | None = None,
) -> tuple[list[Result], list[Extracted]]:
    """Run the whole flow. Review cases go to `review_sink` (default: JSON in data/review)."""
    sink = review_sink or JsonReviewSink()
    cfg = load_config()
    workers = getattr(extractor, "max_workers", 1)
    with ThreadPoolExecutor(max_workers=workers) as pool:  # order kept; rate limit in extractor
        items = list(pool.map(lambda p: _safe_extract(extractor, p), paths))
    groups, lone_bls = group(items)
    # Oldest invoice first, so that of two copies the later one is the suspected duplicate.
    groups.sort(key=lambda g: (g[0].doc.date.value or date.max, g[0].path.name))
    company = client.buyer_company()
    refs = OdooRefs(company_ice=company["ice"], suppliers=client.suppliers())
    results = []
    seen: list[KnownInvoice] = []
    for inv_x, bl_x, dups in groups:
        r = process_group(inv_x, bl_x, client, refs, cfg, dry_run, sink, seen, prior)
        r.duplicates = [p.name for p in dups]
        results.append(r)
        if r.decision.action != "skip":
            seen.append(known_from(inv_x.doc, f"{inv_x.path.name} earlier in this run"))
    return results, lone_bls


def odoo_known(client: OdooClient, partner_id: int | None, inv: Invoice) -> list[KnownInvoice]:
    """Non-cancelled vendor bills of this supplier with the invoice's date and total."""
    if not (partner_id and inv.date.value and inv.total_ttc.value is not None):
        return []
    return [
        KnownInvoice(
            where=f"Odoo bill {b['name'] or '#' + str(b['id'])}",
            supplier_ice=inv.supplier.ice.value,
            number=b["ref"] or None,
            total_ttc=Decimal(str(b["amount_total"])).quantize(TOL),
            invoice_date=inv.date.value,
        )
        for b in client.bills_like(partner_id, inv.date.value, inv.total_ttc.value)
    ]


def _safe_extract(extractor: Extractor, path: Path) -> Extracted:
    """A file the extractor can't read becomes an empty invoice with the reason, so it
    reaches a person (EXTRACTION_FAILED) instead of stopping the run or vanishing."""
    from trimatch.extract.gemini import NotADocument
    from trimatch.extract.ubl import parse_invoice

    try:
        return Extracted(path, extractor.extract(path))
    except NotADocument as exc:
        return Extracted(path, parse_invoice(b""), error=str(exc))


def file_checks(invoice_file: Path) -> list[Check]:
    """Checks on the invoice file itself: an XML e-invoice must be schema-valid UBL 2.1."""
    if invoice_file.suffix.lower() == ".xml":
        from trimatch.extract.ubl import ubl_check

        return [ubl_check(invoice_file)]
    return []


class PriorCases(Protocol):
    """Review cases already in the store that may be the same invoice (store.cases)."""

    def __call__(self, inv: Invoice) -> list[KnownInvoice]: ...
