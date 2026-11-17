# Box placement, test split (2026-11-16)

| | |
|---|---|
| Code | `fb48cf2` |
| Split / seed | test / 2 |
| Documents | 40 clean PDFs (0 skipped: no cached response) |
| Model | gemini-3.5-flash-lite |
| Prompt hash | `cadd85983cea` |
| Command | `uv run --project backend python -m eval.boxes --split test` |

| Method | Fields | Box centre on the value | IoU >= 0.5 | Median IoU | Marked exact | Exact but wrong |
|---|---|---|---|---|---|---|
| gemini | 1504 | 33.0% (496/1504) | 16.7% (251/1504) | 0.082 | 0.0% (0/1504) | n/a |
| snapped | 1504 | 100.0% (1504/1504) | 99.1% (1491/1504) | 0.618 | 99.9% (1503/1504) | 0.0% (0/1503) |

Gemini boxes are always approximate. Snapped boxes are exact when the copied text was found in the PDF text layer; otherwise they are Gemini's box shifted by the page's estimated offset and marked approximate (drawn dashed in the review screen).
