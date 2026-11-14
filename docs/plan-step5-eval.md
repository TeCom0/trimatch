# Build step 5: eval script and first dated result (plan)

Status: APPROVED 2026-11-14. Covers SPEC section 8 and section 9, item 5.

## What gets built

`uv run --project backend python -m eval.run --split dev|test|e2e [--model M]`, in `eval/run.py`:

1. Runs the extractor on every document of the split (cached Gemini responses are reused; the cache key includes model and prompt hash, so a changed prompt really re-runs).
2. Compares each document with its ground-truth label (`trimatch.extract.compare.field_diffs`, SPEC 8 normalisation).
3. For `e2e`, also runs the pipeline in **dry-run** mode per variant (clean set, degraded set) and compares decisions and reason codes with the expected table in SPEC section 4. This needs Odoo running with no trimatch drafts, so the script runs `odoo/reset_bills.py` first if drafts exist, after asking on the command line.
4. Writes `eval/results/YYYY-MM-DD_<git-sha>_<split>.md` (and a `.json` with the raw numbers next to it). The report refuses to run on a dirty git tree, so the sha really is the code that produced the numbers.

## Metrics (SPEC 8), each overall and per degradation (clean, rot, blur, stamp, handwriting)

- **Field accuracy per field** (supplier ICE, invoice number, line quantity, unit price, totals, and so on) and overall.
- **Line accuracy:** share of ground-truth lines with every field right.
- **Document accuracy:** share of documents with every field right.
- **Decision accuracy (e2e):** draft vs review, plus exact match of reason codes.
- **Straight-through rate and false-flag rate (e2e):** how many clean cases reach a draft, and how many get flagged wrongly.
- **Latency** per document, median and p95. **Tokens** per document (input, output). **Cost:** 0 on the free tier, with the tokens recorded so a paid estimate can be computed.
- **Confidence vs correctness:** a 5-bucket table of self-reported confidence against the share actually right. It's descriptive only; calibration work is Phase 1.

Each report header carries the date, git sha, split, seed, document count, model name and version, prompt hash, SDK version, and the API calls made in that run.

## Held-out rule

- `dev` (seed 1) is for prompt work. Any prompt change is checked on dev.
- `test` (seed 2) runs **once per prompt version**, for a reported result. I don't look at individual test errors to tune the prompt. If we change the prompt after seeing test numbers, the next reported test run says so in its header.
- Only numbers from a committed `eval/results/` file go into the README or CV, with a link to the file.

## Quota

200 dev + 200 test documents = 400 calls with Flash Lite, plus e2e (already cached). If the daily limit is lower, `eval.run` stops cleanly at the budget and resumes from the cache the next day. The report is only written once every document has a response. Nothing paid.

## Tests

Unit tests for the metric code (field, line and document accuracy, per-variant grouping, percentiles), with fake predictions and no network.

## Done when

1. `eval.run --split e2e` reports decision accuracy against SPEC section 4 (expected: 5/5 per variant set, from the step 4 run).
2. `eval.run --split dev` reports all metrics. We look at the errors together and decide on any prompt fix.
3. `eval.run --split test` runs once on the final prompt, and the dated report is committed.
4. Metric unit tests pass.

## Out of this step

README quickstart, CI (next, small), the GitHub push.
