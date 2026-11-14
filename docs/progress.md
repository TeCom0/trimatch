# Progress

Newest first. One entry per work session: date, what was done, what's next.

## 2026-11-14
- Build step 3 done (SPEC 9, items 3 and 4, with ground-truth labels as the extractor): validate.py, match.py, decide.py, pipeline.py, cli.py (`trimatch process`), adapter bill methods, odoo/reset_bills.py.
- Run on Youness's PC against the seeded Odoo: PO-001/003/005 -> draft bills with invoice + BL PDFs attached, totals equal to the invoices, Odoo shows "PO Matching 100%"; PO-002 -> review QTY_EXCEEDS_RECEIVED; PO-004 -> review PRICE_OVER_TOLERANCE. Second run: ALREADY_DRAFTED x3, no new bills. Dry run on the 10 degraded e2e copies gives the same decisions. 38 unit tests + 2 live Odoo tests pass.
- Found: Odoo 20 ir.attachment takes `raw`, not `datas`; "localhost" costs ~2 s per request on Windows (client now uses 127.0.0.1).
- Next: step 4 plan, Gemini extraction (free tier, synthetic docs only); needs a Gemini API key in .env.

## 2026-11-13
- Moroccan VAT verified against CGI 2026 (docs/research/vat-cgi-2026.md); config/vat_rates.yaml = 0/10/20.
- SPEC v0.2 approved (supplier 1 = Boucherie-Marée Al Waha, schema adds tp_number/payment_terms/exemption_ref).
- Build step 1 plan (docs/plan-step1-odoo.md) approved: Odoo 20 + postgres 16 in Docker, seed via `odoo shell`.
- Build step 1 done (SPEC 9, item 1): odoo/docker-compose.yml, odoo.conf, entrypoint.sh, seed.py, seed_data.yaml, backend/trimatch/odoo_adapter.py (`--check`). Tested on a fresh volume on Youness's PC: company + ICE, 3 suppliers, 15 products with exempt/10%/20% purchase taxes, PO-001..005 confirmed with receipts (PO-002 merlan 14/20 kg), bot user + rpc key; JSON-2 check prints CHECK OK; second seed run changes nothing.
- Build step 2 done (SPEC 9, item 2): `trimatch.generate` (data, render, degrade), schema.py, money.py, 15 unit tests passing. Generated e2e (20 docs), dev (200) and test (200) on Youness's PC; labels identical across two runs of the same seed; every printed field has a ground-truth box (checked visually on previews). Test split generated but never looked at beyond counts.
- Next: step 3 plan (validation, matching, decision, draft bill in Odoo).

## 2026-11-12
- Phase 0 interview done; docs/SPEC.md v0.1 approved.
- Repo skeleton created (folders, docs, config placeholders, .gitignore, Claude Code settings). No code yet.
- Next: verify item-level VAT rates against the official CGI 2026 (SPEC 4.1); then Odoo 20 in Docker + seed script.
