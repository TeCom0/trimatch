"""trimatch command line.

uv run --project backend trimatch process data/synthetic/e2e/*_clean.pdf
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Annotated

import httpx
import typer

from trimatch.extract import get_extractor
from trimatch.extract.gemini import QuotaExhausted
from trimatch.odoo_adapter import OdooClient
from trimatch.pipeline import JsonReviewSink, ReviewSink
from trimatch.pipeline import process as run_pipeline

app = typer.Typer(add_completion=False, no_args_is_help=True)
db_app = typer.Typer(no_args_is_help=True, help="Review store (PostgreSQL) setup.")
review_app = typer.Typer(no_args_is_help=True, help="Review queue.")
app.add_typer(db_app, name="db")
app.add_typer(review_app, name="review")


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
        bool, typer.Option(help="Decide only: no Odoo writes, no review cases.")
    ] = False,
    review_to: Annotated[
        str, typer.Option(help="store (review screen database) | json (files in data/review)")
    ] = "store",
) -> None:
    """Read BL + invoice documents, match them against Odoo, create draft bills or review cases."""
    paths = _expand(files)
    sink = None if dry_run else _review_sink(review_to)
    prior = _store_prior() if review_to == "store" else None
    try:
        results, lone_bls = run_pipeline(
            paths,
            get_extractor(extractor),
            OdooClient.from_env(),
            dry_run=dry_run,
            review_sink=sink,
            prior=prior,
        )
    except httpx.ConnectError as exc:
        typer.echo(
            f"ERROR: Odoo is not reachable ({exc}). Is Docker running? "
            "Start it with: docker compose -f odoo/docker-compose.yml up -d",
            err=True,
        )
        raise typer.Exit(1) from exc
    except QuotaExhausted as exc:
        typer.echo(f"STOPPED: {exc}", err=True)
        raise typer.Exit(2) from exc
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
        if r.review_file:
            typer.echo(f"{'':<38}-> {r.review_file}")
        for c in r.decision.reasons if r.decision.action == "review" else []:
            typer.echo(f"{'':<38}- {c.code}: {c.detail}")
        if r.duplicates:
            typer.echo(f"{'':<38}(also received as: {', '.join(r.duplicates)})")
    for b in lone_bls:
        typer.echo(f"BL {b.doc.number.value} ({b.path.name}): no invoice yet, nothing to do")


def _review_sink(target: str) -> ReviewSink:
    if target == "json":
        return JsonReviewSink()
    if target != "store":
        raise typer.BadParameter("--review-to must be 'store' or 'json'")
    from trimatch.store.cases import StoreReviewSink
    from trimatch.store.db import StoreNotConfigured, session_factory

    try:
        return StoreReviewSink(session_factory())
    except StoreNotConfigured as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


def _store_prior():
    """Review cases for the duplicate check; None if the store isn't set up (dry runs)."""
    from trimatch.store.cases import StorePrior
    from trimatch.store.db import StoreNotConfigured, session_factory

    try:
        return StorePrior(session_factory())
    except StoreNotConfigured:
        return None


@db_app.command("init")
def db_init(
    test_db: Annotated[
        bool, typer.Option("--test-db", help="Also create trimatch_review_test for pytest.")
    ] = False,
) -> None:
    """Create the trimatch role + database in the Odoo Postgres container and migrate it."""
    from trimatch.store import db

    dbs = ("trimatch_review", "trimatch_review_test") if test_db else ("trimatch_review",)
    try:
        for line in db.init(dbs):
            typer.echo(line)
    except Exception as exc:  # connection refused, wrong admin URL, ...
        typer.echo(
            f"ERROR: {exc}\nIs the database container up? "
            "docker compose -f odoo/docker-compose.yml up -d db",
            err=True,
        )
        raise typer.Exit(1) from exc


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply pending migrations to the review store."""
    from trimatch.store import db

    db.upgrade()
    typer.echo("migrations applied")


@review_app.command("import")
def review_import(
    files: Annotated[list[str], typer.Argument(help="Phase 0 review JSON files; globs allowed.")],
) -> None:
    """Load review entries written as JSON (data/review/*.json) into the review store."""
    from trimatch.store.cases import import_json_files
    from trimatch.store.db import session_factory

    hits = [Path(h) for p in files for h in sorted(glob.glob(p))]
    paths = [h for h in hits if h.suffix == ".json"]
    if not paths:
        raise typer.BadParameter(f"no JSON files match {files}")
    with session_factory().begin() as s:
        for f, r in import_json_files(s, paths):
            typer.echo(f"{f.name}: case #{r.case_id} {r.outcome}")


@review_app.command("clear")
def review_clear(
    yes: Annotated[bool, typer.Option("--yes", help="Confirm: delete every case.")] = False,
) -> None:
    """Delete all review cases, corrections and approvals (to replay the demo). Odoo is untouched."""
    from sqlalchemy import delete

    from trimatch.store.db import session_factory
    from trimatch.store.models import ReviewCase

    if not yes:
        raise typer.BadParameter("this deletes every review case and its corrections; add --yes")
    with session_factory().begin() as s:
        n = s.execute(delete(ReviewCase)).rowcount
    typer.echo(f"deleted {n} review case(s) with their corrections and approvals")


@app.command()
def serve(
    port: Annotated[int, typer.Option(help="Port on 127.0.0.1.")] = 8000,
    reload: Annotated[bool, typer.Option(help="Reload on code changes (development).")] = False,
) -> None:
    """Run the review API (and the built review screen, if frontend/dist exists). Local only."""
    import uvicorn

    uvicorn.run(
        "trimatch.api.app:create_app", factory=True, host="127.0.0.1", port=port, reload=reload
    )


@app.command()
def openapi(
    out: Annotated[Path, typer.Argument(help="Where to write the OpenAPI JSON.")],
) -> None:
    """Write the review API's OpenAPI document (the frontend generates its types from it)."""
    import json
    from unittest.mock import MagicMock

    from trimatch.api.app import create_app

    spec = create_app(sessions=MagicMock(), odoo=MagicMock(), frontend_dist=None).openapi()
    out.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    typer.echo(f"wrote {out}")


if __name__ == "__main__":
    app()
