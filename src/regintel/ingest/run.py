"""Command-line entry point: fetch recent updates and store them.

Usage:
    uv run python -m regintel.ingest.run --days 30
    uv run python -m regintel.ingest.run --days 90 --source mhra
"""

import argparse
import logging
from datetime import date, timedelta

from regintel import config
from regintel.db.database import get_engine, get_sessionmaker, init_db
from regintel.db.repository import upsert_updates
from regintel.ingest import fda, mhra
from regintel.ingest.schema import NormalizedUpdate

log = logging.getLogger("regintel.ingest")


def collect_fda(since: date, max_records: int) -> dict[str, list[NormalizedUpdate]]:
    batches = {}
    for source_type in fda.ENFORCEMENT_ENDPOINTS:
        raw_records = fda.fetch_enforcement(
            source_type, since, max_records=max_records, api_key=config.OPENFDA_API_KEY
        )
        records = []
        for raw in raw_records:
            try:
                records.append(fda.normalize_enforcement(raw, source_type))
            except ValueError as exc:
                log.warning("Skipping FDA record: %s", exc)
        batches[f"FDA {source_type}"] = records
    return batches


def collect_mhra(since: date, max_records: int) -> dict[str, list[NormalizedUpdate]]:
    return {
        f"MHRA {doc_type}": mhra.fetch_and_normalize(
            doc_type, since, max_records=max_records
        )
        for doc_type in mhra.DOCUMENT_TYPES
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Ingest regulatory updates into the database"
    )
    parser.add_argument(
        "--days", type=int, default=30, help="How many days back to fetch"
    )
    parser.add_argument(
        "--max-records", type=int, default=500, help="Cap per source type"
    )
    parser.add_argument("--source", choices=["all", "fda", "mhra"], default="all")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    engine = get_engine()
    init_db(engine)
    Session = get_sessionmaker(engine)
    since = date.today() - timedelta(days=args.days)

    batches: dict[str, list[NormalizedUpdate]] = {}
    if args.source in ("all", "fda"):
        batches |= collect_fda(since, args.max_records)
    if args.source in ("all", "mhra"):
        batches |= collect_mhra(since, args.max_records)

    for name, records in batches.items():
        with Session() as session:
            counts = upsert_updates(session, records)
        log.info("%s: %s", name, counts)


if __name__ == "__main__":
    main()
