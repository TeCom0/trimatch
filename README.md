# trimatch

Reads Moroccan supplier paperwork (delivery notes and invoices: scans, photos, later UBL e-invoices), reconciles them against the purchase order and the goods receipt in Odoo (three-way match), and creates **draft** vendor bills. Uncertain cases go to a human review queue. Nothing is ever posted or paid automatically.

**Status:** Phase 0 (vertical slice) in progress. See [docs/SPEC.md](docs/SPEC.md) and [docs/progress.md](docs/progress.md).

## Results

No results yet. Every number in this README will link to a dated file in `eval/results/` produced by `eval/run.py` on a stated test set and commit.

## Data

All documents in this repo are synthetic. Company names and ICE numbers are fictitious. `data/` is gitignored.
