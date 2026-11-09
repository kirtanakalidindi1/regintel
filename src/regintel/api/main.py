"""FastAPI backend for RegIntel.

Run locally:
    uv run uvicorn regintel.api.main:app --reload
Interactive docs at http://127.0.0.1:8000/docs
"""

import io
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Annotated, Literal

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from regintel.api.queries import UpdateFilters, filtered_rows, final_labels
from regintel.api.schemas import (
    AnalysisOut,
    ReviewIn,
    UpdateDetail,
    UpdateList,
    UpdateSummary,
)
from regintel.db.database import get_engine, get_sessionmaker, init_db
from regintel.db.models import AnalysisRecord, Update
from regintel.llm.taxonomy import PRODUCT_TYPES, RELEVANCE, THERAPEUTIC_AREAS, TOPICS


def create_app(engine: Engine | None = None) -> FastAPI:
    engine = engine or get_engine()
    init_db(engine)

    app = FastAPI(title="RegIntel API", version="0.1.0")
    app.state.sessionmaker = get_sessionmaker(engine)

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
        q: Annotated[str | None, Query(description="Search title and text")] = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> UpdateFilters:
        return UpdateFilters(
            source,
            source_type,
            topic,
            relevance,
            product_type,
            therapeutic_area,
            review_status,
            analysed,
            q,
            date_from,
            date_to,
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
            "review_statuses": ["pending", "approved", "corrected", "rejected"],
        }

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
        analysed = session.scalar(
            select(func.count(func.distinct(AnalysisRecord.update_id)))
        )
        return {
            "updates": sum(n for _, _, n in by_source),
            "analysed_updates": analysed,
            "by_source": [
                {"source": s, "source_type": t, "count": n} for s, t, n in by_source
            ],
            "by_review_status": {status: n for status, n in by_review},
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
                    "relevance": labels.get("relevance"),
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
