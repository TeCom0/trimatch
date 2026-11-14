# Build step 3: validate, match, decide, draft bill in Odoo (plan)

Status: APPROVED 2026-11-14, built the same day. Covers SPEC section 9, items 3 and 4, with ground-truth labels standing in for the extractor. Gemini extraction is step 4.

## Why labels first

The back half of the pipeline (validation, matching, decision, Odoo) is deterministic. With a **label extractor** that returns the generator's ground truth, `trimatch process` on the e2e documents must give exactly the decisions in SPEC section 4. That proves the back half alone. When Gemini comes in at step 4, any new error is an extraction error, which is easy to tell apart.

## Odoo 20 facts (read from the pinned image's source, 2026-11-14)

| Fact | Source | Consequence |
|---|---|---|
| `purchase.order.action_create_invoice(attachment_ids=False)` builds one draft `in_invoice` from the PO lines, quantity = `qty_to_invoice` (received − billed, since our products use `purchase_method='receive'`). Each bill line keeps `purchase_line_id`. | `addons/purchase/models/purchase_order.py:820` | We call it over JSON-2, then set each bill line's quantity and price to the invoice's values (paired by `purchase_line_id`) and drop PO lines the invoice doesn't bill. Odoo's own bill control stays linked. |
| Passing `attachment_ids` runs `_extend_with_attachments`, which tries to decode the file into the bill (Odoo's import logic). | same file, l. 885 | We **don't** pass the PDF there. We create the `ir.attachment` ourselves on the bill afterwards, so our extracted values are the only ones on the bill. |
| `qty_invoiced` counts bill lines of every non-cancelled move, drafts included. | `purchase_order_line.py:_compute_qty_invoiced` | Re-running would see the qty as already billed. So the duplicate check (supplier + invoice number) runs **before** matching. |
| `account.move.duplicated_ref_ids` flags other draft/posted bills with the same ref and partner. | `account_move.py:794, 2200` | Odoo's own duplicate warning works on our drafts too. |

## Flow of `trimatch process <files...>`

1. **Extract** each file through the `Extractor` interface. Now: `LabelExtractor` (reads `data/labels/<split>/<file stem>.json`). Step 4 adds `GeminiExtractor`. Selected with `--extractor labels|gemini`.
2. **Group** documents: an invoice and its BL go together when the invoice's `bl_refs` contains the BL number. Otherwise they're grouped by the same `po_ref` and supplier ICE. Copies of the same document (e.g. clean + degraded e2e copies) are processed once. Later copies are logged as `DUPLICATE_INPUT`.
3. **Already drafted?** If Odoo has a non-cancelled bill with the same supplier and `ref` = invoice number: skip (`ALREADY_DRAFTED`) and create nothing. This makes runs idempotent (SPEC 9.4).
4. **Validate** the invoice and the BL (SPEC 6, pure Python, Odoo data passed in).
5. **Match** against the PO snapshot from Odoo (SPEC 7).
6. **Decide**: draft only if every check passes and every required field has confidence ≥ 0.85.
7. **Draft**: `action_create_invoice` → set ref, invoice date and due date, align lines with the invoice → **safety check**: the bill's untaxed amount, tax and total must equal the invoice's within 0.01 MAD. If not, the bill we just created is deleted (it's our own draft, created seconds earlier) and the case goes to review with `BILL_TOTAL_MISMATCH`. Then attach the source PDF/JPG(s) as `ir.attachment`.
8. **Review entry** otherwise: `data/review/<supplier ICE>_<invoice no>.json` with the extracted data, every failed check with its details, the PO snapshot and the source file paths.
9. Print a summary table: document, PO, decision, reason codes, Odoo bill id.

`--dry-run` stops before step 7 and writes nothing to Odoo or `data/review/`. The eval uses it to score decisions per degradation without creating bills.

## Checks and reason codes

From SPEC 6 and 7: `ICE_FORMAT`, `LINE_MATH`, `SUM_HT`, `VAT_RATE_KNOWN`, `VAT_MATH`, `SUM_TTC`, `SUPPLIER_KNOWN`, `CUSTOMER_IS_US`, `REQUIRED_PRESENT`, `PO_NOT_FOUND`, `LINE_UNMATCHED`, `QTY_EXCEEDS_RECEIVED`, `QTY_BL_MISMATCH`, `PRICE_OVER_TOLERANCE`, `LOW_CONFIDENCE`.

**New codes I propose (SPEC change):**
- `PO_SUPPLIER_MISMATCH`: the PO in Odoo belongs to another supplier than the invoice's ICE.
- `BL_MISSING`: an invoice arrives without a delivery note. A three-way match needs one, so it goes to review.
- `BILL_TOTAL_MISMATCH`: Odoo's computed totals differ from the invoice (step 7 safety check). It catches rounding or tax-mapping differences between our rules and Odoo's.
- `ALREADY_DRAFTED`, `DUPLICATE_INPUT`: skips, not reviews.

Quantity tolerances come from `config/matching.yaml`: `kg` uses 2%, every other unit 0. The price tolerance is 1%. The "received" quantity the invoice is checked against is `qty_received − qty_invoiced` of the PO line, so a second invoice can't bill the same goods twice.

## Code

```
backend/trimatch/
  extract/__init__.py    Extractor protocol + LabelExtractor
  validate.py            SPEC 6 rules -> list[Check(code, ok, detail)]
  match.py               PO lookup, line pairing (ref, then rapidfuzz >= 90), qty/price checks
  decide.py              checks + confidences -> Decision(draft | review | skip, reasons)
  config.py              loads config/matching.yaml and vat_rates.yaml
  odoo_adapter.py        + po_snapshot(name), find_bill(partner, ref), create_draft_bill(...),
                           attach(bill, files), delete_own_draft(bill)  (no post/pay method)
  cli.py                 `trimatch process` (typer), entry point in pyproject
odoo/reset_bills.py      odoo-shell script: removes the draft bills made by trimatch-bot, to replay the demo
backend/tests/           test_validate.py, test_match.py, test_decide.py (pure, run in CI)
                         test_odoo_e2e.py (marked `odoo`, needs the local Odoo; skipped in CI)
```

New dependencies (free): typer, rapidfuzz (MIT).

The bot user may need more Odoo rights to create bills from a PO and attachments (it has Purchase user + Billing). I'll find out by testing. If a group is missing, I'll add the smallest one and log it in decisions.md.

## Done when

1. `trimatch process data/synthetic/e2e/*_clean.pdf --extractor labels` creates 3 draft bills (PO-001, PO-003, PO-005) with the PDF attached, totals equal to the invoices, and state `draft`. It also writes 2 review entries: PO-002 with `QTY_EXCEEDS_RECEIVED`, PO-004 with `PRICE_OVER_TOLERANCE`.
2. Running it again creates nothing new (`ALREADY_DRAFTED` ×3, the 2 reviews rewritten).
3. `--dry-run` on all 20 e2e files gives the same decisions for the degraded copies as for the clean ones.
4. The unit tests for every reason code pass, and so does the live Odoo test.
5. I send you a screenshot of one draft bill in Odoo.

## Out of this step

Gemini extraction (step 4), eval script (step 5), CI wiring, review UI.
