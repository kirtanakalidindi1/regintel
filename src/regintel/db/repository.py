"""Storing updates with deduplication."""

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from regintel.db.models import AnalysisRecord, ImpactAssessmentRecord, Update
from regintel.ingest.schema import NormalizedUpdate


def upsert_updates(
    session: Session, records: Iterable[NormalizedUpdate]
) -> dict[str, int]:
    """Insert new records, refresh changed ones, skip identical ones.

    A record's identity is (source, source_type, source_id). If a record with that
    identity exists but its content hash differs (e.g. a recall moved from Ongoing to
    Terminated), the stored row is updated rather than duplicated.
    """
    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "duplicates_in_batch": 0}
    seen: set[tuple[str, str, str]] = set()

    for rec in records:
        key = (rec.source, rec.source_type, rec.source_id)
        if key in seen:
            counts["duplicates_in_batch"] += 1
            continue
        seen.add(key)

        existing = session.scalar(
            select(Update).where(
                Update.source == rec.source,
                Update.source_type == rec.source_type,
                Update.source_id == rec.source_id,
            )
        )
        new_hash = rec.content_hash

        if existing is None:
            session.add(
                Update(
                    source=rec.source,
                    source_type=rec.source_type,
                    source_id=rec.source_id,
                    title=rec.title,
                    url=rec.url,
                    published_date=rec.published_date,
                    body_text=rec.body_text,
                    raw=rec.raw,
                    content_hash=new_hash,
                )
            )
            counts["inserted"] += 1
        elif existing.content_hash != new_hash:
            existing.title = rec.title
            existing.url = rec.url
            existing.published_date = rec.published_date
            existing.body_text = rec.body_text
            existing.raw = rec.raw
            existing.content_hash = new_hash
            existing.last_updated_at = datetime.now(UTC)
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1

    session.commit()
    return counts


def updates_needing_analysis(
    session: Session, prompt_version: str, limit: int
) -> list[Update]:
    """Updates with no analysis for this prompt version, or whose content changed since."""
    analysed = aliased(Update)
    current = (
        select(AnalysisRecord.update_id)
        .join(analysed, AnalysisRecord.update_id == analysed.id)
        .where(
            AnalysisRecord.prompt_version == prompt_version,
            AnalysisRecord.source_hash == analysed.content_hash,
        )
    )
    stmt = (
        select(Update)
        .where(Update.id.not_in(current))
        .order_by(Update.published_date.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def save_analysis(session: Session, update: Update, result) -> AnalysisRecord:
    a = result.analysis
    record = AnalysisRecord(
        update_id=update.id,
        model=result.model,
        prompt_version=result.prompt_version,
        source_hash=update.content_hash,
        topic=a.topic,
        product_type=a.product_type,
        therapeutic_areas=list(a.therapeutic_areas),
        relevance=a.relevance,
        relevance_rationale=a.relevance_rationale,
        summary_points=result.summary_points,
        all_citations_supported=result.all_citations_supported,
        rare_disease=a.rare_disease,
        labelling_impact=a.labelling_impact,
        labelling_documents=list(a.labelling_documents),
        action_owners=list(a.action_owners),
        portfolio_impacts=[p.model_dump() for p in a.portfolio_impacts],
    )
    session.add(record)
    session.commit()
    return record


def save_assessment(
    session: Session, analysis: AnalysisRecord, result
) -> ImpactAssessmentRecord:
    record = ImpactAssessmentRecord(
        analysis_id=analysis.id,
        model=result.model,
        prompt_version=result.prompt_version,
        content=result.content,
        all_citations_supported=result.all_citations_supported,
    )
    session.add(record)
    session.commit()
    return record


def latest_assessment(
    session: Session, analysis_id: int
) -> ImpactAssessmentRecord | None:
    return session.scalar(
        select(ImpactAssessmentRecord)
        .where(ImpactAssessmentRecord.analysis_id == analysis_id)
        .order_by(ImpactAssessmentRecord.id.desc())
        .limit(1)
    )
