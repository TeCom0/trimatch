"""Review API end to end against a fake Odoo and the test database.

The three cases of the demo story (plan-phase1-review-screen.md):
- PO-003 with a misread VAT base (VAT_MATH): fix the value, approve -> draft bill
- PO-004 price +8% (PRICE_OVER_TOLERANCE): approve only with a reason
- PO-002 short delivery (QTY_EXCEEDS_RECEIVED): cannot be approved, reject with a reason
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pypdfium2 as pdfium
import pytest
from conftest import CFG, make_entry, make_po
from fastapi.testclient import TestClient
from sqlalchemy import select

from trimatch import review
from trimatch.api import app as api_app
from trimatch.api import pages
from trimatch.match import PoSnapshot
from trimatch.odoo_adapter import OdooError
from trimatch.store.cases import upsert_case
from trimatch.store.models import Correction, ReviewAction

MISREAD_BASE = "0.04"  # PO-003's VAT base read 0.04 too high, as Gemini did on 2026-11-15


class FakeOdoo:
    """The OdooClient methods the review flow uses, recording what it was asked to do."""

    def __init__(self, seed, refs):
        self.seed, self.refs = seed, refs
        self.bills: list[dict] = []
        self.deleted: list[int] = []
        self.notes: list[tuple[int, str]] = []
        self.attachments: list[tuple[int, list[str]]] = []
        self.totals_off = Decimal(0)  # simulate Odoo computing different totals
        self.note_fails = False

    def buyer_company(self):
        return {"ice": self.refs.company_ice}

    def suppliers(self):
        return self.refs.suppliers

    def po_snapshot(self, name: str) -> PoSnapshot | None:
        try:
            return make_po(self.seed, name)
        except StopIteration:
            return None

    def find_bill(self, partner_id, ref):
        return [
            b
            for b in self.bills
            if b["partner_id"] == partner_id and b["ref"] == ref and b["id"] not in self.deleted
        ]

    def bills_like(self, partner_id, invoice_date, total):
        return [
            b
            for b in self.live_bills
            if b["partner_id"] == partner_id
            and b.get("invoice_date") == invoice_date
            and abs(Decimal(str(b["amount_total"])) - total) <= Decimal("0.01")
        ]

    def create_draft_bill(self, po, inv, pairs):
        vat = sum((v.amount.value for v in inv.vat), Decimal(0))
        bill = {
            "id": 500 + len(self.bills),
            "name": False,  # Odoo leaves draft bills unnamed
            "state": "draft",
            "partner_id": po.partner_id,
            "ref": inv.number.value,
            "invoice_date": inv.date.value,
            "amount_untaxed": float(inv.total_ht.value + self.totals_off),
            "amount_tax": float(vat),
            "amount_total": float(inv.total_ttc.value + self.totals_off),
        }
        self.bills.append(bill)
        return bill

    def delete_own_draft(self, bill_id):
        self.deleted.append(bill_id)

    def attach(self, model, res_id, files):
        self.attachments.append((res_id, [f.name for f in files]))
        return [900 + len(self.attachments)]

    def call(self, model, method, ids=None, **kw):
        assert method == "write", method  # message_main_attachment_id only
        return True

    def add_internal_note(self, model, res_id, body_html):
        if self.note_fails:
            raise OdooError("mail module down")
        self.notes.append((res_id, body_html))

    @property
    def live_bills(self):
        return [b for b in self.bills if b["id"] not in self.deleted]


def _pdf(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(595, 842)
    pdf.save(path)
    pdf.close()
    return path


@pytest.fixture
def world(clean_db, seed, e2e, refs, tmp_path, monkeypatch):
    """Three open cases with real (blank) PDFs under a temporary data/ directory."""
    data = tmp_path / "data"
    monkeypatch.setattr(review, "DATA_DIR", data)
    monkeypatch.setattr(pages, "CACHE_DIR", data / "cache" / "pages")
    ids = {}
    with clean_db.begin() as s:
        for po in ("PO-002", "PO-003", "PO-004"):
            inv = e2e[po, "invoice"].label
            if po == "PO-003":
                vat = [v.model_copy(deep=True) for v in inv.vat]
                vat[0].base_ht.value += Decimal(MISREAD_BASE)
                inv = inv.model_copy(update={"vat": vat})
            inv_path = _pdf(data / "synthetic" / f"{po}_invoice.pdf")
            bl_path = _pdf(data / "synthetic" / f"{po}_bl.pdf")
            entry = make_entry(seed, refs, po, inv, e2e[po, "bl"].label, inv_path, bl_path)
            ids[po] = upsert_case(s, entry).case_id
    odoo = FakeOdoo(seed, refs)
    app = api_app.create_app(
        sessions=clean_db, odoo=lambda: odoo, reviewer="Test Reviewer", cfg=CFG, frontend_dist=None
    )
    return TestClient(app), odoo, ids, clean_db


def _vat_fix(e2e):
    return {
        "doc": "invoice",
        "path": "vat.0.base_ht",
        "value": str(e2e["PO-003", "invoice"].label.vat[0].base_ht.value),
    }


# --- reading -----------------------------------------------------------------------------


def test_queue_and_meta(world):
    client, _, _ids, _ = world
    cases = client.get("/api/reviews").json()
    assert [c["po_ref"] for c in cases] == ["PO-002", "PO-003", "PO-004"]
    assert {c["po_ref"]: c["reason_codes"] for c in cases} == {
        "PO-002": ["QTY_EXCEEDS_RECEIVED"],
        "PO-003": ["VAT_MATH"],
        "PO-004": ["PRICE_OVER_TOLERANCE"],
    }
    meta = client.get("/api/meta").json()
    assert meta["reviewer"] == "Test Reviewer"
    assert meta["reasons"]["PRICE_OVER_TOLERANCE"]["overridable"] is True
    assert meta["reasons"]["QTY_EXCEEDS_RECEIVED"]["overridable"] is False
    assert client.get("/api/reviews", params={"status": "approved"}).json() == []


def test_case_detail(world):
    client, _, ids, _ = world
    d = client.get(f"/api/reviews/{ids['PO-004']}").json()
    assert d["documents"]["invoice"] == {
        "file_name": "PO-004_invoice.pdf",
        "media_type": "application/pdf",
        "pages": 1,
    }
    [reason] = d["reasons"]
    assert reason["code"] == "PRICE_OVER_TOLERANCE" and reason["overridable"]
    assert reason["fields"] == [f"lines.{reason['line']}.unit_price_ht"]
    assert "source" in d["invoice"]["number"]  # the box for highlighting (None in labels)
    assert d["odoo_po"]["name"] == "PO-004"
    assert d["first_opened_at"] is not None
    assert client.get("/api/reviews/999").status_code == 404


def test_page_images(world):
    client, _, ids, _ = world
    r = client.get(f"/api/reviews/{ids['PO-004']}/documents/bl/pages/1")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    again = client.get(f"/api/reviews/{ids['PO-004']}/documents/bl/pages/1")
    assert again.content == r.content  # served from the disk cache
    assert client.get(f"/api/reviews/{ids['PO-004']}/documents/bl/pages/2").status_code == 404


def test_files_outside_data_are_refused(world, tmp_path):
    client, _, ids, sessions = world
    outside = _pdf(tmp_path / "elsewhere" / "secret.pdf")
    with sessions.begin() as s:
        s.get(api_app.ReviewCase, ids["PO-004"]).invoice_file = str(outside)
    r = client.get(f"/api/reviews/{ids['PO-004']}/documents/invoice/pages/1")
    assert r.status_code == 422 and "outside data/" in r.json()["detail"]


# --- the misread case: fix one value, approve ------------------------------------------------


def test_recheck_shows_fix_working_and_writes_nothing(world, e2e):
    client, odoo, ids, sessions = world
    url = f"/api/reviews/{ids['PO-003']}/recheck"
    before = client.post(url, json={"edits": []}).json()
    assert before["action"] == "review" and before["blocking"] == ["VAT_MATH"]
    assert not before["can_approve"]
    assert "vat" in before["failed"][0]["fields"]
    after = client.post(url, json={"edits": [_vat_fix(e2e)]}).json()
    assert after["action"] == "draft" and after["failed"] == [] and after["can_approve"]
    assert after["po"]["name"] == "PO-003"
    assert odoo.bills == []
    with sessions() as s:
        assert s.scalars(select(Correction)).all() == []


def test_approve_misread_creates_one_draft_and_logs_the_correction(world, e2e):
    client, odoo, ids, sessions = world
    url = f"/api/reviews/{ids['PO-003']}/approve"
    r = client.post(url, json={"edits": [_vat_fix(e2e)]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["case"]["status"] == "approved" and body["corrections"] == 1
    assert body["bill"]["state"] == "draft" and body["overridden"] == []
    assert len(odoo.live_bills) == 1
    assert odoo.attachments == [(body["bill"]["id"], ["PO-003_invoice.pdf", "PO-003_bl.pdf"])]
    [(bill_id, note)] = odoo.notes
    assert bill_id == body["bill"]["id"] and "Test Reviewer" in note and "vat.0.base_ht" in note

    with sessions() as s:
        [c] = s.scalars(select(Correction)).all()
        original = e2e["PO-003", "invoice"].label.vat[0].base_ht
        assert (c.doc, c.field_path, c.reviewer) == ("invoice", "vat.0.base_ht", "Test Reviewer")
        assert Decimal(c.old_value) == original.value + Decimal(MISREAD_BASE)
        assert Decimal(c.new_value) == original.value
        assert c.old_confidence == original.confidence
        assert c.source == (original.source.model_dump() if original.source else None)
        [a] = s.scalars(select(ReviewAction)).all()
        assert (a.action.value, a.odoo_bill_id) == ("approve", body["bill"]["id"])

    # A double click, or a second tab: no second bill.
    again = client.post(url, json={"edits": [_vat_fix(e2e)]})
    assert again.status_code == 409 and len(odoo.live_bills) == 1
    detail = client.get(f"/api/reviews/{ids['PO-003']}").json()
    assert [c["field_path"] for c in detail["corrections"]] == ["vat.0.base_ht"]
    assert detail["actions"][0]["action"] == "approve"


def test_approve_without_fix_is_refused(world):
    client, odoo, ids, _ = world
    r = client.post(f"/api/reviews/{ids['PO-003']}/approve", json={"edits": []})
    assert r.status_code == 422
    assert "VAT_MATH" in r.json()["detail"] and r.json()["checks"][0]["code"] == "VAT_MATH"
    assert odoo.bills == []


def test_odoo_totals_mismatch_keeps_case_open(world, e2e):
    client, odoo, ids, sessions = world
    odoo.totals_off = Decimal("1.00")
    r = client.post(f"/api/reviews/{ids['PO-003']}/approve", json={"edits": [_vat_fix(e2e)]})
    assert r.status_code == 422 and r.json()["checks"][0]["code"] == "BILL_TOTAL_MISMATCH"
    assert odoo.live_bills == [] and len(odoo.deleted) == 1
    with sessions() as s:
        assert s.scalars(select(Correction)).all() == []
    assert client.get(f"/api/reviews/{ids['PO-003']}").json()["status"] == "open"


def test_note_failure_does_not_lose_the_approval(world, e2e):
    client, odoo, ids, _ = world
    odoo.note_fails = True
    r = client.post(f"/api/reviews/{ids['PO-003']}/approve", json={"edits": [_vat_fix(e2e)]})
    assert r.status_code == 200 and "mail module down" in r.json()["note_error"]
    assert r.json()["case"]["status"] == "approved"


def test_already_in_odoo_is_a_conflict(world, e2e):
    client, odoo, ids, _ = world
    odoo.bills.append({"id": 1, "name": "BILL/1", "state": "draft", "partner_id": 12, "ref": "x"})
    odoo.bills[0]["ref"] = e2e["PO-003", "invoice"].label.number.value
    r = client.post(f"/api/reviews/{ids['PO-003']}/approve", json={"edits": [_vat_fix(e2e)]})
    assert r.status_code == 409 and "BILL/1" in r.json()["detail"]


# --- price change: override with a reason --------------------------------------------------


def test_price_override_needs_a_reason(world):
    client, odoo, ids, sessions = world
    url = f"/api/reviews/{ids['PO-004']}/approve"
    check = client.post(f"/api/reviews/{ids['PO-004']}/recheck", json={}).json()
    assert check["overridable"] == ["PRICE_OVER_TOLERANCE"] and check["needs_reason"]
    assert check["can_approve"]
    for reason in (None, "", "ok"):
        r = client.post(url, json={"reason": reason})
        assert r.status_code == 422 and "needs a reason" in r.json()["detail"]
    r = client.post(url, json={"reason": "New price agreed by phone with Anfa on 9 Nov."})
    assert r.status_code == 200 and r.json()["overridden"] == ["PRICE_OVER_TOLERANCE"]
    with sessions() as s:
        [a] = s.scalars(select(ReviewAction)).all()
        assert a.overridden_codes == ["PRICE_OVER_TOLERANCE"] and "phone" in a.reason
    assert "New price agreed" in odoo.notes[0][1]


# --- short delivery: reject only --------------------------------------------------------------


def test_short_delivery_cannot_be_approved_and_is_rejected(world):
    client, odoo, ids, _sessions = world
    base = f"/api/reviews/{ids['PO-002']}"
    r = client.post(f"{base}/approve", json={"reason": "please just bill it anyway"})
    assert r.status_code == 422 and "QTY_EXCEEDS_RECEIVED" in r.json()["detail"]
    assert client.post(f"{base}/reject", json={"reason": "no"}).status_code == 422
    r = client.post(f"{base}/reject", json={"reason": "Short delivery: credit note asked."})
    assert r.status_code == 200 and r.json()["case"]["status"] == "rejected"
    assert odoo.bills == []
    assert client.post(f"{base}/reject", json={"reason": "again, twice over"}).status_code == 409
    assert [c["po_ref"] for c in client.get("/api/reviews").json()] == ["PO-003", "PO-004"]


# --- bad input and failures ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "edit,message",
    [
        ({"doc": "invoice", "path": "lines.99.quantity", "value": "1"}, "no field"),
        ({"doc": "invoice", "path": "lines.-1.quantity", "value": "1"}, "no field"),
        ({"doc": "invoice", "path": "currency", "value": "EUR"}, "not an extracted value"),
        ({"doc": "invoice", "path": "lines.0.quantity", "value": "abc"}, "lines.0.quantity"),
        ({"doc": "invoice", "path": "date", "value": "31/02/2026"}, "date"),
    ],
)
def test_bad_edits_are_422(world, edit, message):
    client, _, ids, _ = world
    r = client.post(f"/api/reviews/{ids['PO-004']}/recheck", json={"edits": [edit]})
    assert r.status_code == 422 and message in r.json()["detail"]


def test_missing_optional_field_can_be_filled(world):
    client, _, ids, _ = world
    edit = {"doc": "invoice", "path": "lines.0.exemption_ref", "value": "art. 91-I-A-6°"}
    r = client.post(f"/api/reviews/{ids['PO-004']}/recheck", json={"edits": [edit]})
    assert r.status_code == 200


def test_odoo_down_is_502(world, seed, refs, clean_db):
    def down():
        raise httpx.ConnectError("refused")

    app = api_app.create_app(
        sessions=clean_db, odoo=down, reviewer="R", cfg=CFG, frontend_dist=None
    )
    client = TestClient(app)
    _, _, ids, _ = world
    r = client.post(f"/api/reviews/{ids['PO-004']}/recheck", json={})
    assert r.status_code == 502 and "not reachable" in r.json()["detail"]
    assert client.get(f"/api/reviews/{ids['PO-004']}").status_code == 200  # reading still works


def test_no_reviewer_configured(world, clean_db, seed, refs):
    app = api_app.create_app(
        sessions=clean_db,
        odoo=lambda: FakeOdoo(seed, refs),
        reviewer="",
        cfg=CFG,
        frontend_dist=None,
    )
    _, _, ids, _ = world
    r = TestClient(app).post(f"/api/reviews/{ids['PO-002']}/reject", json={"reason": "x" * 20})
    assert r.status_code == 422 and "TRIMATCH_REVIEWER" in r.json()["detail"]


def test_openapi_document(tmp_path):
    from typer.testing import CliRunner

    from trimatch.cli import app as cli

    out = tmp_path / "openapi.json"
    result = CliRunner().invoke(cli, ["openapi", str(out)])
    assert result.exit_code == 0, result.output
    import json

    spec = json.loads(out.read_text(encoding="utf-8"))
    assert "/api/reviews/{case_id}/approve" in spec["paths"]
    assert "CaseDetail" in spec["components"]["schemas"]
