"""Generate synthetic BL + invoice documents with ground truth (SPEC 8, plan-step2-generator.md).

uv run --project backend python -m trimatch.generate --split e2e [--preview]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

from trimatch.generate.data import REPO_ROOT, SPLIT_SEEDS, build_split
from trimatch.generate.degrade import degrade as degrade_doc
from trimatch.generate.degrade import iter_fields, rasterise
from trimatch.generate.render import render_pdf


def git_sha() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def draw_boxes(img: Image.Image, label) -> Image.Image:
    img = img.convert("RGB")
    d = ImageDraw.Draw(img)
    w, h = img.size
    for f in iter_fields(label):
        if f.source:
            b = f.source
            d.rectangle((b.x0 * w, b.y0 * h, b.x1 * w, b.y1 * h), outline=(230, 0, 120), width=2)
    return img


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trimatch.generate")
    ap.add_argument("--split", choices=sorted(SPLIT_SEEDS), required=True)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data")
    ap.add_argument(
        "--preview",
        action="store_true",
        help="also write PNGs with the ground-truth boxes drawn, to data/previews/",
    )
    args = ap.parse_args(argv)

    docs = build_split(args.split)
    doc_dir = args.out / "synthetic" / args.split
    label_dir = args.out / "labels" / args.split
    prev_dir = args.out / "previews" / args.split
    for d in (doc_dir, label_dir, prev_dir):
        shutil.rmtree(d, ignore_errors=True)
    doc_dir.mkdir(parents=True)
    label_dir.mkdir(parents=True)
    if args.preview:
        prev_dir.mkdir(parents=True)

    manifest = []
    t0 = time.perf_counter()
    with sync_playwright() as pw, tempfile.TemporaryDirectory() as tmpdir:
        browser = pw.chromium.launch()
        for n, doc in enumerate(docs, 1):
            if doc.variant == "clean":
                out = doc_dir / f"{doc.doc_id}.pdf"
                label = render_pdf(browser, doc, out)
                img = rasterise(out) if args.preview else None
            else:
                tmp_pdf = Path(tmpdir) / f"{doc.doc_id}.pdf"
                rendered = render_pdf(browser, doc, tmp_pdf)
                out = doc_dir / f"{doc.doc_id}.jpg"
                label = degrade_doc(tmp_pdf, rendered, doc.variant, doc.rng_key, out)
                img = Image.open(out) if args.preview else None
            missing = [f for f in iter_fields(label) if f.value is not None and f.source is None]
            if missing:
                raise RuntimeError(f"{doc.doc_id}: {len(missing)} fields have no box")
            (label_dir / f"{doc.doc_id}.json").write_text(
                label.model_dump_json(indent=1), encoding="utf-8"
            )
            if img is not None:
                draw_boxes(img, label).save(prev_dir / f"{doc.doc_id}.png")
            manifest.append(
                {
                    "doc_id": doc.doc_id,
                    "file": out.name,
                    "doc_type": label.doc_type,
                    "po_ref": doc.po_ref,
                    "scenario": doc.scenario,
                    "variant": doc.variant,
                }
            )
            print(f"[{n}/{len(docs)}] {out.name}", flush=True)
        browser.close()

    (doc_dir / "manifest.json").write_text(
        json.dumps(
            {
                "split": args.split,
                "seed": SPLIT_SEEDS[args.split],
                "generator_git_sha": git_sha(),
                "doc_count": len(manifest),
                "documents": manifest,
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {len(manifest)} documents to {doc_dir} in {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
