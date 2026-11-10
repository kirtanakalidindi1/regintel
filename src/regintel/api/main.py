"""FastAPI backend for RegIntel.

Run locally:
    uv run uvicorn regintel.api.main:app --reload
Interactive docs at http://127.0.0.1:8000/docs
"""

import io
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Annotated, Literal

import anthropic
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from regintel import config
from regintel.api.queries import (
    UpdateFilters,
    filtered_rows,
    final_labels,
    portfolio_items,
)
from regintel.api.schemas import (
    AnalysisOut,
    AssessmentOut,
    AssessmentReviewIn,
    ReviewIn,
    UpdateDetail,
    UpdateList,
    UpdateSummary,
)
from regintel.assessment_export import to_markdown
from regintel.db.database import get_engine, get_sessionmaker, init_db
from regintel.db.models import AnalysisRecord, ImpactAssessmentRecord, Update
from regintel.db.repository import latest_assessment, save_assessment
from regintel.llm.assess import AssessmentError, draft_assessment
from regintel.llm.taxonomy import (
    ACTION_OWNERS,
    LABELLING_DOCUMENTS,
    PRODUCT_TYPES,
    RELEVANCE,
    THERAPEUTIC_AREAS,
    TOPICS,
)
from regintel.portfolio import load_portfolio


def create_app(engine: Engine | None = None, llm_client=None) -> FastAPI:
    """Build the app. Tests pass an in-memory engine and a fake Claude client."""
    engine = engine or get_engine()
    init_db(engine)

    app = FastAPI(title="RegIntel API", version="0.1.0")
    app.state.sessionmaker = get_sessionmaker(engine)
    app.state.llm_client = llm_client

    def get_llm_client():
        if app.state.llm_client is None:
            if not config.ANTHROPIC_API_KEY:
                raise HTTPException(503, "ANTHROPIC_API_KEY is not set in .env")
            app.state.llm_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        return app.state.llm_client

    def get_session(request: Request) -> Iterator[Session]:
        with request.app.state.sessionmaker() as session:
            yield session

    SessionDep = Annotated[Session, Depends(get_session)]

    def filters(
        source: str | None = None,
        source_type: str | None = None,
        topic: str | None = None,
        relevance: str | None = None,
        product_type: str | None = None,
        therapeutic_area: str | None = None,
        review_status: str | None = None,
        analysed: bool | None = None,
        labelling_impact: bool | None = None,
        rare_disease: bool | None = None,
        portfolio_item: str | None = None,
        action_owner: str | None = None,
        q: Annotated[str | None, Query(description="Search title and text")] = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> UpdateFilters:
        return UpdateFilters(
            source=source,
            source_type=source_type,
            topic=topic,
            relevance=relevance,
            product_type=product_type,
            therapeutic_area=therapeutic_area,
            review_status=review_status,
            analysed=analysed,
            labelling_impact=labelling_impact,
            rare_disease=rare_disease,
            portfolio_item=portfolio_item,
            action_owner=action_owner,
            q=q,
            date_from=date_from,
            date_to=date_to,
        )

    FiltersDep = Annotated[UpdateFilters, Depends(filters)]

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/taxonomy")
    def taxonomy() -> dict:
        """Label lists, so the frontend never hard-codes them."""
        return {
            "topics": list(TOPICS),
            "product_types": list(PRODUCT_TYPES),
            "therapeutic_areas": THERAPEUTIC_AREAS,
            "relevance": list(RELEVANCE),
            "action_owners": list(ACTION_OWNERS),
            "labelling_documents": LABELLING_DOCUMENTS,
            "review_statuses": ["pending", "approved", "corrected", "rejected"],
        }

    @app.get("/portfolio")
    def portfolio() -> list[dict]:
        """The watchlist of products and drug classes."""
        return load_portfolio()

    @app.get("/stats")
    def stats(session: SessionDep) -> dict:
        by_source = session.execute(
            select(Update.source, Update.source_type, func.count()).group_by(
                Update.source, Update.source_type
            )
        ).all()
        by_review = session.execute(
            select(AnalysisRecord.review_status, func.count()).group_by(
                AnalysisRecord.review_status
            )
        ).all()
        _, rows = filtered_rows(session, UpdateFilters(analysed=True))
        labels = [(final_labels(a), a.review_status) for _, a in rows]
        return {
            "updates": sum(n for _, _, n in by_source),
            "analysed_updates": len(rows),
            "by_source": [
                {"source": s, "source_type": t, "count": n} for s, t, n in by_source
            ],
            "by_review_status": {status: n for status, n in by_review},
            "queues": {
                "needs_review": sum(1 for _, status in labels if status == "pending"),
                "high_relevance": sum(
                    1 for lab, _ in labels if lab["relevance"] == "high"
                ),
                "labelling_impact": sum(
                    1 for lab, _ in labels if lab["labelling_impact"]
                ),
                "portfolio_matches": sum(
                    1 for lab, _ in labels if lab["portfolio_impacts"]
                ),
            },
        }

    @app.get("/updates", response_model=UpdateList)
    def list_updates(
        session: SessionDep,
        f: FiltersDep,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> UpdateList:
        total, rows = filtered_rows(session, f, limit=limit, offset=offset)
        items = []
        for update, analysis in rows:
            labels = final_labels(analysis)
            items.append(
                UpdateSummary(
                    id=update.id,
                    source=update.source,
                    source_type=update.source_type,
                    title=update.title,
                    url=update.url,
                    published_date=update.published_date,
                    topic=labels.get("topic"),
                    relevance=labels.get("relevance"),
                    therapeutic_areas=labels.get("therapeutic_areas", []),
                    rare_disease=labels.get("rare_disease"),
                    labelling_impact=labels.get("labelling_impact"),
                    action_owners=labels.get("action_owners", []),
                    portfolio_items=portfolio_items(labels),
                    review_status=analysis.review_status if analysis else None,
                )
            )
        return UpdateList(total=total, items=items)

    @app.get("/updates/{update_id}", response_model=UpdateDetail)
    def get_update(update_id: int, session: SessionDep) -> UpdateDetail:
        update = session.get(Update, update_id)
        if update is None:
            raise HTTPException(404, "Update not found")
        latest = session.scalar(
            select(AnalysisRecord)
            .where(AnalysisRecord.update_id == update_id)
            .order_by(AnalysisRecord.id.desc())
            .limit(1)
        )
        detail = UpdateDetail.model_validate(update)
        detail.analysis = AnalysisOut.model_validate(latest) if latest else None
        assessment = latest_assessment(session, latest.id) if latest else None
        detail.assessment = (
            AssessmentOut.model_validate(assessment) if assessment else None
        )
        return detail

    @app.post("/analyses/{analysis_id}/review", response_model=AnalysisOut)
    def review_analysis(
        analysis_id: int, review: ReviewIn, session: SessionDep
    ) -> AnalysisOut:
        analysis = session.get(AnalysisRecord, analysis_id)
        if analysis is None:
            raise HTTPException(404, "Analysis not found")
        analysis.review_status = review.status
        analysis.reviewed_output = (
            review.corrections.model_dump(exclude_none=True)
            if review.corrections
            else None
        )
        analysis.reviewer_note = review.note
        analysis.reviewed_at = datetime.now(UTC)
        session.commit()
        return AnalysisOut.model_validate(analysis)

    @app.post("/analyses/{analysis_id}/assessment", response_model=AssessmentOut)
    def create_assessment(analysis_id: int, session: SessionDep) -> AssessmentOut:
        """Draft a labelling impact assessment with Claude. Takes several seconds."""
        analysis = session.get(AnalysisRecord, analysis_id)
        if analysis is None:
            raise HTTPException(404, "Analysis not found")
        update = session.get(Update, analysis.update_id)
        try:
            result = draft_assessment(
                get_llm_client(),
                config.ASSESSMENT_MODEL,
                title=update.title,
                source=update.source,
                source_type=update.source_type,
                body_text=update.body_text,
                labels=final_labels(analysis),
                portfolio=load_portfolio(),
            )
        except AssessmentError as exc:
            raise HTTPException(
                502, f"Claude's assessment couldn't be used: {exc}"
            ) from exc
        except anthropic.APIError as exc:
            raise HTTPException(
                502, f"The Claude API returned an error: {exc}"
            ) from exc
        return AssessmentOut.model_validate(save_assessment(session, analysis, result))

    @app.get("/analyses/{analysis_id}/assessment", response_model=AssessmentOut)
    def get_assessment(analysis_id: int, session: SessionDep) -> AssessmentOut:
        assessment = latest_assessment(session, analysis_id)
        if assessment is None:
            raise HTTPException(404, "No assessment drafted yet")
        return AssessmentOut.model_validate(assessment)

    @app.post("/assessments/{assessment_id}/review", response_model=AssessmentOut)
    def review_assessment(
        assessment_id: int, review: AssessmentReviewIn, session: SessionDep
    ) -> AssessmentOut:
        assessment = session.get(ImpactAssessmentRecord, assessment_id)
        if assessment is None:
            raise HTTPException(404, "Assessment not found")
        assessment.status = review.status
        assessment.reviewer_note = review.note
        assessment.reviewed_at = datetime.now(UTC)
        session.commit()
        return AssessmentOut.model_validate(assessment)

    @app.get("/assessments/{assessment_id}/export")
    def export_assessment(assessment_id: int, session: SessionDep):
        """The assessment as a Markdown document."""
        assessment = session.get(ImpactAssessmentRecord, assessment_id)
        if assessment is None:
            raise HTTPException(404, "Assessment not found")
        analysis = session.get(AnalysisRecord, assessment.analysis_id)
        update = session.get(Update, analysis.update_id)
        return PlainTextResponse(
            to_markdown(update, analysis, assessment),
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="impact_assessment_{update.id}.md"'
            },
        )

    @app.get("/export")
    def export(
        session: SessionDep,
        f: FiltersDep,
        format: Literal["csv", "json"] = "csv",
    ):
        """Export filtered updates with final labels (reviewer corrections applied)."""
        _, rows = filtered_rows(session, f)
        records = []
        for update, analysis in rows:
            labels = final_labels(analysis)
            records.append(
                {
                    "id": update.id,
                    "source": update.source,
                    "source_type": update.source_type,
                    "published_date": update.published_date.isoformat()
                    if update.published_date
                    else None,
                    "title": update.title,
                    "url": update.url,
                    "topic": labels.get("topic"),
                    "product_type": labels.get("product_type"),
                    "therapeutic_areas": "; ".join(labels.get("therapeutic_areas", [])),
                    "rare_disease": labels.get("rare_disease"),
                    "relevance": labels.get("relevance"),
                    "labelling_impact": labels.get("labelling_impact"),
                    "labelling_documents": "; ".join(
                        labels.get("labelling_documents", [])
                    ),
                    "action_owners": "; ".join(labels.get("action_owners", [])),
                    "watchlist_matches": "; ".join(portfolio_items(labels)),
                    "summary": " ".join(
                        p["claim"] for p in labels.get("summary_points", [])
                    ),
                    "review_status": analysis.review_status if analysis else None,
                    "model": analysis.model if analysis else None,
                }
            )
        if format == "json":
            return records
        buffer = io.StringIO()
        pd.DataFrame(records).to_csv(buffer, index=False)
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="regintel_{stamp}.csv"'
            },
        )

    return app


app = create_app()
