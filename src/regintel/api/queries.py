"""Shared query logic: each update joined to its most recent analysis, with filters."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from regintel.db.models import AnalysisRecord, Update


@dataclass
class UpdateFilters:
    source: str | None = None
    source_type: str | None = None
    topic: str | None = None
    relevance: str | None = None
    product_type: str | None = None
    therapeutic_area: str | None = None
    review_status: str | None = None
    analysed: bool | None = None
    q: str | None = None
    date_from: date | None = None
    date_to: date | None = None


def latest_analysis_ids():
    """Subquery: the newest analysis id for each update."""
    return (
        select(
            AnalysisRecord.update_id, func.max(AnalysisRecord.id).label("analysis_id")
        )
        .group_by(AnalysisRecord.update_id)
        .subquery()
    )


def filtered_rows(
    session: Session, f: UpdateFilters, limit: int | None = None, offset: int = 0
):
    """Return (total, [(Update, AnalysisRecord | None), ...]) newest first."""
    latest = latest_analysis_ids()
    stmt = (
        select(Update, AnalysisRecord)
        .outerjoin(latest, latest.c.update_id == Update.id)
        .outerjoin(AnalysisRecord, AnalysisRecord.id == latest.c.analysis_id)
    )

    conditions = []
    if f.source:
        conditions.append(Update.source == f.source)
    if f.source_type:
        conditions.append(Update.source_type == f.source_type)
    if f.date_from:
        conditions.append(Update.published_date >= f.date_from)
    if f.date_to:
        conditions.append(Update.published_date <= f.date_to)
    if f.q:
        pattern = f"%{f.q}%"
        conditions.append(
            or_(Update.title.ilike(pattern), Update.body_text.ilike(pattern))
        )
    if f.topic:
        conditions.append(AnalysisRecord.topic == f.topic)
    if f.relevance:
        conditions.append(AnalysisRecord.relevance == f.relevance)
    if f.product_type:
        conditions.append(AnalysisRecord.product_type == f.product_type)
    if f.review_status:
        conditions.append(AnalysisRecord.review_status == f.review_status)
    if f.analysed is True:
        conditions.append(AnalysisRecord.id.is_not(None))
    elif f.analysed is False:
        conditions.append(AnalysisRecord.id.is_(None))
    stmt = stmt.where(*conditions).order_by(
        Update.published_date.desc().nulls_last(), Update.id.desc()
    )

    rows = [(u, a) for u, a in session.execute(stmt)]
    # Therapeutic areas are stored as a JSON list, so filter them in Python. This keeps the
    # query identical on SQLite and Postgres, and the dataset is small.
    if f.therapeutic_area:
        rows = [
            (u, a) for u, a in rows if a and f.therapeutic_area in a.therapeutic_areas
        ]

    total = len(rows)
    end = None if limit is None else offset + limit
    return total, rows[offset:end]


def final_labels(analysis: AnalysisRecord | None) -> dict:
    """The labels to report: reviewer corrections override the AI's where present."""
    if analysis is None:
        return {}
    labels = {
        "topic": analysis.topic,
        "product_type": analysis.product_type,
        "therapeutic_areas": analysis.therapeutic_areas,
        "relevance": analysis.relevance,
        "summary_points": analysis.summary_points,
    }
    if analysis.review_status == "corrected" and analysis.reviewed_output:
        labels.update(analysis.reviewed_output)
    return labels
