"""Command-line entry point: fetch recent updates and store them.

Usage:
    uv run python -m regintel.ingest.run --days 30
"""

import argparse
import logging
from datetime import date, timedelta

from regintel import config
from regintel.db.database import get_engine, get_sessionmaker, init_db
from regintel.db.repository import upsert_updates
from regintel.ingest import fda

log = logging.getLogger("regintel.ingest")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Ingest regulatory updates into the database"
    )
    parser.add_argument(
        "--days", type=int, default=30, help="How many days back to fetch"
    )
    parser.add_argument("--max-records", type=int, default=500, help="Cap per source")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    engine = get_engine()
    init_db(engine)
    Session = get_sessionmaker(engine)
    since = date.today() - timedelta(days=args.days)

    for source_type in fda.ENFORCEMENT_ENDPOINTS:
        raw_records = fda.fetch_enforcement(
            source_type,
            since,
            max_records=args.max_records,
            api_key=config.OPENFDA_API_KEY,
        )
        records = []
        for raw in raw_records:
            try:
                records.append(fda.normalize_enforcement(raw, source_type))
            except ValueError as exc:
                log.warning("Skipping record: %s", exc)

        with Session() as session:
            counts = upsert_updates(session, records)
        log.info("%s: %s", source_type, counts)


if __name__ == "__main__":
    main()
