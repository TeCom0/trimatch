# trimatch: Phase 0 spec (vertical slice)

Status: APPROVED v0.1, 2026-11-12. Source of truth for intent: PROJECT_BRIEF.md (v2). This file defines what Phase 0 builds and how it is judged. Changes go through docs/decisions.md.

## 1. Goal of the slice

One command takes a French delivery note (bon de livraison, BL) and supplier invoice for a purchase order that exists in Odoo. It reads both, checks them, matches them against the PO and the receipt in Odoo, and then does one of two things:

- creates a **draft** vendor bill in Odoo with the source PDF attached, or
- writes a review-queue entry that says exactly why it did not.

Nothing is posted or paid. The slice proves the full chain works and produces a first measured, dated result.

## 2. Scope

### In
- Odoo 20 Community in Docker, seeded with a fake company (section 4).
- Synthetic document generator: one French layout, three supplier brandings, BL + invoice per PO, plus degraded copies.
- Extraction through an `Extractor` interface, with one implementation: a Gemini Flash vision model on the **free tier** (synthetic documents only).
- Deterministic validation and three-way matching (pure Python).
- Decision step plus an Odoo adapter that creates draft bills through the JSON-2 API.
- CLI: `trimatch process <files...>`.
- Three scenarios: clean match, short delivery, price change.
- Eval script and a dated results table.
- Unit tests and GitHub Actions CI.

### Out (Phase 1 or later)
FastAPI server, review UI, duplicate-invoice scenario, UBL e-invoice input, local OCR/LLM extractor and the extractor comparison, real documents, deposits/consignes, Arabic, phone photos, email intake, LangGraph agent for ambiguous cases, deployment.

**Scope rule:** nothing from "Out" starts until every item in section 9 is done.

## 3. Tooling

| Area | Choice | Note |
|---|---|---|
| ERP | Odoo 20 Community, official Docker image pinned to a dated tag (e.g. `20.0-YYYYMMDD`) | Fallback: 19.0. Free (LGPL, self-hosted). |
| ERP API | JSON-2 (`POST /json/2/<model>/<method>`), bearer API key of a dedicated bot user | XML-RPC/JSON-RPC are deprecated since 19; not used. |
| Language | Python 3.12, `uv` for env + lockfile | |
| Libraries | pydantic v2 (schema), httpx (Odoo), typer (CLI), google-genai (Gemini), Jinja2 + Playwright (render PDFs), pypdfium2 + Pillow/OpenCV (rasterise + degrade), python-stdnum (ICE), pytest, ruff | All free. |
| CI | GitHub Actions: ruff + pytest (unit tests only, no Odoo, no Gemini) | |

Secrets (`GEMINI_API_KEY`, `ODOO_API_KEY`) live in `.env`. That file is gitignored and denied to Claude Code.

## 4. Fake company

All names are fictitious. ICEs are generated as valid 15-digit numbers (mod 97 check) with the enterprise part starting with `999` so they read as synthetic. Before seeding, we check that none of them appears in a public ICE lookup.

**Buyer:** *Riad Atlas Hospitality SARL*, Casablanca. A hotel-restaurant group with one warehouse (`WH`) in Odoo.

| Supplier | Category | Units | VAT (to verify, see 4.1) |
|---|---|---|---|
| Primeurs Al Waha SARL | Fresh produce | kg, botte | exempt (expected) |
| Distribution Boissons Anfa SARL | Beverages | pack, carton | 10% water, 20% other (expected) |
| HygiPro Maroc SARL | Cleaning and hygiene | unit, carton, rouleau | 20% (expected) |

**Products (15):**
- Produce: tomates (kg), pommes de terre (kg), oignons (kg), oranges (kg), menthe (botte)
- Beverages: eau minérale 1,5 L pack de 6; soda 33 cl carton de 24; jus d'orange 1 L carton de 12; eau gazeuse 1 L pack de 6; thé glacé 50 cl carton de 12
- Cleaning: liquide vaisselle 5 L, eau de javel 5 L, savon liquide mains 5 L, essuie-mains papier carton de 6, sacs poubelle 100 L rouleau de 10

**Purchase orders (5), all confirmed in Odoo:**

| PO | Supplier | Scenario | Receipt in Odoo | Invoice | Expected decision |
|---|---|---|---|---|---|
| PO-001 | Primeurs | clean | full | = received qty, PO price | draft |
| PO-002 | Primeurs | short delivery | partial (one line ~70%), BL shows the lower qty | bills the **ordered** qty | review: `QTY_EXCEEDS_RECEIVED` |
| PO-003 | Boissons | clean | full | = received, PO price | draft |
| PO-004 | Boissons | price change | full | one line +8% over PO price | review: `PRICE_OVER_TOLERANCE` |
| PO-005 | HygiPro | clean | full | = received, PO price | draft |

Seeding is idempotent: `odoo/seed.py` creates the company, the Moroccan chart of accounts/taxes (`l10n_ma`, to confirm in Odoo 20), partners with ICE, products, POs, confirmed receipts, and the bot user with its API key.

### 4.1 Facts still to verify against official text before the generator is written

Research on 2026-11-12 used secondary sources only (tax.gov.ma blocks automated reads):
- VAT: two rates from 1 Jan 2026, 20% and 10%, after 7% and 14% were folded in (LF 2024 reform). Sources conflict on sugar. **The item-level rates in the table above are unverified.** Rates live in `config/vat_rates.yaml`, so a correction needs no code change.
- ICE: 15 digits (9 enterprise + 4 establishment + 2 control). The whole number is ≡ 0 mod 97 (python-stdnum).
- Invoice mentions (CGI art. 145-III): supplier name, ICE, IF, RC, patente/TP, client name and ICE (B2B), number, date, goods description, qty, unit price, HT, VAT rate and amount, TTC, payment terms/method, exemption mention where relevant.
- E-invoicing (art. 145-IX): no implementing text published as of late Sept 2026 per one source. Irrelevant to the slice; UBL is Phase 1.

Action: Youness or I read the official CGI 2026 (PDF from tax.gov.ma, by hand) and record the result in `docs/research/`.

## 5. Extraction schema

One pydantic model per document type. Every extracted scalar is a `Field[T]`:

```python
class Box(BaseModel):
    page: int            # 1-based
    x0: float; y0: float; x1: float; y1: float   # normalised 0..1, origin top-left

class Field(BaseModel, Generic[T]):
    value: T | None
    confidence: float    # 0..1, from the extractor
    source: Box | None   # where the value was read
```

```python
class Party(BaseModel):
    name: Field[str]
    ice: Field[str]           # 15 digits, normalised (no spaces)
    if_number: Field[str] | None
    rc: Field[str] | None

class Line(BaseModel):
    description: Field[str]
    supplier_ref: Field[str] | None
    quantity: Field[Decimal]
    unit: Field[str] | None
    unit_price_ht: Field[Decimal] | None   # None on a BL without prices
    vat_rate: Field[Decimal] | None        # 0, 10, 20 (percent)
    line_total_ht: Field[Decimal] | None

class VatBreakdown(BaseModel):
    rate: Field[Decimal]
    base_ht: Field[Decimal]
    amount: Field[Decimal]

class DeliveryNote(BaseModel):
    doc_type: Literal["delivery_note"]
    supplier: Party
    customer: Party
    number: Field[str]
    date: Field[date]
    po_ref: Field[str] | None
    lines: list[Line]

class Invoice(BaseModel):
    doc_type: Literal["invoice"]
    supplier: Party
    customer: Party
    number: Field[str]
    date: Field[date]
    due_date: Field[date] | None
    po_ref: Field[str] | None
    bl_refs: list[Field[str]]
    currency: Literal["MAD"]
    lines: list[Line]
    total_ht: Field[Decimal]
    vat: list[VatBreakdown]
    total_ttc: Field[Decimal]
```

Money is `Decimal`, never float. Rounding: half-up to 0.01 MAD.

Classification in the slice: the extractor also returns `doc_type`. A separate classifier is Phase 1.

**Confidence caveat:** an LLM's self-reported confidence is not calibrated. The slice records it but does not trust it alone (see 7). Calibration is measured in Phase 1.

## 6. Validation (deterministic, `backend/trimatch/validate.py`)

Each rule returns `pass | fail` with a reason code.

| Code | Rule |
|---|---|
| `ICE_FORMAT` | supplier and customer ICE are 15 digits and pass mod 97 |
| `LINE_MATH` | qty × unit price = line total (±0.01) |
| `SUM_HT` | Σ line totals = total HT (±0.01) |
| `VAT_RATE_KNOWN` | each rate is in `vat_rates.yaml` |
| `VAT_MATH` | per rate: base × rate = amount (±0.01); Σ bases = total HT |
| `SUM_TTC` | HT + Σ VAT = TTC (±0.01) |
| `SUPPLIER_KNOWN` | supplier ICE matches exactly one Odoo partner |
| `CUSTOMER_IS_US` | customer ICE = the buyer company's ICE |
| `REQUIRED_PRESENT` | number, date, supplier ICE, totals are non-null |

## 7. Matching and decision (deterministic, `match.py`, `decide.py`)

1. **Find the PO:** by `po_ref` on the invoice, else on the BL. If there's none or it's ambiguous, send to review with `PO_NOT_FOUND` (agent resolution is Phase 1).
2. **Line pairing:** invoice line ↔ PO line ↔ BL line. First by supplier ref = product default code. Otherwise normalised description similarity (rapidfuzz ≥ 90), one-to-one, with the threshold in config. An unpaired line gives `LINE_UNMATCHED`.
3. **Per line:**
   - `QTY_EXCEEDS_RECEIVED`: invoice qty > Odoo received qty + tolerance (0 for countable units, 2% for kg)
   - `QTY_BL_MISMATCH`: BL qty ≠ Odoo received qty (beyond tolerance)
   - `PRICE_OVER_TOLERANCE`: |invoice price − PO price| / PO price > 1%
4. **Decide:** draft only if every validation and match check passes **and** every required field has confidence ≥ 0.85 (config). Otherwise review, with all reason codes.
5. **Draft creation:** `account.move` with `move_type='in_invoice'`, linked to the PO lines so Odoo's own bill control applies. The `ref` is the supplier invoice number, the invoice date is set, and the PDF is attached as `ir.attachment`. State stays draft. The adapter has no method that posts.
6. **Review queue (slice):** one JSON file per document in `data/review/` with extracted data, reason codes and the source file path. It becomes a DB table with the UI in Phase 1.

Tolerances live in `config/matching.yaml`.

Odoo specifics to confirm in Odoo 20 during build: the exact way to create a bill from a PO through the API (`action_create_invoice` on `purchase.order` vs building the move with `purchase_line_id`), and the Community bill-control setting (`purchase_method` = received quantities).

## 8. Eval protocol

**Data:** generated with fixed seeds and never edited by hand. The ground truth is the exact JSON the generator rendered.

| Split | Seed | Content | Use |
|---|---|---|---|
| `dev` | 1 | 20 BL+invoice pairs (random POs from the 15 products, the 3 suppliers) × {clean, rot, blur, stamp, handwriting} = 200 docs | prompt and threshold tuning |
| `test` | 2 | same recipe, different values = 200 docs | **held out**: run only for a reported result, never while tuning |
| `e2e` | 3 | the 5 seeded POs × {clean, one degraded} = 20 docs | end-to-end decision check against Odoo |

Degradations: rotation ±3–8°, Gaussian blur, a "REÇU" stamp over the text, handwriting font for quantities on the BL, JPEG compression at 150 dpi.

**Metrics (all printed per degradation and overall):**
- Field accuracy per field. Exact match after normalisation: numbers to 2 dp, dates ISO, strings casefolded with whitespace collapsed, ICE digits only.
- Line accuracy: share of ground-truth lines matched with all fields correct.
- Document accuracy: share of docs with every field correct.
- e2e: decision accuracy (draft vs review) and reason-code exact match against the expected table in section 4.
- Latency per doc (median, p95) and tokens per doc. Cost is 0 on the free tier, and we record tokens so a paid estimate is possible.

**Reporting:** `uv run python -m eval.run --split test` writes `eval/results/YYYY-MM-DD_<git-sha>_<split>.md` with the table, model name and version, prompt hash, seed and doc count. Only numbers from such a file may appear in the README or CV.

Gemini free-tier data may be used by Google. Only generated documents are ever sent.

## 9. Definition of done (all must hold)

1. `docker compose up` + `uv run python odoo/seed.py` on a fresh clone gives the company, suppliers, products, 5 POs and receipts (PO-002 partial).
2. `uv run python -m trimatch.generate --split e2e` produces the BL + invoice PDFs and degraded copies.
3. `trimatch process data/synthetic/e2e/*` creates 3 draft bills (PO-001/003/005) with PDFs attached, and 2 review entries with the expected reason codes.
4. Running it twice creates no duplicate drafts (idempotent on supplier + invoice number).
5. `eval.run --split test` produces a dated results file, committed.
6. `pytest` (validation, matching, decision, ICE, rounding) passes in GitHub Actions.
7. The README quickstart reproduces 1–3 in under 5 minutes, given Docker and a Gemini key.

## 10. Repo layout

```
trimatch/
  docs/        SPEC.md progress.md decisions.md research/
  odoo/        docker-compose.yml seed.py
  backend/     pyproject.toml  trimatch/{schema,extract,validate,match,decide,odoo_adapter,generate,cli}.py
  config/      vat_rates.yaml matching.yaml
  eval/        run.py  results/
  frontend/    (empty until Phase 1)
  data/        raw/ synthetic/ labels/ review/   <- gitignored
  .claude/     settings.json (deny .env, data/raw)
  .github/workflows/ci.yml
  .gitignore README.md .env.example
```

CLAUDE.md is created later in Claude Code with /init. The Stop hook that runs tests is added once tests exist.

## 11. Open questions (not blocking Phase 0)

- Source of 20–30 real anonymised documents for the Phase 1 held-out set, and who gives permission.
- Interview dates for target roles.
- Official CGI 2026 check of item-level VAT rates (section 4.1).
