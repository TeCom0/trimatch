# Decisions

Format: date · decision · why · alternatives rejected. Newest first.

## 2026-11-12 (Phase 0 interview)
- **Name: trimatch.** Repo `TeCom0/trimatch`, folder `C:\dev\trimatch`. Says "three-way match" in English; renaming later is cheap.
- **Repo public from day one.** Visible history for recruiters; safety comes from gitignored `data/`, denied `.env`, synthetic data only.
- **No deadline, strict done-list.** Quality over speed; scope guard enforced by SPEC section 9.
- **ERP: Odoo 20 Community, self-hosted Docker, pinned dated tag; fallback 19.0.** Free (LGPL). Latest stable at decision time.
- **ERP API: JSON-2 only** (`/json/2/<model>/<method>`, bot user + API key). XML-RPC/JSON-RPC deprecated since 19 (removal date: docs say 20, third-party blogs say 22 for self-hosted; irrelevant since we don't use them).
- **Fake company: Casablanca hotel-restaurant group** with produce / beverages / cleaning suppliers. Different units and (expected) VAT treatments, realistic short deliveries. Rejected: building-materials distributor (uniform VAT, fewer interesting cases).
- **Slice extractor: Gemini Flash vision, free tier, synthetic docs only.** Fastest path end-to-end at zero cost; free-tier data may be used by Google, so real docs never go there. Local OCR + LLM (Ollama/Vulkan; RX 7600S not on official ROCm lists) comes in Phase 1 and is the only path allowed for real docs. Rejected for slice: local-first (driver risk before anything works).
- **No FastAPI or UI in the slice.** Package + CLI; API arrives with the review screen in Phase 1.
- **Short delivery and price change pulled into the slice** (brief had them in Phase 1). Without a mismatch the three-way match can't fail, so the demo proves nothing. Duplicate invoice stays in Phase 1.
- **VAT rates in config, not code.** Item-level rates unverified (secondary sources conflict, tax.gov.ma not machine-readable); must be checked against CGI 2026 by hand.

## 2026-11-13
- **VAT verified against CGI 2026** (docs/research/vat-cgi-2026.md): only 20%, 10% and exempt in 2026. Odoo 20's `l10n_ma` 7%/14% taxes are obsolete and not used.
- **Supplier 1 swapped from fresh fruit/veg to meat, fish and dairy.** The CGI exempts meat, fish and milk explicitly (art. 91-I-A), but has no exemption for fresh fruit/veg sold by a wholesaler, so their treatment is unclear. Result: every rate in the demo cites an article, and the three invoices cover exempt-only, 10%+20%, and exempt+20%.
- **Schema adds `tp_number`, `payment_terms`, `exemption_ref`** to cover art. 145-III mentions.
- **Seed runs inside the container via `odoo shell`, not over the API** (step 1 plan approved). The seed creates the bot's API key so it can't authenticate with it; the ORM gives idempotency and receipt validation. The pipeline still uses JSON-2 only.
- **PostgreSQL 16** (Odoo 20 `MIN_PG_VERSION = 16`, read from source).
- **Odoo image pinned to `odoo:20.0-20261112`** (newest dated 20.0 tag on Docker Hub on 2026-11-13).
- **Database created with `odoo db init trimatch --country MA` before installing modules.** Without a country, `account` installs the generic chart and `l10n_ma` is not applied to the company. Found while building step 1.
- **Seed reads `/mnt/trimatch/odoo/seed.py` inside the container** instead of `Get-Content | odoo shell`: PowerShell prepended a BOM that Python rejected. The repo is mounted read-only at `/mnt/trimatch`.
- **IF stored in the partner's `vat` field (Odoo 20 identifier `MA_TIN`), ICE in `additional_identifiers.MA_ICE`.** Odoo 20 dropped `company_registry` and computes `is_company` from the VAT/TIN. RC and TP stay in `odoo/seed_data.yaml` for the generator only.
- **Bot user groups: internal user, Purchase user, Billing.** Enough for reading POs/receipts over JSON-2; draft bill creation is tested in step 3.
- **Generator design (step 2 plan approved):** one French A4 HTML layout rendered with Playwright/Chromium; ground-truth boxes read from `data-field` elements after layout; degraded copies saved as JPEG 150 dpi q70; amount in words via num2words. Fonts Inter, Caveat (OFL) and Homemade Apple (Apache 2.0), bundled with licences.
- **RC split into number + city in seed_data.yaml** (`rc: "538902"`, `rc_city: Casablanca`), so the RC ground truth is the number only.
- **VAT breakdown includes an exempt row (rate 0, amount 0)** so Σ bases = total HT holds for VAT_MATH.

## 2026-11-14
- **Step 3 plan approved.** Back half proven with a label (oracle) extractor before Gemini. Bills are made with Odoo's `purchase.order.action_create_invoice`, then aligned to the invoice line by line; the PDF is attached afterwards (passing it to that action triggers Odoo's own import of the file).
- **New reason codes:** PO_SUPPLIER_MISMATCH, BL_MISSING, BILL_TOTAL_MISMATCH (Odoo totals vs invoice safety check; our own draft is deleted), plus ALREADY_DRAFTED as an idempotent skip. Added to SPEC 7.
- **Billable quantity = qty_received − qty_invoiced** (drafts count as invoiced in Odoo 20), so the duplicate check runs before matching.
- **Odoo client uses 127.0.0.1**, measured 21.8 s vs 1.3 s for 10 calls with "localhost" on Windows.
- **Bot user rights unchanged** (internal user, Purchase user, Billing): enough to create draft bills from POs and attachments.
- **Step 4 plan approved.** Default model gemini-3.5-flash-lite (larger free quota) for prompt work; gemini-3.8-flash (5 RPM / 20 RPD on Youness's project) kept for a final comparison. Model and limits in config/extract.yaml.
- **Gemini copies values as printed; Python parses them** (French numbers, dates, ICE, "TVA 20 %", "Exonéré"). A value that is printed but unparseable gets confidence 0, so it can never reach a draft.
- **Extractor refuses files outside data/synthetic/** (free-tier data may be used by Google).

## 2026-11-15
- **First reported result is Gemini 3.5 Flash Lite on the test split** (seed 2), run once on the prompt tuned on dev only. Test errors are counted in the report but not listed, so they can't leak into tuning.
- **Kept the I/l ambiguity** in supplier names as a real error instead of renaming the supplier to avoid it.
- **"No wrong draft" is the safety metric to watch** next to accuracy: misreads must end in review, never in a wrong draft bill.
- **Gemini calls run 4 in parallel** (config `max_parallel`), spaced by the rpm limit; brought the fresh-clone quickstart from 440 s to 271 s.
- **Odoo host port configurable (`ODOO_PORT`)**, so a second stack can run next to the demo one.

## 2026-11-16 (Phase 1 review screen plan approved)
- **Review store in PostgreSQL**: database `trimatch_review`, own login role `trimatch`, inside the Postgres 16 container Odoo already uses (port bound to 127.0.0.1:5442). SQLAlchemy 2 typed ORM, psycopg 3, Alembic. Rejected: SQLite (would be swapped later; the brief names PostgreSQL). Not named `trimatch`: that is Odoo's database.
- **`trimatch db init` writes a generated role password to `.env`** and resets the role to it on every run, so `.env` is the single source of truth; the value is never printed.
- **One code path for decisions**: `pipeline.evaluate()` is used by `trimatch process` and by the review API, so a re-check in the screen can't disagree with the CLI.
- **One case per supplier ICE + invoice number** (`case_key`); a new run refreshes an open case and never reopens an approved or rejected one.
- **Override rules (D2)**: after corrections, `PRICE_OVER_TOLERANCE`, `QTY_BL_MISMATCH` and `LOW_CONFIDENCE` may be overridden with a written reason; `QTY_EXCEEDS_RECEIVED` and validation failures are reject-only.
- **Reviewer identity from `.env` (`TRIMATCH_REVIEWER`)**, no login for the local demo (D3).

## 2026-11-16 (review screen front end)
- **Front end: Vite 8 + React 19 + TypeScript 7 (strict), oxlint**, as the official Vite react-ts template ships them today. **TanStack Query** for server state (caching, keep-previous-data while re-checking), **React Router** for two routes. No UI kit: plain CSS with light/dark variables.
- **API types are generated, not hand-written**: `trimatch openapi` writes frontend/openapi.json, openapi-typescript generates src/api/schema.d.ts, openapi-fetch gives a typed client. CI fails if either file is stale. openapi-typescript 7 needs the TypeScript 5 compiler API, so `npm run gen:api` runs it through `npx` pinned to typescript 5.9.3; the app itself type-checks with TS 7.
- **One process for the demo**: `trimatch serve` serves the built app and the API on 127.0.0.1:8000 (no CORS, no second server). Vite's dev server proxies /api for development.
- **Invoice lines as cards**, not a wide table: the right-hand pane is ~600 px, and a 7-column table needed horizontal scrolling that hid the totals and the PO comparison.

## 2026-11-16 (highlight boxes)
- **Boxes come from the PDF text layer, not from Gemini**, whenever the copied text is found there. Gemini's own boxes centred on the right value for 33.0% of test fields. Rejected: a constant offset correction (the error varies per page and by row), and asking Gemini for better boxes (no control, costs calls).
- **Ambiguity is resolved deterministically**: unique values anchor the page's shift and each table line's row; no thresholds were tuned on test.
- **A box that isn't read from the file is marked `approximate`** and drawn dashed, so the screen never presents an estimate as exact. This covers misreads (exactly where a reviewer looks) and scans until OCR word boxes exist.

