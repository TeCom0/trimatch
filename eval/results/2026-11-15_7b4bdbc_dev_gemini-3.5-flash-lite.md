# Extraction eval: dev

| | |
|---|---|
| Date | 2026-11-15 |
| Code | `7b4bdbc` |
| Split / seed / documents | dev / 1 / 200 |
| Generator commit | `1cbcb5c` |
| Model | gemini-3.5-flash-lite (version reported: gemini-3.5-flash-lite) |
| Prompt hash | `cadd85983cea` |
| SDK | google-genai 3.3.0, Python 3.12.10 |
| API calls in this run | 0 (rest from cache) |
| Cost | 0 (free tier); tokens below allow a paid estimate |

## Overall

- Field accuracy: 99.5% (6520/6550)
- Line accuracy (every field of the line right): 99.0% (624/630)
- Document accuracy (every field right): 85.0% (170/200)

## By degradation

| Variant | Docs | Field acc. | Line acc. | Doc acc. |
|---|---|---|---|---|
| clean | 40 | 99.9% (1309/1310) | 100.0% (126/126) | 97.5% (39/40) |
| rot | 40 | 99.5% (1304/1310) | 100.0% (126/126) | 85.0% (34/40) |
| blur | 40 | 99.4% (1302/1310) | 96.8% (122/126) | 80.0% (32/40) |
| stamp | 40 | 99.3% (1301/1310) | 99.2% (125/126) | 77.5% (31/40) |
| handwriting | 40 | 99.5% (1304/1310) | 99.2% (125/126) | 85.0% (34/40) |

## By document type

| Type | Docs | Field acc. | Doc acc. |
|---|---|---|---|
| delivery_note | 100 | 99.2% (2243/2260) | 83.0% (83/100) |
| invoice | 100 | 99.7% (4277/4290) | 87.0% (87/100) |

## Per field

| Field | Accuracy |
|---|---|
| supplier.name | 88.5% (177/200) |
| lines.description | 99.4% (626/630) |
| customer.ice | 99.5% (199/200) |
| lines.quantity | 99.8% (629/630) |
| lines.unit | 99.8% (629/630) |
| bl_refs | 100.0% (100/100) |
| customer.name | 100.0% (200/200) |
| date | 100.0% (200/200) |
| due_date | 100.0% (100/100) |
| lines.exemption_ref | 100.0% (180/180) |
| lines.line_total_ht | 100.0% (315/315) |
| lines.supplier_ref | 100.0% (630/630) |
| lines.unit_price_ht | 100.0% (315/315) |
| lines.vat_rate | 100.0% (315/315) |
| number | 100.0% (200/200) |
| payment_terms | 100.0% (100/100) |
| po_ref | 100.0% (200/200) |
| supplier.ice | 100.0% (200/200) |
| supplier.if_number | 100.0% (200/200) |
| supplier.rc | 100.0% (200/200) |
| supplier.tp_number | 100.0% (200/200) |
| total_ht | 100.0% (100/100) |
| total_ttc | 100.0% (100/100) |
| vat.amount | 100.0% (135/135) |
| vat.base_ht | 100.0% (135/135) |
| vat.rate | 100.0% (135/135) |

## Latency and tokens per document

- Latency (recorded at call time): median 7.1 s, p95 44.7 s
- Input tokens: median 1568; output tokens (incl. thinking): median 2496

## Self-reported confidence vs correctness (descriptive, not calibrated)

| Confidence | Fields | Share right |
|---|---|---|
| [0.00, 0.50) | 2 | 0.0% |
| [0.50, 0.80) | 9 | 100.0% |
| [0.80, 0.90) | 31 | 96.8% |
| [0.90, 0.99) | 943 | 98.9% |
| [0.99, 1.00] | 5565 | 99.7% |

## Errors

- `dev_0001_bl_handwriting` lines.3.quantity: truth `11`, got `None`
- `dev_0002_bl_blur` lines.1.description: truth `Sacs poubelle 100 L, rouleau de 10`, got `Sacs poubelle 100 L., rouleau de 10`
- `dev_0002_invoice_rot` customer.ice: truth `999417302000177`, got `99941730200017`
- `dev_0003_invoice_stamp` supplier.name: truth `HygiPro Maroc SARL`, got `HegiPro Maroc SARL`
- `dev_0004_bl_rot` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0004_bl_blur` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0004_bl_handwriting` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0006_bl_blur` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0006_invoice_stamp` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0009_bl_clean` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0009_bl_rot` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0009_bl_blur` lines.3.description: truth `Sardines fraîches`, got `Sardines fraiches`
- `dev_0009_invoice_blur` lines.3.description: truth `Sardines fraîches`, got `Sardines fraiches`
- `dev_0009_invoice_stamp` lines.1.unit: truth `kg`, got `None`
- `dev_0010_bl_blur` lines.1.description: truth `Sardines fraîches`, got `Sardines fraiches`
- `dev_0010_bl_stamp` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0010_invoice_rot` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0010_invoice_blur` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0010_invoice_stamp` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0012_bl_stamp` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0012_bl_handwriting` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0012_invoice_rot` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0014_bl_handwriting` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0016_bl_stamp` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0016_bl_handwriting` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0017_bl_handwriting` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0017_invoice_blur` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0018_invoice_stamp` supplier.name: truth `HygiPro Maroc SARL`, got `HigiPro Maroc SARL`
- `dev_0019_invoice_rot` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Marée AI Waha SARL`
- `dev_0019_invoice_stamp` supplier.name: truth `Boucherie-Marée Al Waha SARL`, got `Boucherie-Maree Al Waha SARL`

Generated by `eval/run.py`. Metric definitions: docs/SPEC.md section 8.
