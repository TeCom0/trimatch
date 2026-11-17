"""Review actions (plan-phase1-review-screen.md): corrections, re-check, approve, reject.

No HTTP here; the FastAPI layer (trimatch.api) calls these. Every decision goes through
pipeline.evaluate(), and an approval creates the draft through
pipeline.create_checked_draft(), exactly like `trimatch process`. Nothing is posted or paid.
"""

from __future__ import annotations

import copy
import html
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from trimatch.config import REPO_ROOT, MatchConfig
from trimatch.match import PoSnapshot
from trimatch.odoo_adapter import OdooClient
from trimatch.pipeline import (
    create_checked_draft,
    evaluate,
    odoo_known,
    po_ref_of,
    supplier_partner_id,
)
from trimatch.reasons import OVERRIDABLE, describe
from trimatch.schema import DeliveryNote, Invoice
from trimatch.store.cases import known_cases
from trimatch.store.models import (
    ActionKind,
    CaseStatus,
    Correction,
    ReviewAction,
    ReviewCase,
)
from trimatch.validate import OdooRefs

DATA_DIR = REPO_ROOT / "data"
DocName = Literal["invoice", "bl"]
MIN_REASON_CHARS = 10


class ReviewError(Exception):
    """A request the reviewer can fix (bad correction, missing reason, blocking check)."""

    def __init__(self, message: str, checks: list[dict] | None = None):
        super().__init__(message)
        self.checks = checks or []


class Conflict(ReviewError):
    """The case is no longer open, or Odoo already has this bill."""


@dataclass(frozen=True)
class FieldEdit:
    doc: DocName
    path: str  # "lines.2.unit_price_ht", "vat.0.base_ht", "po_ref", "supplier.ice"
    value: Any


# --- corrections ------------------------------------------------------------------------


def _walk(node: Any, parts: list[str]) -> tuple[Any, str | int]:
    """-> (container, last key) for a dotted path; raises KeyError on a bad path."""
    for part in parts[:-1]:
        if isinstance(node, list):
            idx = int(part)
            if not 0 <= idx < len(node):
                raise IndexError(idx)
            node = node[idx]
        else:
            node = node[part]
        if node is None:
            raise KeyError(part)
    last = parts[-1]
    if isinstance(node, list):
        idx = int(last)
        if not 0 <= idx < len(node):
            raise IndexError(idx)
        return node, idx
    if last not in node:
        raise KeyError(last)
    return node, last


def apply_edits(doc_json: dict, edits: list[FieldEdit]) -> dict:
    """Return a copy with each edited Field set to the new value, confidence 1.0 (a person
    read it) and its original box kept. Only extracted fields (`{"value", ...}`) can change."""
    out = copy.deepcopy(doc_json)
    for e in edits:
        try:
            container, key = _walk(out, e.path.split("."))
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ReviewError(f"{e.doc}: no field {e.path!r}") from exc
        current = container[key]
        if current is None:
            container[key] = {"value": e.value, "confidence": 1.0, "source": None}
        elif isinstance(current, dict) and "value" in current and "confidence" in current:
            container[key] = {**current, "value": e.value, "confidence": 1.0}
        else:
            raise ReviewError(f"{e.doc}: {e.path!r} is not an extracted value")
    return out


def _parse(kind: DocName, data: dict | None) -> Invoice | DeliveryNote | None:
    if data is None:
        return None
    model = Invoice if kind == "invoice" else DeliveryNote
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ReviewError(f"{kind}: {errors}") from exc


@dataclass
class CaseDocs:
    invoice: Invoice
    bl: DeliveryNote | None
    invoice_json: dict
    bl_json: dict | None


def corrected_docs(case: ReviewCase, edits: list[FieldEdit]) -> CaseDocs:
    for e in edits:
        if e.doc == "bl" and case.bl is None:
            raise ReviewError("this case has no delivery note")
    inv_json = apply_edits(case.invoice, [e for e in edits if e.doc == "invoice"])
    bl_json = apply_edits(case.bl, [e for e in edits if e.doc == "bl"]) if case.bl else None
    return CaseDocs(_parse("invoice", inv_json), _parse("bl", bl_json), inv_json, bl_json)


# --- re-check ---------------------------------------------------------------------------


@dataclass
class Outcome:
    action: str  # "draft" | "review"
    failed: list[dict]  # described checks (reasons.describe)
    blocking: list[str]  # codes that can't be overridden
    overridable: list[str]  # codes that can be approved with a reason
    po: PoSnapshot | None
    already_drafted: dict | None = None

    @property
    def can_approve(self) -> bool:
        return not self.blocking and self.already_drafted is None

    @property
    def needs_reason(self) -> bool:
        return bool(self.overridable)


def _refs(client: OdooClient) -> OdooRefs:
    company = client.buyer_company()
    return OdooRefs(company_ice=company["ice"], suppliers=client.suppliers())


def recheck(
    case: ReviewCase, edits: list[FieldEdit], client: OdooClient, cfg: MatchConfig
) -> tuple[Outcome, CaseDocs, list]:
    """Run the pipeline's checks on the corrected documents against live Odoo data."""
    docs = corrected_docs(case, edits)
    refs = _refs(client)
    po_ref = po_ref_of(docs.invoice, docs.bl)
    po = client.po_snapshot(po_ref) if po_ref else None
    partner_id = supplier_partner_id(docs.invoice, refs)
    known = odoo_known(client, partner_id, docs.invoice)
    session = object_session(case)
    if session is not None:
        known += known_cases(session, docs.invoice, exclude_case_id=case.id)
    ev = evaluate(docs.invoice, docs.bl, po, refs, cfg, known)
    failed = [c for c in ev.checks if not c.ok]
    codes = sorted({c.code for c in failed})
    existing = None
    if partner_id and docs.invoice.number.value:
        bills = client.find_bill(partner_id, docs.invoice.number.value)
        existing = bills[0] if bills else None
    outcome = Outcome(
        action=ev.decision.action,
        failed=[describe(c) for c in failed],
        blocking=[c for c in codes if c not in OVERRIDABLE],
        overridable=[c for c in codes if c in OVERRIDABLE],
        po=po,
        already_drafted=existing,
    )
    return outcome, docs, ev.pairs


# --- approve / reject -------------------------------------------------------------------


def source_file(path_str: str | None) -> Path | None:
    """Stored path (relative to the repo, as the CLI got it) -> absolute path under data/."""
    if not path_str:
        return None
    p = Path(path_str.replace("\\", "/"))
    p = (p if p.is_absolute() else REPO_ROOT / p).resolve()
    if not p.is_relative_to(DATA_DIR.resolve()):
        raise ReviewError(f"source file outside data/: {path_str}")
    return p


def _lock_open(session: Session, case_id: int) -> ReviewCase:
    case = session.scalars(
        select(ReviewCase).where(ReviewCase.id == case_id).with_for_update()
    ).one_or_none()
    if case is None:
        raise LookupError(case_id)
    if case.status != CaseStatus.open:
        raise Conflict(f"case #{case_id} is already {case.status.value}")
    return case


def _log_corrections(
    session: Session, case: ReviewCase, edits: list[FieldEdit], reviewer: str
) -> list[Correction]:
    """One row per value that actually changed: the labelled data."""
    rows = []
    for e in edits:
        original = case.invoice if e.doc == "invoice" else case.bl
        try:
            container, key = _walk(original, e.path.split("."))
            old = container[key]
        except (KeyError, IndexError, ValueError, TypeError):
            old = None
        old_value = old.get("value") if isinstance(old, dict) else None
        if old_value is not None and str(old_value) == str(e.value):
            continue
        rows.append(
            Correction(
                case=case,
                doc=e.doc,
                field_path=e.path,
                old_value=old_value,
                new_value=e.value,
                old_confidence=old.get("confidence") if isinstance(old, dict) else None,
                source=old.get("source") if isinstance(old, dict) else None,
                reviewer=reviewer,
            )
        )
    session.add_all(rows)
    return rows


@dataclass
class Approval:
    bill: dict
    corrections: int
    overridden: list[str]
    note_error: str | None = None
    warnings: list[str] = field(default_factory=list)


def approve(
    session: Session,
    case_id: int,
    edits: list[FieldEdit],
    reason: str | None,
    reviewer: str,
    client: OdooClient,
    cfg: MatchConfig,
) -> Approval:
    """Corrections -> re-check -> draft bill in Odoo -> audit rows. One transaction; the row
    lock makes a double click create one bill, and Odoo's own duplicate check is re-run."""
    case = _lock_open(session, case_id)
    outcome, docs, pairs = recheck(case, edits, client, cfg)
    if outcome.already_drafted:
        b = outcome.already_drafted
        raise Conflict(f"Odoo already has bill {b['name'] or b['id']} with this reference")
    if outcome.blocking:
        raise ReviewError(
            "these checks still fail and cannot be overridden: " + ", ".join(outcome.blocking),
            outcome.failed,
        )
    reason = (reason or "").strip() or None
    if outcome.overridable and (not reason or len(reason) < MIN_REASON_CHARS):
        raise ReviewError(
            f"approving over {', '.join(outcome.overridable)} needs a reason "
            f"(at least {MIN_REASON_CHARS} characters)",
            outcome.failed,
        )
    files = [f for f in (source_file(case.invoice_file), source_file(case.bl_file)) if f]
    bill, failure = create_checked_draft(client, outcome.po, docs.invoice, pairs, files)
    if failure:
        raise ReviewError("Odoo's totals differ from the invoice", [describe(failure)])

    rows = _log_corrections(session, case, edits, reviewer)
    now = datetime.now(UTC)
    session.add(
        ReviewAction(
            case=case,
            action=ActionKind.approve,
            reviewer=reviewer,
            reason=reason,
            overridden_codes=outcome.overridable,
            odoo_bill_id=bill["id"],
            odoo_bill_name=bill.get("name") or None,
        )
    )
    case.status = CaseStatus.approved
    case.decided_at = now
    session.flush()
    result = Approval(bill=bill, corrections=len(rows), overridden=outcome.overridable)
    try:
        client.add_internal_note(
            "account.move", bill["id"], _note_html(case, rows, reason, reviewer)
        )
    except Exception as exc:  # noqa: BLE001 (the bill and the audit rows are what matter)
        result.note_error = str(exc)
    return result


def reject(
    session: Session,
    case_id: int,
    edits: list[FieldEdit],
    reason: str,
    reviewer: str,
) -> int:
    """Close the case without a bill (e.g. short delivery: ask for a credit note)."""
    reason = (reason or "").strip()
    if len(reason) < MIN_REASON_CHARS:
        raise ReviewError(f"a rejection needs a reason (at least {MIN_REASON_CHARS} characters)")
    case = _lock_open(session, case_id)
    corrected_docs(case, edits)  # refuse invalid corrections before logging them
    rows = _log_corrections(session, case, edits, reviewer)
    session.add(ReviewAction(case=case, action=ActionKind.reject, reviewer=reviewer, reason=reason))
    case.status = CaseStatus.rejected
    case.decided_at = datetime.now(UTC)
    session.flush()
    return len(rows)


def _note_html(case: ReviewCase, rows: list[Correction], reason: str | None, reviewer: str) -> str:
    """Chatter note on the draft bill: who approved it, what they changed and why."""
    e = html.escape
    parts = [
        f"<p><b>trimatch review case #{case.id}</b> approved by {e(reviewer)}.</p>",
        f"<p>Flagged: {e(', '.join(case.reason_codes))}.</p>",
    ]
    if reason:
        parts.append(f"<p>Reason: {e(reason)}</p>")
    if rows:
        items = "".join(
            f"<li>{e(r.doc)} {e(r.field_path)}: {e(str(r.old_value))} → {e(str(r.new_value))}"
            f"{_box(r.source)}</li>"
            for r in rows
        )
        parts.append(f"<p>Corrections:</p><ul>{items}</ul>")
    return "".join(parts)


def _box(source: dict | None) -> str:
    if not source:
        return ""
    return f" (page {source.get('page')}, box {source.get('x0'):.3f},{source.get('y0'):.3f})"
