"""trimatch command line.

uv run --project backend trimatch process data/synthetic/e2e/*_clean.pdf
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Annotated

import typer

from trimatch.extract import get_extractor
from trimatch.odoo_adapter import OdooClient
from trimatch.pipeline import process as run_pipeline

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def main() -> None:
    """Delivery note + invoice three-way match against Odoo. Creates DRAFT bills only."""


def _expand(patterns: list[str]) -> list[Path]:
    # PowerShell does not expand globs for native commands, so we do it here.
    out: list[Path] = []
    for p in patterns:
        hits = glob.glob(p) if any(ch in p for ch in "*?[") else [p]
        out += [Path(h) for h in sorted(hits)]
    files = [f for f in dict.fromkeys(out) if f.is_file() and f.suffix.lower() != ".json"]
    if not files:
        raise typer.BadParameter(f"no input files match {patterns}")
    return files


@app.command()
def process(
    files: Annotated[list[str], typer.Argument(help="Documents (PDF/JPG); globs allowed.")],
    extractor: Annotated[
        str, typer.Option(help="labels (ground truth) | gemini (step 4)")
    ] = "labels",
    dry_run: Annotated[
        bool, typer.Option(help="Decide only: no Odoo writes, no review files.")
    ] = False,
) -> None:
    """Read BL + invoice documents, match them against Odoo, create draft bills or review entries."""
    paths = _expand(files)
    results, lone_bls = run_pipeline(
        paths, get_extractor(extractor), OdooClient.from_env(), dry_run=dry_run
    )
    mode = " (dry run)" if dry_run else ""
    typer.echo(f"\n{len(paths)} files, {len(results)} invoices{mode}\n")
    typer.echo(f"{'PO':<8} {'invoice':<20} {'decision':<8} {'reasons / result'}")
    for r in results:
        if r.decision.action == "draft":
            what = (
                f"Odoo bill id {r.bill['id']}, total {r.bill['amount_total']:.2f}"
                if r.bill
                else "would create a draft bill"
            )
        elif r.decision.action == "skip":
            what = r.decision.reasons[0].detail
        else:
            what = ", ".join(r.decision.codes)
        typer.echo(f"{r.po_ref or '?':<8} {r.invoice_number:<20} {r.decision.action:<8} {what}")
        for c in r.decision.reasons if r.decision.action == "review" else []:
            typer.echo(f"{'':<38}- {c.code}: {c.detail}")
        if r.duplicates:
            typer.echo(f"{'':<38}(also received as: {', '.join(r.duplicates)})")
    for b in lone_bls:
        typer.echo(f"BL {b.doc.number.value} ({b.path.name}): no invoice yet, nothing to do")


if __name__ == "__main__":
    app()
