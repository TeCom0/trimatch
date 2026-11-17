"""The e2e_ubl split (docs/plan-phase1-ubl.md): the e2e orders with their invoices as UBL 2.1
e-invoices and their delivery notes on paper, plus three planted bad e-invoices.

    uv run --project backend python -m trimatch.generate.ubl_split

Reads data/synthetic/e2e (generate it first). The BL files are copied byte for byte, so the
cached Gemini responses for them still apply; invoices are written from the ground truth.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from lxml import etree

from trimatch.config import REPO_ROOT
from trimatch.extract.ubl import NS, write_invoice
from trimatch.schema import Field, Invoice

SRC, DST = "e2e", "e2e_ubl"
OTHER_BUYER_ICE = "999801234000112"  # valid mod 97, synthetic (999 prefix), not the buyer's


def _f(value) -> Field:
    return Field(value=value, confidence=1.0)


def _renumber(inv: Invoice, add: int) -> Invoice:
    prefix, seq = inv.number.value.rsplit("-", 1)
    return inv.model_copy(update={"number": _f(f"{prefix}-{(int(seq) + add) % 10000:04d}")})


def planted(inv: Invoice) -> list[tuple[str, str, Invoice, bytes]]:
    """(key, scenario, ground truth, xml) for the three bad e-invoices, built on one clean
    invoice. Each gets its own number and, where needed, date, so it isn't also a duplicate."""
    out = []

    bad_schema = _renumber(inv, 101).model_copy(
        update={"date": _f(inv.date.value + timedelta(days=2))}
    )
    root = etree.fromstring(write_invoice(bad_schema))
    cur = root.find("cbc:DocumentCurrencyCode", NS)
    extra = etree.Element(f"{{{NS['cbc']}}}Remise")  # not a UBL element
    extra.text = "0.00"
    cur.addnext(extra)
    out.append(
        (
            "bad-schema",
            "ubl_invalid",
            bad_schema,
            etree.tostring(root, xml_declaration=True, encoding="UTF-8"),
        )
    )

    bad_total = _renumber(inv, 102).model_copy(
        update={"total_ttc": _f(inv.total_ttc.value + Decimal("10.00"))}
    )
    out.append(("bad-total", "ubl_bad_total", bad_total, write_invoice(bad_total)))

    customer = inv.customer.model_copy(update={"ice": _f(OTHER_BUYER_ICE)})
    bad_buyer = _renumber(inv, 103).model_copy(
        update={"customer": customer, "date": _f(inv.date.value + timedelta(days=1))}
    )
    out.append(("bad-buyer", "ubl_wrong_buyer", bad_buyer, write_invoice(bad_buyer)))
    return out


def main(root: Path = REPO_ROOT / "data") -> int:
    src_dir, src_labels = root / "synthetic" / SRC, root / "labels" / SRC
    manifest = json.loads((src_dir / "manifest.json").read_text(encoding="utf-8"))
    dst_dir, dst_labels = root / "synthetic" / DST, root / "labels" / DST
    for d in (dst_dir, dst_labels):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    docs = []
    base_for_planted = None
    for d in manifest["documents"]:
        if d["variant"] != "clean":
            continue
        stem = Path(d["file"]).stem
        label_json = (src_labels / f"{stem}.json").read_text(encoding="utf-8")
        if d["doc_type"] == "delivery_note":
            shutil.copy2(src_dir / d["file"], dst_dir / d["file"])
            (dst_labels / f"{stem}.json").write_text(label_json, encoding="utf-8")
            docs.append({**d, "doc_id": f"{DST}_{stem}"})
            continue
        inv = Invoice.model_validate_json(label_json)
        name = stem.replace("_clean", "_ubl") + ".xml"
        (dst_dir / name).write_bytes(write_invoice(inv))
        (dst_labels / f"{Path(name).stem}.json").write_text(label_json, encoding="utf-8")
        docs.append({**d, "doc_id": f"{DST}_{Path(name).stem}", "file": name, "variant": "ubl"})
        if d["po_ref"] == "PO-003" and d["scenario"] == "clean":
            base_for_planted = (inv, d)
    if base_for_planted is None:
        sys.exit("PO-003's clean invoice not found in the e2e manifest")
    inv, d = base_for_planted
    for key, scenario, truth, xml in planted(inv):
        name = f"{DST}_PO-003-{key}_invoice_ubl.xml"
        (dst_dir / name).write_bytes(xml)
        (dst_labels / f"{Path(name).stem}.json").write_text(
            truth.model_dump_json(indent=1), encoding="utf-8"
        )
        docs.append(
            {**d, "doc_id": Path(name).stem, "file": name, "variant": "ubl", "scenario": scenario}
        )
    out = {**manifest, "split": DST, "doc_count": len(docs), "documents": docs}
    (dst_dir / "manifest.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"Wrote {len(docs)} documents to {dst_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
