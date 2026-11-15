# trimatch

Reads Moroccan supplier paperwork (delivery notes and invoices: scans, photos, later UBL e-invoices), reconciles them against the purchase order and the goods receipt in Odoo (three-way match), and creates **draft** vendor bills. Uncertain cases go to a human review queue. Nothing is ever posted or paid automatically.

**Status:** Phase 0 (vertical slice) in progress. See [docs/SPEC.md](docs/SPEC.md) and [docs/progress.md](docs/progress.md).

## Results

First measured result, 2026-11-15: extraction with Gemini 3.5 Flash Lite (free tier) on the **held-out synthetic test set** (seed 2, 200 documents: 100 delivery notes + 100 invoices, each 40 clean and 160 degraded by rotation, blur, a stamp or handwriting). Code `7b4bdbc`, prompt `cadd85983cea`. Full report: [eval/results/2026-11-15_7b4bdbc_test_gemini-3.5-flash-lite.md](eval/results/2026-11-15_7b4bdbc_test_gemini-3.5-flash-lite.md).

| | Field accuracy | Document accuracy (every field right) |
|---|---|---|
| All 200 documents | 99.2% (7460/7520) | 86.5% (173/200) |
| Clean (40) | 99.9% | 97.5% |
| Rotated (40) | 98.1% | 85.0% |
| Blurred (40) | 99.6% | 90.0% |
| Stamped (40) | 98.8% | 77.5% |
| Handwritten quantities / notes (40) | 99.5% | 82.5% |

End to end against Odoo ([e2e report](eval/results/2026-11-15_7b4bdbc_e2e_gemini-3.5-flash-lite.md), the 5 seeded POs, clean and degraded sets, dry run): 8 of 10 decisions exactly as expected, **no wrong draft**. The 2 misses are clean cases sent to review because a misread number broke the VAT/total checks, which is the safe direction.

Caveats: synthetic documents from one layout, so these numbers say nothing yet about real supplier paperwork; that needs the Phase 1 real held-out set. LLM output varies between runs even at temperature 0.

## Data

All documents in this repo are synthetic. Company names and ICE numbers are fictitious. `data/` is gitignored.
