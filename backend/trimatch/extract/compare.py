"""Field-by-field comparison of an extracted document with its ground truth (SPEC 8 rules).

Debug tool for prompt work in step 4; the reported eval (step 5) reuses `field_diffs`.
    uv run --project backend python -m trimatch.extract.compare data/synthetic/e2e/* [--model M]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from trimatch.extract import LabelExtractor
from trimatch.schema import Field


def norm(v):
    """SPEC 8: numbers to 2 dp, dates ISO, strings casefolded + whitespace collapsed."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    if isinstance(v, date):
        return v.isoformat()
    return re.sub(r"\s+", " ", str(v)).strip().casefold()


def flatten(obj, prefix: str = "") -> dict[str, Field]:
    out: dict[str, Field] = {}
    if isinstance(obj, Field):
        out[prefix] = obj
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            out |= flatten(x, f"{prefix}.{i}")
    elif isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            out |= flatten(getattr(obj, name), f"{prefix}.{name}" if prefix else name)
    return out


def field_diffs(pred, truth) -> list[tuple[str, object, object]]:
    """[(path, truth value, predicted value)] for every ground-truth field that differs."""
    p, t = flatten(pred), flatten(truth)
    diffs = []
    for path, tf in t.items():
        if tf.value is None:
            continue
        pv = p[path].value if path in p else None
        if norm(pv) != norm(tf.value):
            diffs.append((path, tf.value, pv))
    return diffs


def main(argv: list[str] | None = None) -> int:
    from trimatch.extract.gemini import GeminiExtractor, QuotaExhausted

    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--model")
    args = ap.parse_args(argv)
    import glob

    files = sorted(
        {Path(h) for f in args.files for h in (glob.glob(f) or [f]) if not h.endswith(".json")}
    )
    ex, labels = GeminiExtractor(model=args.model), LabelExtractor()
    per_field: Counter = Counter()
    n_fields = n_wrong = n_docs_ok = 0
    for f in files:
        truth = labels.extract(f)
        try:
            pred = ex.extract(f)
        except QuotaExhausted as e:
            print(f"STOP: {e}")
            break
        if pred.doc_type != truth.doc_type:
            print(f"{f.name}: doc_type {pred.doc_type} != {truth.doc_type}")
            continue
        d = field_diffs(pred, truth)
        n_fields += sum(1 for x in flatten(truth).values() if x.value is not None)
        n_wrong += len(d)
        n_docs_ok += not d
        print(f"{f.name}: {len(d)} wrong")
        for path, tv, pv in d:
            per_field[re.sub(r"\.\d+\.", ".N.", path)] += 1
            print(f"    {path}: truth {tv!r}  got {pv!r}")
    print(f"\n{len(files)} files, {ex.calls} API calls, model {ex.model}, prompt {ex.prompt_hash}")
    if n_fields:
        print(f"fields wrong: {n_wrong}/{n_fields}; documents fully right: {n_docs_ok}")
    for k, v in per_field.most_common():
        print(f"  {k}: {v}")
    print("(debug output for prompt work, not a reported result)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
