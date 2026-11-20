"""Eval runner (SPEC section 8, docs/plan-step5-eval.md).

    uv run --project backend python -m eval.run --split dev|test|e2e [--model M] [--reset-bills]

Writes eval/results/YYYY-MM-DD_<git sha>_<split>[_<model>].md and .json. Refuses to write a
report from a dirty git tree, so the sha is the code that produced the numbers.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import date
from importlib.metadata import version

from trimatch.config import REPO_ROOT
from trimatch.evaluation import aggregate, calibration, pct, percentile, score_document
from trimatch.extract import LabelExtractor, Routed
from trimatch.extract.gemini import GeminiExtractor, NotADocument, QuotaExhausted
from trimatch.extract.ubl import UblExtractor

SPLITS = {"dev": 1, "test": 2, "e2e": 3, "e2e_ubl": 3}
RESULTS = REPO_ROOT / "eval" / "results"
VARIANTS = ["clean", "rot", "blur", "stamp", "handwriting", "ubl"]
EXPECTED = {
    "clean": ("draft", []),
    "short_delivery": ("review", ["QTY_EXCEEDS_RECEIVED"]),
    "price_change": ("review", ["PRICE_OVER_TOLERANCE"]),
    # dry run: the copy is caught within the run (nothing is billed, so no qty failure)
    "duplicate_invoice": ("review", ["DUPLICATE_SUSPECTED"]),
    # e2e_ubl planted e-invoices (trimatch.generate.ubl_split)
    "ubl_invalid": ("review", ["UBL_INVALID"]),
    "ubl_bad_total": ("review", ["SUM_TTC"]),
    "ubl_wrong_buyer": ("review", ["CUSTOMER_IS_US"]),
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def load_manifest(split: str) -> dict:
    f = REPO_ROOT / "data" / "synthetic" / split / "manifest.json"
    if not f.is_file():
        sys.exit(f"no {f}: run `python -m trimatch.generate --split {split}` first")
    return json.loads(f.read_text(encoding="utf-8"))


def stratified(manifest: dict, n: int) -> dict:
    """n documents balanced over variants and document types, spread over the split's
    orders (tuning subsets)."""
    groups: dict[tuple, list] = {}
    for d in manifest["documents"]:
        groups.setdefault((d["variant"], d["doc_type"]), []).append(d)
    per_group = -(-n // len(groups))  # ceil
    picked = []
    for key in sorted(groups):
        g = groups[key]
        step = max(1, len(g) // per_group)
        picked += g[::step][:per_group]
    picked = sorted(picked, key=lambda d: d["doc_id"])[:n]
    return {**manifest, "documents": picked, "subset": f"stratified {len(picked)}"}


def make_extractor(name: str, model: str | None):
    if name == "gemini":
        return GeminiExtractor(model=model)
    from trimatch.extract.local import LocalVlmExtractor, OcrLlmExtractor

    return {"local-vlm": LocalVlmExtractor, "local-ocr-llm": OcrLlmExtractor}[name](model=model)


def extract_all(split: str, manifest: dict, ex: GeminiExtractor):
    labels = LabelExtractor()
    scores, latencies, tokens = [], [], []
    for d in manifest["documents"]:
        path = REPO_ROOT / "data" / "synthetic" / split / d["file"]
        truth = labels.extract(path)
        if path.suffix.lower() == ".xml":  # e-invoice: parsed, no model call
            pred = UblExtractor().extract(path)
        else:
            try:
                pred = ex.extract(path)
            except NotADocument:
                pred = None
            rec = ex.raw(path)
            latencies.append(rec["latency_s"])
            tokens.append(rec["usage"])
        scores.append(score_document(d["doc_id"], d["variant"], pred, truth))
        print(f"  {d['file']}: {scores[-1].fields_right}/{scores[-1].fields_total}", flush=True)
    return scores, latencies, tokens


def e2e_decisions(manifest: dict, reset: bool, split: str = "e2e", ex=None) -> list[dict]:
    """Dry-run the pipeline on the clean set and on the degraded set, vs SPEC section 4."""
    from trimatch.odoo_adapter import OdooClient
    from trimatch.pipeline import process

    client = OdooClient.from_env()
    bot_drafts = client.search_read(
        "account.move", [("move_type", "=", "in_invoice"), ("state", "=", "draft")], ["id"]
    )
    if bot_drafts:
        if not reset:
            sys.exit(
                "Odoo has draft bills; decisions would be ALREADY_DRAFTED. Re-run with "
                "--reset-bills (deletes trimatch's draft bills via odoo/reset_bills.py)."
            )
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "odoo/docker-compose.yml",
                "run",
                "--rm",
                "odoo",
                "bash",
                "-c",
                "odoo shell -d trimatch --no-http < /mnt/trimatch/odoo/reset_bills.py",
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        )
    scen = {d["file"]: d["scenario"] for d in manifest["documents"]}
    rows = []
    e2e_dir = REPO_ROOT / "data" / "synthetic" / split
    sets = (
        [("ubl", lambda v: True)]
        if split == "e2e_ubl"
        else [("clean", lambda v: v == "clean"), ("degraded", lambda v: v != "clean")]
    )
    for label, pick in sets:
        files = [e2e_dir / d["file"] for d in manifest["documents"] if pick(d["variant"])]
        results, _ = process(files, Routed(ex or GeminiExtractor()), client, dry_run=True)
        for r in results:
            want_action, want_codes = EXPECTED[scen[r.invoice_file]]
            rows.append(
                {
                    "set": label,
                    "po": r.po_ref
                    + {
                        "duplicate_invoice": " re-issued",
                        "ubl_invalid": " schema-invalid",
                        "ubl_bad_total": " bad total",
                        "ubl_wrong_buyer": " wrong buyer",
                    }.get(scen[r.invoice_file], ""),
                    "expected": want_action,
                    "expected_codes": want_codes,
                    "got": r.decision.action,
                    "got_codes": r.decision.codes,
                    "ok": r.decision.action == want_action and r.decision.codes == want_codes,
                }
            )
    return rows


def report(
    split: str,
    manifest: dict,
    ex: GeminiExtractor,
    scores,
    latencies,
    tokens,
    decisions,
    sha: str,
    dirty: bool,
) -> str:
    by_var = aggregate(scores, "variant")
    by_type = aggregate(scores, "doc_type")
    a = by_var["all"]
    sample = json.loads(next(iter(sorted(ex.cache_dir.glob("*.json")))).read_text("utf-8"))
    L = [f"# Extraction eval: {split}", ""]
    if dirty:
        L += ["**DIRTY TREE: not a reportable result.**", ""]
    L += [
        "| | |",
        "|---|---|",
        f"| Date | {date.today().isoformat()} |",
        f"| Code | `{sha}` |",
        f"| Split / seed / documents | {split} / {manifest['seed']} / {len(scores)} |",
        f"| Generator commit | `{manifest['generator_git_sha']}` |",
        f"| Extractor | {getattr(ex, 'name', 'gemini')} |",
        f"| Model | {ex.model} (version reported: {sample.get('model_version')}) |",
        f"| Documents used | {manifest.get('subset', 'all')} |",
        f"| Prompt hash | `{ex.prompt_hash}` |",
        f"| SDK | google-genai {version('google-genai')}, Python {platform.python_version()} |",
        f"| API calls in this run | {ex.calls} (rest from cache) |",
        "| Cost | 0 (free tier, or local on this laptop); tokens allow a paid estimate |",
        "",
        "## Overall",
        "",
        f"- Field accuracy: {pct(a.fields_right, a.fields)}",
        f"- Line accuracy (every field of the line right): {pct(a.lines_right, a.lines)}",
        f"- Document accuracy (every field right): {pct(a.docs_right, a.docs)}",
        "",
        "## By degradation",
        "",
        "| Variant | Docs | Field acc. | Line acc. | Doc acc. |",
        "|---|---|---|---|---|",
    ]
    for v in VARIANTS:
        if v in by_var:
            g = by_var[v]
            L.append(
                f"| {v} | {g.docs} | {pct(g.fields_right, g.fields)} | "
                f"{pct(g.lines_right, g.lines)} | {pct(g.docs_right, g.docs)} |"
            )
    L += [
        "",
        "## By document type",
        "",
        "| Type | Docs | Field acc. | Doc acc. |",
        "|---|---|---|---|",
    ]
    for t in ("delivery_note", "invoice"):
        if t in by_type:
            g = by_type[t]
            L.append(
                f"| {t} | {g.docs} | {pct(g.fields_right, g.fields)} | "
                f"{pct(g.docs_right, g.docs)} |"
            )
    L += ["", "## Per field", "", "| Field | Accuracy |", "|---|---|"]
    for k, (r, n) in sorted(a.per_field.items(), key=lambda kv: (kv[1][0] / kv[1][1], kv[0])):
        L.append(f"| {k} | {pct(r, n)} |")
    if decisions:
        ok = sum(d["ok"] for d in decisions)
        clean = [d for d in decisions if d["expected"] == "draft"]
        flagged = [d for d in clean if d["got"] != "draft"]
        L += [
            "",
            "## End-to-end decisions (dry run against Odoo, SPEC section 4)",
            "",
            f"- Decision + reason codes exact: {pct(ok, len(decisions))}",
            f"- Straight-through (clean cases drafted): {pct(len(clean) - len(flagged), len(clean))}",
            f"- False flags (clean cases sent to review): {pct(len(flagged), len(clean))}",
            "",
            "| Set | PO | Expected | Got | OK |",
            "|---|---|---|---|---|",
        ]
        for d in decisions:
            L.append(
                f"| {d['set']} | {d['po']} | {d['expected']} {d['expected_codes']} | "
                f"{d['got']} {d['got_codes']} | {'yes' if d['ok'] else 'NO'} |"
            )
    tin = [t["prompt_tokens"] or 0 for t in tokens]
    tout = [(t["output_tokens"] or 0) + (t["thinking_tokens"] or 0) for t in tokens]
    L += [
        "",
        "## Latency and tokens per document",
        "",
        "(Model calls only: XML e-invoices are parsed without a model.)",
        "",
        (
            f"- Latency (recorded at call time): median {percentile(latencies, 50):.1f} s, "
            f"p95 {percentile(latencies, 95):.1f} s"
        ),
        (
            f"- Input tokens: median {percentile(tin, 50):.0f}; output tokens (incl. thinking): "
            f"median {percentile(tout, 50):.0f}"
        ),
        "",
        "## Self-reported confidence vs correctness (descriptive, not calibrated)",
        "",
        "| Confidence | Fields | Share right |",
        "|---|---|---|",
    ]
    for label, n, share in calibration(scores):
        L.append(f"| {label} | {n} | {'n/a' if share is None else f'{100 * share:.1f}%'} |")
    L += ["", "## Errors", ""]
    errs = [(s.doc_id, w) for s in scores for w in s.wrong]
    if split == "test":
        L.append(
            f"{len(errs)} wrong fields. Not listed: the test split is held out and its "
            "errors are not used for tuning."
        )
    else:
        for doc_id, (path, tv, pv) in errs:
            L.append(f"- `{doc_id}` {path}: truth `{tv}`, got `{pv}`")
        if not errs:
            L.append("None.")
    L += ["", "Generated by `eval/run.py`. Metric definitions: docs/SPEC.md section 8."]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.run")
    ap.add_argument("--split", choices=sorted(SPLITS), required=True)
    ap.add_argument("--model")
    ap.add_argument(
        "--extractor", default="gemini", choices=["gemini", "local-vlm", "local-ocr-llm"]
    )
    ap.add_argument("--subset", type=int, help="stratified subset of N documents (tuning)")
    ap.add_argument("--reset-bills", action="store_true")
    ap.add_argument("--allow-dirty", action="store_true", help="debug only; report marked DIRTY")
    args = ap.parse_args(argv)

    dirty = bool(git("status", "--porcelain", "--", ".", ":!eval/results"))  # reports may pile up
    if dirty and not args.allow_dirty:
        sys.exit("git tree is dirty: commit first, so the report's sha is the code that ran")
    sha = git("rev-parse", "--short", "HEAD")
    manifest = load_manifest(args.split)
    ex = make_extractor(args.extractor, args.model)
    if args.subset:
        manifest = stratified(manifest, args.subset)
    print(f"{args.split}: {len(manifest['documents'])} documents, model {ex.model}")
    try:
        scores, lat, tok = extract_all(args.split, manifest, ex)
    except QuotaExhausted as e:
        print(f"STOPPED: {e}\nNo report written; re-run later, cached documents cost nothing.")
        return 2
    decisions = (
        e2e_decisions(manifest, args.reset_bills, args.split, ex)
        if args.split in ("e2e", "e2e_ubl")
        else []
    )

    RESULTS.mkdir(parents=True, exist_ok=True)
    tag = f"_subset{args.subset}" if args.subset else ""
    model_tag = ex.model.replace(":", "-")  # ":" is not allowed in Windows file names
    stem = (
        f"{date.today().isoformat()}_{sha}{'-dirty' if dirty else ''}_{args.split}{tag}_{model_tag}"
    )
    md = report(args.split, manifest, ex, scores, lat, tok, decisions, sha, dirty)
    (RESULTS / f"{stem}.md").write_text(md, encoding="utf-8")
    raw = {
        "split": args.split,
        "sha": sha,
        "dirty": dirty,
        "model": ex.model,
        "prompt_hash": ex.prompt_hash,
        "documents": [
            {
                "doc_id": s.doc_id,
                "variant": s.variant,
                "doc_type": s.doc_type,
                "fields_right": s.fields_right,
                "fields_total": s.fields_total,
                "lines_right": s.lines_right,
                "lines_total": s.lines_total,
            }
            for s in scores
        ],
        "decisions": decisions,
    }
    (RESULTS / f"{stem}.json").write_text(json.dumps(raw, indent=1), encoding="utf-8")
    print(md)
    print(f"Wrote {RESULTS / stem}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
