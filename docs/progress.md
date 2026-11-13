# Progress

Newest first. One entry per work session: date, what was done, what's next.

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
