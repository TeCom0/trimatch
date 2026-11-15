"""Eval metrics (SPEC section 8). Pure functions; eval/run.py does the I/O and the report."""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from trimatch.extract.compare import flatten, norm

CONF_BUCKETS = [(0.0, 0.5), (0.5, 0.8), (0.8, 0.9), (0.9, 0.99), (0.99, 1.01)]


def field_key(path: str) -> str:
    """'lines.3.quantity' -> 'lines.quantity'; 'vat.1.amount' -> 'vat.amount'."""
    return re.sub(r"\.\d+(?=\.|$)", "", path)


@dataclass
class DocScore:
    doc_id: str
    doc_type: str
    variant: str
    fields_total: int
    fields_right: int
    per_field: dict[str, tuple[int, int]]  # key -> (right, total)
    lines_total: int
    lines_right: int
    wrong: list[tuple[str, object, object]]  # (path, truth, predicted)
    conf: list[tuple[float, bool]]  # (predicted confidence, right) per truth field
    type_ok: bool = True

    @property
    def doc_right(self) -> bool:
        return self.type_ok and self.fields_right == self.fields_total


def score_document(doc_id: str, variant: str, pred, truth) -> DocScore:
    t = {p: f for p, f in flatten(truth).items() if f.value is not None}
    if pred is None or pred.doc_type != truth.doc_type:
        per = defaultdict(lambda: [0, 0])
        for p in t:
            per[field_key(p)][1] += 1
        return DocScore(
            doc_id,
            truth.doc_type,
            variant,
            len(t),
            0,
            {k: (a, b) for k, (a, b) in per.items()},
            len(truth.lines),
            0,
            [("doc_type", truth.doc_type, getattr(pred, "doc_type", None))],
            [],
            type_ok=False,
        )
    p = flatten(pred)
    per: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    wrong, conf = [], []
    line_bad: set[str] = set()
    for path, tf in t.items():
        pf = p.get(path)
        ok = pf is not None and norm(pf.value) == norm(tf.value)
        k = field_key(path)
        per[k][1] += 1
        per[k][0] += ok
        conf.append((pf.confidence if pf is not None else 0.0, ok))
        if not ok:
            wrong.append((path, tf.value, pf.value if pf is not None else None))
            m = re.match(r"lines\.(\d+)\.", path)
            if m:
                line_bad.add(m[1])
    right = sum(a for a, _ in per.values())
    n_lines = len(truth.lines)
    return DocScore(
        doc_id,
        truth.doc_type,
        variant,
        len(t),
        right,
        {k: (a, b) for k, (a, b) in per.items()},
        n_lines,
        n_lines - len(line_bad),
        wrong,
        conf,
    )


@dataclass
class Aggregate:
    docs: int = 0
    docs_right: int = 0
    fields: int = 0
    fields_right: int = 0
    lines: int = 0
    lines_right: int = 0
    per_field: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))

    def add(self, s: DocScore) -> None:
        self.docs += 1
        self.docs_right += s.doc_right
        self.fields += s.fields_total
        self.fields_right += s.fields_right
        self.lines += s.lines_total
        self.lines_right += s.lines_right
        for k, (a, b) in s.per_field.items():
            self.per_field[k][0] += a
            self.per_field[k][1] += b


def aggregate(scores: list[DocScore], by: str | None = None) -> dict[str, Aggregate]:
    """Overall ('all') plus one Aggregate per value of `by` ('variant' or 'doc_type')."""
    out: dict[str, Aggregate] = defaultdict(Aggregate)
    for s in scores:
        out["all"].add(s)
        if by:
            out[getattr(s, by)].add(s)
    return dict(out)


def calibration(scores: list[DocScore]) -> list[tuple[str, int, float | None]]:
    """[(bucket label, fields in bucket, share right)] for self-reported confidence."""
    pairs = [c for s in scores for c in s.conf]
    rows = []
    for lo, hi in CONF_BUCKETS:
        inb = [ok for c, ok in pairs if lo <= c < hi]
        label = f"[{lo:.2f}, {min(hi, 1.0):.2f}{']' if hi > 1 else ')'}"
        rows.append((label, len(inb), sum(inb) / len(inb) if inb else None))
    return rows


def percentile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    return statistics.quantiles(xs, n=100, method="inclusive")[int(q) - 1]


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}% ({a}/{b})" if b else "n/a"
