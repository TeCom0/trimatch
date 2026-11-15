# Progress

Newest first. One entry per work session: date, what was done, what's next.

## 2026-11-15
- Step 5 (eval) done. `eval.run` writes dated reports; first reported result on the held-out test split (seed 2, 200 docs, gemini-3.5-flash-lite, code 7b4bdbc): field accuracy 99.2%, document accuracy 86.5%. e2e dry run: 8/10 decisions exact, 0 wrong drafts (2 clean cases flagged by VAT/total checks after a misread number). Reports in eval/results/, numbers in README.
- Fixes found on the way: retry dropped Gemini connections; quota counted per Pacific day; parser normalises RC numbers and CGI article references (from dev errors only; test errors not inspected).
- Known: "Al Waha" read as "AI Waha" (I/l look identical in Inter); harmless, suppliers are matched by ICE.
- Next: README quickstart (SPEC 9 item 7) and a demo run-through; then the slice is done.

## 2026-11-14
- Build step 3 done (SPEC 9, items 3 and 4, with ground-truth labels as the extractor): validate.py, match.py, decide.py, pipeline.py, cli.py (`trimatch process`), adapter bill methods, odoo/reset_bills.py.
- Run on Youness's PC against the seeded Odoo: PO-001/003/005 -> draft bills with invoice + BL PDFs attached, totals equal to the invoices, Odoo shows "PO Matching 100%"; PO-002 -> review QTY_EXCEEDS_RECEIVED; PO-004 -> review PRICE_OVER_TOLERANCE. Second run: ALREADY_DRAFTED x3, no new bills. Dry run on the 10 degraded e2e copies gives the same decisions. 38 unit tests + 2 live Odoo tests pass.
- Found: Odoo 20 ir.attachment takes `raw`, not `datas`; "localhost" costs ~2 s per request on Windows (client now uses 127.0.0.1).
- Step 4 (Gemini extraction) built: GeminiExtractor (structured JSON, values copied as printed and parsed in Python, boxes, self-reported confidence), disk cache, rate limit + daily budget, path guard (data/synthetic only), offline parse tests (59 unit tests pass).
- Free-tier limits read in AI Studio by Youness on 2026-11-14: Gemini 3.8 Flash 5 RPM / 20 RPD. Gemini 3.5 Flash Lite text-out limits not read yet (config holds a conservative guess).
- First e2e run on gemini-3.5-flash-lite (prompt cadd85983cea): 19 API calls, then 0 on re-run (cache). Debug comparison (not a reported result): after two parser fixes, 1 field differed from ground truth on 20 docs (an accent dropped on a blurred line description). `trimatch process` with Gemini on all 20 e2e files: 3 drafts (totals equal to invoices), PO-002 and PO-004 to review with the expected codes.
- Next: step 5 plan, eval.run on the held-out test split (200 docs; check whether the Flash Lite daily quota fits).

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
