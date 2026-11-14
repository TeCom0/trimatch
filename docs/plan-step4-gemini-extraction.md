# Build step 4: Gemini extraction (plan)

Status: APPROVED 2026-11-14, built the same day. Covers the extractor in SPEC section 2 ("Gemini Flash vision on the free tier, synthetic documents only") and makes SPEC 9 item 3 run with a real extractor. The eval script and reported numbers are step 5.

## Facts that shape the plan (checked 2026-11-14)

| Fact | Source | Consequence |
|---|---|---|
| Free ("unpaid") Gemini API use: Google may use inputs and outputs to improve its products, and human reviewers may read them. It advises against sending personal or confidential data. | Gemini API Additional Terms, ai.google.dev/gemini-api/terms (the live page decides; snapshots differ in detail) | Only generated documents from `data/synthetic/` are ever sent. The extractor refuses any path outside `data/synthetic/`. `data/raw/` stays local-only (Phase 1). |
| Free-tier models and limits are per project and change often. Third-party reports from Oct–Nov 2026 disagree: as low as **5 requests/min and 20/day** on the newest Flash, and around 15/min and 500/day on Flash-Lite. Pro is not free. | AI Studio rate-limit page is authoritative; secondary: apidog.com, imisofts.com, aifreeapi.com blog posts | The model name is config, not code. Once your key is in `.env`, I list the models the key can use (`models.list`) and you read the limits for your project in AI Studio. If the best Flash really has 20/day, the e2e set (20 docs) costs a full day of quota, so we start on Flash-Lite and keep Flash for a final comparison. |
| Exceeding the per-minute limit returns HTTP 429. | same | Client-side rate limiter (requests/min from config) and retry with backoff on 429. A daily budget stops the run cleanly and resumes the next day from the cache. |

## Design

- `GeminiExtractor` implements the existing `Extractor` interface, so `trimatch process --extractor gemini` and (step 5) the eval use it unchanged.
- **Input:** the file as-is. A clean PDF goes in as `application/pdf`, a degraded JPEG as `image/jpeg`. One request per document.
- **Output:** structured JSON through the API's response schema, with one entry per SPEC 5 field: `value`, `confidence` (0–1, self-reported) and `box` in Gemini's `[ymin, xmin, ymax, xmax]` 0–1000 format. Code converts it to the pydantic `Invoice` / `DeliveryNote` (boxes normalised to 0–1, numbers to `Decimal`). The extractor also returns `doc_type` (SPEC 5).
- **Prompt:** short, French-document aware: comma decimals, narrow-space thousands, dd/mm/yyyy dates, ICE = 15 digits without spaces, exempt lines have rate 0 plus the article reference, and "copy what is printed, don't compute". It's stored as a file in the repo, and its hash is recorded with every result.
- **Deterministic settings:** temperature 0. Model name, prompt hash and SDK version are recorded with each response.
- **Cache:** every response is stored under `data/cache/gemini/<model>/<prompt hash>/<file sha256>.json`, with the raw response and token counts. Re-runs and later eval runs cost no quota unless the file, model or prompt changes. `--no-cache` forces a call.
- **Never trusted blindly:** the pipeline's checks stay the authority. LLM confidence is recorded but, as SPEC 5 says, not calibrated. Calibration is measured in Phase 1.

## Config

`config/extract.yaml`: `model`, `requests_per_minute`, `daily_budget`, `max_retries`. The key is `GEMINI_API_KEY` from `.env`, read the same way as the Odoo key and never printed or logged.

## Code

```
backend/trimatch/extract/
  gemini.py         GeminiExtractor: call, retry/rate-limit, cache, response -> schema
  gemini_schema.py  the response schema sent to the API, built from schema.py
  prompt_fr.md      the prompt
backend/tests/test_gemini_parse.py   parsing of recorded responses (no network): numbers,
                                     dates, boxes, missing fields; path guard
```

New dependency: `google-genai` (Google's official SDK, Apache 2.0).

## Done when

1. `python -m trimatch.extract.gemini --list-models` shows the models your key can use, and we pick the default together with the AI Studio limits in view.
2. `trimatch process "data/synthetic/e2e/*" --extractor gemini --dry-run` runs on all 20 e2e documents within the free quota and prints decisions.
3. A quick, unreported comparison against ground truth on those 20 documents: which fields are wrong, per degradation. It's for debugging the prompt only. The first reported numbers come from `eval.run` on the test split in step 5.
4. A second run makes zero API calls (cache).
5. Unit tests pass without network.

## Cost

Free tier only. If the quota turns out too small for the 200-document dev/test sets, I'll stop and ask before anything paid.

## Out of this step

Eval script and results table (step 5), local OCR/LLM extractor (Phase 1), real documents.
