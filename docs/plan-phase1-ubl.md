# Phase 1, item 3: UBL e-invoice input (plan)

Status: DRAFT 2026-11-17, for Youness's approval.

## What we know about the Moroccan format (checked 2026-11-17)

- **Legal basis:** CGI art. 145-IX requires an invoicing system that meets the technical criteria the administration defines (already in SPEC 4.1).
- **No official technical specification is published.** No decree in the Bulletin Officiel and no schema on tax.gov.ma. In April 2026 the director of taxes said specifications would be published for software publishers ([Médias24, 2026-04-18](https://medias24.com/2026/04/18/la-facturation-electronique-expliquee-par-younes-idrissi-kaitouni-directeur-des-impots-1661379/)). Upsilon Consulting reported a draft implementing decree sent to the government's general secretariat in April 2026 ([Upsilon](https://upsilon-consulting.com/facturation-electronique-maroc-2026/)). A free portal for small companies, fatourati.gov.ma, is announced.
- **Format and model, secondary sources only:** clearance (CTC) through a DGI platform, UBL 2.1 or UN/CEFACT CII XML, buyer ICE required, electronic signature ([EDICOM](https://edicomgroup.com/blog/morocco-electronic-invoicing), [VATupdate, 2026-07](https://www.vatupdate.com/2026/07/02/briefing-document-podcast-e-invoicing-e-reporting-in-morocco/), [Sage Maroc](https://www.sage.com/fr-ma/blog/facturation-electronique-maroc-2026/)). These are vendor and consultancy blogs. They disagree on dates, thresholds and the platform's name (Simpl-TVA, xHub, fatourati). One says Morocco has not adopted EN 16931 or Peppol.

Consequence: we build against the **OASIS UBL 2.1 standard**. Everything Morocco-specific (where the ICE, IF, TP and RC go, how an exemption is coded) lives in one mapping file that we change when the DGI publishes its specification. We don't claim "DGI-compliant" anywhere.

## What gets built

1. **`UblExtractor`** (`extract/ubl.py`, lxml): parses a UBL 2.1 `Invoice` into the existing `schema.Invoice`. Values come from the XML, so confidence is 1.0. There is no page box; the source is the XML element path, shown in the review screen.
   - Validated against the official OASIS UBL 2.1 XSDs first. A file that fails is not guessed at: it goes to review with a new code `UBL_INVALID` and the schema errors.
   - Only the XML parser is used, with entity resolution and network access disabled (no XXE).
2. **Morocco mapping** (`config/ubl_ma.yaml`), our assumption until the DGI publishes one:
   - ICE in `cac:PartyLegalEntity/cbc:CompanyID` with `schemeID="ICE"`
   - IF, TP and RC in `cac:PartyIdentification/cbc:ID` with `schemeID` IF, TP and RC
   - exempt lines as tax category `E` with the CGI article in `cbc:TaxExemptionReason`
   - MAD amounts
3. **Routing by file type:** `.xml` goes to UBL and anything else goes to Gemini (`--extractor auto`, the new default). A UBL invoice matches against a paper BL (scan or PDF) and the Odoo PO and receipt. The rest of the pipeline doesn't change: the same validation (UBL arithmetic is checked too, since a structured file can still be wrong), matching, duplicate check and decision.
4. **Generator:** writes the e2e invoices also as UBL 2.1 XML from the same ground truth, into a new folder `data/synthetic/e2e_ubl/`. It also writes three planted bad files: one that fails the schema, one whose totals don't add up (`SUM_TTC`), and one with a wrong buyer ICE (`CUSTOMER_IS_US`).
5. **Review screen:** for an XML invoice, the left pane shows the parsed e-invoice as a readable document (seller, buyer, lines, VAT, totals), with each value's XML path on hover, instead of a page image. The BL stays as an image with its boxes.
6. **Tests and measurement:**
   - unit tests: parse round trip against the generator's ground truth, mapping, XSD failure, XXE refused
   - a live Odoo e2e run with UBL invoices + paper BLs
   - a dated e2e report for the UBL set
   - no Gemini calls for the invoices; the BLs reuse cached responses

## Licences and cost

- **OASIS UBL 2.1 XSDs:** published by OASIS for free use in implementations. I'd vendor the schema files in `backend/trimatch/extract/ubl21/` with their notice. That means downloading them from docs.oasis-open.org, which needs your OK.
- **lxml:** BSD licence.
- Free; no API cost.

## Out of scope

UN/CEFACT CII (add when the DGI confirms it), signatures and their verification, sending anything to a DGI platform (we only receive), credit notes (`CreditNote`), UBL delivery notes (`DespatchAdvice`).

## Decisions for Youness

- **D1. Mapping.** *Recommended:* our own documented assumption, as above, switchable in one file. Alternative: copy one vendor's guess. That costs the same and is no more official.
- **D2. Vendoring the OASIS UBL 2.1 XSDs** in the repo (downloaded from docs.oasis-open.org). *Recommended:* yes, so validation works offline and in CI.
