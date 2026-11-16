"""Review API. Local only (bound to 127.0.0.1 by `trimatch serve`); no login, the reviewer
name comes from TRIMATCH_REVIEWER (plan-phase1-review-screen.md, D3).

Every write runs in one database transaction, committed before the response is sent. Odoo is reached through the same JSON-2
adapter as the CLI; the API can create draft bills and internal notes, never post or pay.
"""

import os
from collections.abc import Callable, Iterator
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from trimatch import review
from trimatch.api import pages
from trimatch.api.schemas import (
    ApproveIn,
    ApproveOut,
    BillRef,
    CaseDetail,
    CaseSummary,
    DocumentInfo,
    ErrorOut,
    Meta,
    RecheckIn,
    RecheckOut,
    RejectIn,
    RejectOut,
)
from trimatch.checks import Check
from trimatch.config import REPO_ROOT, MatchConfig, load_config
from trimatch.odoo_adapter import DEFAULT_URL, OdooClient, OdooError, load_dotenv
from trimatch.reasons import catalogue, describe
from trimatch.store.models import CaseStatus, ReviewCase

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
ERRORS = {
    404: {"model": ErrorOut},
    409: {"model": ErrorOut},
    422: {"model": ErrorOut},
    502: {"model": ErrorOut},
}


def create_app(
    sessions: sessionmaker[Session] | None = None,
    odoo: Callable[[], OdooClient] | None = None,
    reviewer: str | None = None,
    cfg: MatchConfig | None = None,
    frontend_dist: Path | None = FRONTEND_DIST,
) -> FastAPI:
    """Dependencies are injectable so tests run against a fake Odoo and a test database."""
    load_dotenv()
    if sessions is None:
        from trimatch.store.db import session_factory

        sessions = session_factory()
    odoo_factory = odoo or OdooClient.from_env
    reviewer = reviewer if reviewer is not None else (os.environ.get("TRIMATCH_REVIEWER") or None)
    cfg = cfg or load_config()
    odoo_url = os.environ.get("ODOO_URL", DEFAULT_URL)

    app = FastAPI(
        title="trimatch review API",
        version="1",
        summary="Review queue for invoices the three-way match could not draft on its own.",
    )

    # --- dependencies -------------------------------------------------------------------

    def db() -> Iterator[Session]:
        # Routes commit explicitly before they return; anything else is rolled back on close.
        with sessions() as session:
            yield session

    def odoo_client() -> OdooClient:
        return odoo_factory()

    def who() -> str:
        if not reviewer:
            raise review.ReviewError("TRIMATCH_REVIEWER is not set in .env: who is reviewing?")
        return reviewer

    DB = Annotated[Session, Depends(db)]
    Odoo = Annotated[OdooClient, Depends(odoo_client)]
    Reviewer = Annotated[str, Depends(who)]

    # --- errors -------------------------------------------------------------------------

    @app.exception_handler(review.Conflict)
    async def _conflict(_: Request, exc: review.Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "checks": exc.checks}, status_code=409)

    @app.exception_handler(review.ReviewError)
    async def _invalid(_: Request, exc: review.ReviewError) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "checks": exc.checks}, status_code=422)

    @app.exception_handler(OdooError)
    async def _odoo(_: Request, exc: OdooError) -> JSONResponse:
        return JSONResponse({"detail": f"Odoo: {exc}", "checks": []}, status_code=502)

    @app.exception_handler(httpx.HTTPError)
    async def _odoo_down(_: Request, exc: httpx.HTTPError) -> JSONResponse:
        return JSONResponse(
            {"detail": f"Odoo is not reachable ({exc.__class__.__name__}). Is Docker running?"},
            status_code=502,
        )

    def _case(session: Session, case_id: int) -> ReviewCase:
        case = session.get(ReviewCase, case_id)
        if case is None:
            raise HTTPException(404, f"no review case #{case_id}")
        return case

    # --- routes -------------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/meta")
    def meta() -> Meta:
        return Meta(
            reviewer=reviewer,
            min_reason_chars=review.MIN_REASON_CHARS,
            reasons=catalogue(),
            odoo_url=odoo_url,
        )

    @app.get("/api/reviews")
    def list_cases(
        session: DB,
        status: Annotated[Literal["open", "approved", "rejected", "all"], Query()] = "open",
    ) -> list[CaseSummary]:
        q = select(ReviewCase).order_by(ReviewCase.created_at, ReviewCase.id)
        if status != "all":
            q = q.where(ReviewCase.status == CaseStatus(status))
        return [CaseSummary.model_validate(c) for c in session.scalars(q)]

    @app.get("/api/reviews/{case_id}", responses=ERRORS)
    def get_case(session: DB, case_id: int) -> CaseDetail:
        case = _case(session, case_id)
        if case.first_opened_at is None:  # for time-per-review measurements later
            case.first_opened_at = datetime.now(UTC)
            session.commit()
        docs = {}
        for name, stored in (("invoice", case.invoice_file), ("bl", case.bl_file)):
            path = review.source_file(stored)
            if path and path.is_file():
                docs[name] = DocumentInfo(
                    file_name=path.name,
                    media_type=pages.media_type(path),
                    pages=pages.page_count(path),
                )
        return CaseDetail.model_validate(
            {
                **CaseSummary.model_validate(case).model_dump(),
                "reasons": [describe(Check(**r)) for r in case.reasons],
                "invoice": case.invoice,
                "bl": case.bl,
                "odoo_po": case.odoo_po,
                "documents": docs,
                "corrections": case.corrections,
                "actions": case.actions,
                "first_opened_at": case.first_opened_at,
            }
        )

    @app.get(
        "/api/reviews/{case_id}/documents/{doc}/pages/{page}",
        responses={**ERRORS, 200: {"content": {"image/png": {}, "image/jpeg": {}}}},
        response_class=Response,
    )
    def page_image(session: DB, case_id: int, doc: Literal["invoice", "bl"], page: int) -> Response:
        case = _case(session, case_id)
        path = review.source_file(case.invoice_file if doc == "invoice" else case.bl_file)
        if path is None or not path.is_file():
            raise HTTPException(404, f"case #{case_id} has no {doc} file on disk")
        try:
            data, media_type = pages.page_image(path, page)
        except IndexError:
            raise HTTPException(404, f"{doc} has no page {page}") from None
        return Response(
            data, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"}
        )

    @app.post("/api/reviews/{case_id}/recheck", responses=ERRORS)
    def recheck(session: DB, odoo: Odoo, case_id: int, body: RecheckIn) -> RecheckOut:
        """Re-run validation and matching on the corrected values. Writes nothing."""
        outcome, _, _ = review.recheck(_case(session, case_id), _edits(body), odoo, cfg)
        return RecheckOut(
            action=outcome.action,
            failed=outcome.failed,
            blocking=outcome.blocking,
            overridable=outcome.overridable,
            can_approve=outcome.can_approve,
            needs_reason=outcome.needs_reason,
            already_drafted=outcome.already_drafted,
            po=asdict(outcome.po) if outcome.po else None,
        )

    @app.post("/api/reviews/{case_id}/approve", responses=ERRORS)
    def approve(
        session: DB, odoo: Odoo, who: Reviewer, case_id: int, body: ApproveIn
    ) -> ApproveOut:
        """Log corrections, re-check, create the DRAFT vendor bill in Odoo. Never posts."""
        try:
            result = review.approve(session, case_id, _edits(body), body.reason, who, odoo, cfg)
        except LookupError:
            raise HTTPException(404, f"no review case #{case_id}") from None
        out = ApproveOut(  # built before the commit: nothing can fail after it
            case=CaseSummary.model_validate(session.get(ReviewCase, case_id)),
            bill=BillRef.model_validate(result.bill),
            corrections=result.corrections,
            overridden=result.overridden,
            note_error=result.note_error,
        )
        session.commit()
        return out

    @app.post("/api/reviews/{case_id}/reject", responses=ERRORS)
    def reject(session: DB, who: Reviewer, case_id: int, body: RejectIn) -> RejectOut:
        """Close the case without a bill, with a reason (e.g. ask for a credit note)."""
        try:
            n = review.reject(session, case_id, _edits(body), body.reason, who)
        except LookupError:
            raise HTTPException(404, f"no review case #{case_id}") from None
        out = RejectOut(
            case=CaseSummary.model_validate(session.get(ReviewCase, case_id)), corrections=n
        )
        session.commit()
        return out

    # --- built React app (frontend/dist), if present ------------------------------------

    if frontend_dist and (frontend_dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            return FileResponse(frontend_dist / "index.html")

    return app


def _edits(body: RecheckIn) -> list[review.FieldEdit]:
    return [review.FieldEdit(e.doc, e.path, e.value) for e in body.edits]
