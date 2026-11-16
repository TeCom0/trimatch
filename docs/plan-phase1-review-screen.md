# Phase 1, item 1: review screen (plan)

Status: APPROVED 2026-11-16 (D1-D3 as recommended). Covers the "Review screen" line of the brief (section 3) and the Phase 1 FastAPI + React items of SPEC section 2.

## Goal

A person opens the queue of documents the pipeline sent to review, sees the invoice and its delivery note with every extracted value highlighted where it was read, sees why the case was flagged, fixes a misread value or accepts/rejects the case, and on approval gets a **draft** vendor bill in Odoo. Every correction is stored as labelled data, and every value on an approved bill can be traced to a document, page, box and the person who approved it.

Demo story it must support (all three exist today with Gemini on the e2e set):
1. **Misread** (PO-003 on the fresh clone: VAT base 2 204,00 read as 2 204,04 → `VAT_MATH`). The reviewer clicks the highlighted base, sees the crop, types 2204.00, the checks re-run and pass, Approve → draft bill.
2. **Price change** (PO-004, `PRICE_OVER_TOLERANCE` +8%). Nothing is misread; the reviewer either accepts the new price with a written reason (→ draft) or rejects (dispute with the supplier).
3. **Short delivery** (PO-002, `QTY_EXCEEDS_RECEIVED`). The supplier billed goods we did not receive. Reject only (ask for a credit note); see decision D2.

## What gets built

### Back end (`backend/trimatch/api/`, FastAPI)
- **Store.** A `review` table (one row per flagged invoice+BL group: status `open | approved | rejected`, reason codes, extracted invoice/BL JSON, PO snapshot, file paths, timestamps), a `correction` table (review id, document, field path, old value, old confidence, source box, new value, reviewer, time) and an `approval` table (review id, action, reviewer, override reason, Odoo bill id, time). The pipeline writes new review cases to the store instead of `data/review/*.json`; a one-off command imports the existing JSON files. Database: see D1.
- **Re-check is the same code.** I split `pipeline.process_group` into a pure `evaluate(invoice, bl, po, refs, cfg) -> (checks, pairs)` and the Odoo side effects. The API calls `evaluate` on the corrected documents, so the screen and the CLI can never disagree. Corrected fields get confidence 1.0 and keep their original box.
- **Endpoints:**
  - `GET /api/reviews?status=open`: queue (supplier, invoice number, PO, reason codes, age).
  - `GET /api/reviews/{id}`: full case: both documents, failed checks with details, PO snapshot, corrections so far.
  - `GET /api/reviews/{id}/pages/{doc}/{n}.png`: page image. PDFs rasterised with pypdfium2 (already a dependency), JPEGs served as is. Only files under `data/` are served.
  - `POST /api/reviews/{id}/recheck` with corrections: runs `evaluate`, returns the new checks. Writes nothing.
  - `POST /api/reviews/{id}/approve` with corrections and an optional override reason: logs corrections, re-checks, then creates the draft bill with the existing adapter path (same `BILL_TOTAL_MISMATCH` safety check, same attachments, same `ALREADY_DRAFTED` guard). Refused if a non-overridable check still fails.
  - `POST /api/reviews/{id}/reject` with a reason.
- **Audit in Odoo too:** on approval, a chatter note on the draft bill (`message_post`, a note, not an email) with the reviewer, corrections and override reason. Nothing is posted or paid; the adapter still has no posting method.
- **Labelled data export:** `trimatch corrections export` writes `data/labels/corrections.jsonl` (gitignored) for later extractor work.

### Front end (`frontend/`, Vite + React + TypeScript)
- **Queue page:** table of open cases with reason-code chips.
- **Case page:** left, the document viewer (invoice / BL tabs, page image with an overlay box per extracted field; boxes on failing fields in red, low-confidence fields in amber). Right, the form grouped as header, lines, VAT, totals; clicking a field scrolls the viewer to its box and vice versa. Top, the failed checks in plain words with their details (e.g. "ANF-HT05: invoiced 99.36, PO price 92 (+8.0% vs 1.0% allowed)"). Editing a field re-runs the checks live through `/recheck`. Buttons: **Approve → draft bill** (enabled when checks pass, or when only overridable codes remain and a reason is typed), **Reject**.
- No UI library beyond React; plain CSS. Data fetching with `fetch` + a small hook.

### Tests and CI
- pytest: store, import, `evaluate` parity with the old `process_group` (the existing matching tests keep passing), API tests with FastAPI's TestClient and a fake Odoo client (approve creates exactly one draft, refused approve creates none, corrections logged, path guard on page images).
- Vitest + Testing Library: overlay box placement, approve-button rules.
- CI: add a `frontend` job (npm ci, tsc, vitest, build). Back-end job unchanged except for the new tests.

### Measured, not claimed
The store records when a case was opened and decided, so a later report can give time per review on the demo set. No number goes into the README until it is measured that way.

## Build order (one branch and PR each, merge when CI is green)
1. `evaluate` refactor + store + import + pipeline writes to the store. CLI behaviour unchanged.
2. FastAPI endpoints + Odoo chatter note + tests.
3. React queue + case page, CI frontend job.
4. Demo pass on Youness's PC: e2e with Gemini against a fresh Odoo, resolve the three cases above in the screen, screenshots + a short GIF for the README, `docs/progress.md` and `docs/decisions.md` updated.

## Out of scope for this item
Login/auth (reviewer name comes from config, see D3), uploading documents from the UI, email intake, the LangGraph agent, duplicate-invoice scenario, UBL, deployment, Arabic. Each is its own Phase 1 or later item.

## Decisions for Youness
- **D1. Database.** *Recommended: PostgreSQL*, a second database `trimatch_review` (role `trimatch`) in the Postgres 16 container that Odoo already runs (no new service), SQLAlchemy 2 + psycopg 3, Alembic for migrations. Matches the brief's stack and costs nothing. CI gets a Postgres service container. Alternative: SQLite file in `data/`, simpler but a stack I'd swap later anyway.
- **D2. Override rules.** *Recommended:* the reviewer can fix any extracted value. After fixes, `PRICE_OVER_TOLERANCE`, `QTY_BL_MISMATCH` and `LOW_CONFIDENCE` can be overridden with a written reason. `QTY_EXCEEDS_RECEIVED` cannot: Odoo bills received quantities, so the only correct answers are reject (ask for a credit note) or a later receipt in Odoo. Validation failures (`VAT_MATH`, `SUM_TTC`, `ICE_FORMAT`...) can't be overridden either: if the document really doesn't add up, it's rejected.
- **D3. Reviewer identity.** *Recommended:* a reviewer name in `.env` (`TRIMATCH_REVIEWER`), shown in the header and written to every correction and approval. Real login is out of scope for a local demo.
