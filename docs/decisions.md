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
