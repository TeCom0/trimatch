"""Box placement eval: do the highlight boxes point at the right value?

    uv run --project backend python -m eval.boxes --split dev|test|e2e

For every field that has a box in the ground truth and in the prediction, compares
Gemini's own box with the snapped box (backend/trimatch/extract/snap.py) on the split's
clean PDFs (the only files with a text layer; scans keep Gemini's box, marked approximate).
Uses cached Gemini responses only: it never calls the API, and a document without a cached
response is counted as skipped.

Metrics, per method:
- hit: the box centre falls inside the true box (the highlight points at the right value)
- IoU >= 0.5, median IoU
- for snapped boxes: share marked exact, and wrong-but-exact (an exact box whose centre is
  outside the true box: the failure that would mislead a reviewer)

Writes eval/results/YYYY-MM-DD_<git sha>_boxes_<split>.md and .json. Like eval.run, a dirty
git tree is refused for a reported result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from datetime import date
from pathlib import Path

from eval.run import RESULTS, SPLITS, git, load_manifest
from trimatch.config import REPO_ROOT
from trimatch.extract import LabelExtractor
from trimatch.extract.gemini import GeminiExtractor, snapped_boxes
from trimatch.extract.gemini_schema import RDoc, to_document


def leaves(a, b, path=""):
    """(path, true box, predicted box) for every extracted value present in both."""
    if isinstance(a, dict) and "value" in a and "confidence" in a:
        bb = b if isinstance(b, dict) else {}
        yield path, a.get("source"), bb.get("source")
        return
    if isinstance(a, dict):
        for k, v in a.items():
            sub = b.get(k) if isinstance(b, dict) else None
            yield from leaves(v, sub, f"{path}.{k}".lstrip("."))
    elif isinstance(a, list):
        for i, v in enumerate(a):
            sub = b[i] if isinstance(b, list) and i < len(b) else None
            yield from leaves(v, sub, f"{path}.{i}")


def iou(t: dict, p: dict) -> float:
    ix = max(0.0, min(t["x1"], p["x1"]) - max(t["x0"], p["x0"]))
    iy = max(0.0, min(t["y1"], p["y1"]) - max(t["y0"], p["y0"]))
    inter = ix * iy
    area = (t["x1"] - t["x0"]) * (t["y1"] - t["y0"]) + (p["x1"] - p["x0"]) * (p["y1"] - p["y0"])
    return inter / (area - inter) if area - inter > 0 else 0.0


def hit(t: dict, p: dict) -> bool:
    cx, cy = (p["x0"] + p["x1"]) / 2, (p["y0"] + p["y1"]) / 2
    return t["x0"] <= cx <= t["x1"] and t["y0"] <= cy <= t["y1"]


class Tally:
    def __init__(self) -> None:
        self.n = self.hits = self.iou50 = self.exact = self.exact_wrong = 0
        self.ious: list[float] = []

    def add(self, t: dict, p: dict) -> None:
        self.n += 1
        h = hit(t, p)
        self.hits += h
        v = iou(t, p)
        self.ious.append(v)
        self.iou50 += v >= 0.5
        if not p.get("approximate", False):
            self.exact += 1
            self.exact_wrong += not h

    def row(self) -> dict:
        return {
            "fields": self.n,
            "hit": self.hits,
            "iou_ge_0_5": self.iou50,
            "median_iou": round(statistics.median(self.ious), 3) if self.ious else None,
            "exact": self.exact,
            "exact_wrong": self.exact_wrong,
        }


def run(split: str) -> dict:
    manifest = load_manifest(split)
    ex, labels = GeminiExtractor(), LabelExtractor()
    tallies = {"gemini": Tally(), "snapped": Tally()}
    docs = skipped = 0
    for d in manifest["documents"]:
        if d["variant"] != "clean":
            continue
        path = REPO_ROOT / "data" / "synthetic" / split / d["file"]
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if not (ex.cache_dir / f"{sha}.json").is_file():
            skipped += 1
            continue
        rdoc = RDoc.model_validate_json(ex.raw(path)["text"])
        truth = labels.extract(path).model_dump(mode="json")
        preds = {
            "gemini": to_document(rdoc),
            "snapped": to_document(rdoc, snapped_boxes(rdoc, path)),
        }
        if preds["gemini"] is None:
            skipped += 1
            continue
        docs += 1
        for name, pred in preds.items():
            for _, t, p in leaves(truth, pred.model_dump(mode="json")):
                if t and p:
                    tallies[name].add(t, p)
    return {
        "split": split,
        "seed": SPLITS[split],
        "docs": docs,
        "skipped": skipped,
        "model": ex.model,
        "prompt_hash": ex.prompt_hash,
        "methods": {k: v.row() for k, v in tallies.items()},
    }


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}% ({a}/{b})" if b else "n/a"


def report(res: dict, sha: str, dirty: bool) -> str:
    lines = [
        f"# Box placement, {res['split']} split ({date.today().isoformat()})",
        "",
        "| | |",
        "|---|---|",
        f"| Code | `{sha}`{' (DIRTY TREE: not a reported result)' if dirty else ''} |",
        f"| Split / seed | {res['split']} / {res['seed']} |",
        f"| Documents | {res['docs']} clean PDFs ({res['skipped']} skipped: no cached response) |",
        f"| Model | {res['model']} |",
        f"| Prompt hash | `{res['prompt_hash']}` |",
        (f"| Command | `uv run --project backend python -m eval.boxes --split {res['split']}` |"),
        "",
        (
            "| Method | Fields | Box centre on the value | IoU >= 0.5 | Median IoU "
            "| Marked exact | Exact but wrong |"
        ),
        "|---|---|---|---|---|---|---|",
    ]
    for name, r in res["methods"].items():
        n = r["fields"]
        lines.append(
            f"| {name} | {n} | {pct(r['hit'], n)} | {pct(r['iou_ge_0_5'], n)} | "
            f"{r['median_iou']} | {pct(r['exact'], n)} | {pct(r['exact_wrong'], r['exact'])} |"
        )
    lines += [
        "",
        (
            "Gemini boxes are always approximate. Snapped boxes are exact when the copied text was "
            "found in the PDF text layer; otherwise they are Gemini's box shifted by the page's "
            "estimated offset and marked approximate (drawn dashed in the review screen)."
        ),
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=SPLITS, required=True)
    ap.add_argument("--print-only", action="store_true", help="no files written (tuning)")
    args = ap.parse_args(argv)
    res = run(args.split)
    sha = git("rev-parse", "--short", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    text = report(res, sha, dirty)
    print(text)
    if args.print_only:
        return 0
    if dirty:
        print("dirty git tree: commit first, nothing written", file=sys.stderr)
        return 1
    stem = RESULTS / f"{date.today().isoformat()}_{sha}_boxes_{args.split}"
    Path(f"{stem}.md").write_text(text, encoding="utf-8")
    Path(f"{stem}.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {stem}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
