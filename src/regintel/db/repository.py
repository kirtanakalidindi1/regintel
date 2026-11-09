"""Storing updates with deduplication."""

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from regintel.db.models import Update
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
