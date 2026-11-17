# Phase 1, item 2: duplicate-invoice scenario (plan)

Status: APPROVED 2026-11-17 (D1 as recommended), built the same day. Completes the planted errors of the brief (short delivery, price change, duplicate invoice).

## The problem today

- **Same invoice number sent twice** (a resend, a second scan): already handled. The second copy is skipped with `ALREADY_DRAFTED` before matching (SPEC 7), and Odoo's own `duplicated_ref_ids` warning also fires.
- **Same invoice with a new number** (a supplier re-issues it, or "duplicata" gets its own number): not detected as such. Odoo has already billed the received quantities through the first bill, so the copy fails `QTY_EXCEEDS_RECEIVED`. That stops it, but the reason misleads the reviewer: it says "billed more than received", and the reviewer may look for a missing receipt instead of a double billing. And if the first invoice is still waiting in review, nothing has been billed yet, so the copy can be drafted.

The risk to cover is paying the same goods twice under two invoice numbers.

## What gets built

1. **New reason code `DUPLICATE_SUSPECTED`** (not overridable): the invoice has the same supplier, the same total TTC (±0.01 MAD) and the same invoice date as one of:
   - an existing non-cancelled vendor bill in Odoo with a different reference, or
   - an invoice already handled earlier in the same run (this also covers `--dry-run`, where nothing reaches Odoo), or
   - an open or approved review case in the store.

   The detail names the match ("same supplier, total 2 484,60 and date 2026-11-08 as Odoo bill BILL/2026/11/0004, ref FA-HP-2026-0197"). Deterministic: no fuzzy matching, no LLM. Same supplier + same total + same date is a strong signal on its own; a false flag only costs a review, and the reviewer sees exactly why.
2. **Odoo adapter:** one search on `account.move` (supplier, `move_type=in_invoice`, state ≠ cancel, `invoice_date`, `amount_total`). Read only.
3. **Order of processing:** invoices in a run are handled by invoice date, then file name, so "the second one" is well defined: the later arrival gets flagged, the first can be drafted.
4. **Generator, e2e split:** PO-005 gets a re-issued copy of its invoice: same lines, totals, date and BL reference, a new number, and a "DUPLICATA" mention. Clean + one degraded variant, like every e2e document. Expected decision: review with `DUPLICATE_SUSPECTED` (plus `QTY_EXCEEDS_RECEIVED` when the original is already drafted in Odoo). The 5 existing scenarios and their files don't change. Only the 2 new files need Gemini: 2 free-tier calls, synthetic documents only.
5. **Review screen:** the reason gets a title and hint ("Possible double billing: compare with the bill named in the detail, then reject"). Reject-only.
6. **Tests:** unit tests for the rule (Odoo match, same-run match, store match; a different total or date is not flagged; a cancelled bill is ignored), a live Odoo e2e check, and the e2e eval's expected-decision table extended.
7. **Measured:** a new dated e2e report (`eval.run --split e2e`). The README and the CV only quote that report.

## Out of scope

Fuzzy duplicates (a different total because one line changed, a different date): that's a judgement call, the "ambiguous cases" agent of the brief. Duplicate BLs on their own (a BL creates no bill).

## Decision for Youness

- **D1. Match rule.** *Recommended:* same supplier + same total TTC + same invoice date, as above. Alternative: also require the same PO reference. It's stricter, but it misses a copy re-issued against a different PO by mistake, which is exactly the case to catch.
