# Build step 2: synthetic document generator (plan)

Status: APPROVED 2026-11-13, built the same day. Covers SPEC section 9, item 2, and the data side of section 8. Nothing else.

## Goal

`uv run --project backend python -m trimatch.generate --split e2e` writes BL + invoice documents for the 5 seeded POs, plus degraded copies, and the exact ground-truth JSON for each document. `--split dev` and `--split test` write the extraction eval sets (SPEC 8). Same seed gives the same data every time.

## Inputs

- `odoo/seed_data.yaml` is the single source for the company, suppliers (with IF, RC, TP, payment terms), products, prices, VAT and the 5 POs. The e2e documents therefore match Odoo exactly, without querying Odoo.
- `config/vat_rates.yaml` for the allowed rates.

## Outputs (all under gitignored `data/`)

```
data/synthetic/<split>/<doc_id>.pdf | .jpg     the document the pipeline reads
data/labels/<split>/<doc_id>.json              ground truth: the SPEC 5 schema, confidence 1.0, real boxes
data/synthetic/<split>/manifest.json           doc_id, doc_type, PO, scenario, variant, seed, generator git sha
```

`doc_id` example: `e2e_PO-002_bl_clean`, `dev_0007_invoice_stamp`.

## Documents

One French A4 layout (Jinja2 HTML + CSS), rendered to PDF with Playwright (headless Chromium). Three brandings: colour, header font weight, and a simple text logo (initials in a shape; no real logos).

**Invoice** carries everything art. 145-III/VIII requires (docs/research/vat-cgi-2026.md): seller name and address, IF, TP, RC and ICE; buyer name, address and ICE; invoice number and date; BL and PO references; lines (ref, description, qty, unit, unit price HT, VAT rate, line total HT); exempt lines say "Exonéré – art. 91-I-A-x° CGI"; VAT breakdown per rate; total HT, total VAT, total TTC; payment terms and method; due date. Plus the usual Moroccan closing line "Arrêtée la présente facture à la somme de … dirhams TTC" (amount in words; needs the `num2words` package, LGPL, used as a library).

**Delivery note (BL)**: same header, BL number and date, PO ref, lines with ref, description, qty and unit, no prices. Footer with "Reçu par / signature / cachet" boxes.

**Money:** `Decimal`, half-up to 0.01. Line total = qty × price, rounded. VAT per rate = Σ bases of that rate × rate, rounded. TTC = HT + Σ VAT. These are the same rules `validate.py` will check, so a clean document always passes.

**Numbering and dates:** per supplier prefix, e.g. `BL-AW-2026-0412`, `FA-AW-2026-0398`. BL date = PO date + 1 to 2 days, invoice date = BL date + 0 to 3 days, due date from the supplier's payment terms. All drawn from the split's seed.

## Ground-truth boxes

Every value in the HTML is wrapped in an element with `data-field="lines.2.quantity"` and so on. After rendering, Playwright reads each element's bounding box from the page and normalises it to 0..1 (page size known). So the labels have real source boxes at no labelling cost, and step 4 can measure whether the extractor points at the right place. For rotated copies the boxes are rotated with the image (the box becomes the axis-aligned box around the rotated corners).

## Variants (SPEC 8)

| Variant | What | File |
|---|---|---|
| `clean` | vector PDF as rendered | .pdf |
| `rot` | rasterised at 150 dpi, rotated by ±3–8°, white fill | .jpg (quality 70) |
| `blur` | 150 dpi, Gaussian blur sigma 1.0–1.6 | .jpg |
| `stamp` | 150 dpi, a red/blue "REÇU" stamp with date, semi-transparent, placed over part of the line table | .jpg |
| `handwriting` | BL: quantities written in a handwriting font with small jitter in position and angle. Invoice: printed as normal plus a handwritten note ("Bon pour paiement", initials) near the totals, not covering any field | .jpg |

Raster: pypdfium2 renders the PDF, Pillow + OpenCV degrade it. Every random choice comes from the split's seed.

Fonts (bundled under `backend/trimatch/generate/fonts/` with their licence files): **Inter** (OFL 1.1) for print, **Caveat** (OFL 1.1) and **Homemade Apple** (Apache 2.0) for handwriting. Licences checked on github.com/google/fonts on 2026-11-13.

## Splits

| Split | Seed | Content | Count |
|---|---|---|---|
| `e2e` | 3 | the 5 seeded POs. Each gives a BL + invoice, clean + one degraded variant (rotating through rot/blur/stamp/handwriting) | 20 docs |
| `dev` | 1 | 20 random orders × {BL, invoice} × 5 variants | 200 docs |
| `test` | 2 | same recipe, different seed | 200 docs |

**e2e scenarios** follow SPEC section 4: PO-002 BL shows 14 kg merlan and the invoice bills the ordered 20 kg; PO-004 invoice bills ANF-HT05 at +8% (92.00 → 99.36). The other three match the PO and receipt exactly.

**dev/test random orders:** one supplier, 2–6 of its products, quantities by unit (kg in 0.5 steps from 5 to 60, countable 1 to 50), price = catalogue price ±10% so the extractor can't memorise prices. They don't exist in Odoo; they are for extraction accuracy only.

## Code

```
backend/trimatch/
  schema.py              SPEC 5 pydantic models (Box, Field, Party, Line, VatBreakdown, DeliveryNote, Invoice)
  money.py               Decimal rounding and the totals rules (shared with validate.py later)
  generate/
    __main__.py          CLI: --split e2e|dev|test [--out data/]
    data.py              builds the documents' data from seed_data.yaml + seed (pure Python, no I/O)
    render.py            Jinja2 → Playwright PDF + field boxes
    degrade.py           rasterise + variants
    templates/ invoice.html  bl.html  base.css
    fonts/               Inter, Caveat, Homemade Apple + licence files
backend/tests/
  test_money.py          rounding, VAT per rate, TTC
  test_generate_data.py  totals consistent; ICE valid; PO-002/PO-004 scenarios as in SPEC 4; same seed = same data
```

New dependencies (all free): pydantic, jinja2, playwright, pypdfium2, pillow, opencv-python-headless, num2words, pyyaml, python-stdnum; pytest and ruff as dev dependencies. Playwright needs a one-off `uv run playwright install chromium` (about 150 MB download).

## Done when

1. `--split e2e` writes 20 documents, 20 label files and a manifest. I send you PNG previews of one BL and one invoice (clean and degraded) to check by eye.
2. Each label file validates against `schema.py`, and its totals pass the money rules.
3. Two runs with the same seed give identical label files (the PDFs can differ in metadata bytes; the data can't).
4. `pytest` passes locally.

## Out of this step

Extraction, validation, matching, Odoo bill creation, CI wiring (step 6 of SPEC 9).

## Open points for Youness

- **num2words** for the amount in words: adds realism and one more field the extractor may read. Recommended. The alternative is to leave the line out.
- **Degraded files as JPEG** (scan-like) rather than image-in-PDF. Recommended, since real phone photos and scans arrive as JPEGs.
