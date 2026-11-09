"""Command-line entry point: analyze stored updates with Claude.

Usage:
    uv run python -m regintel.llm.run --limit 5
"""

import argparse
import logging

import anthropic

from regintel import config
from regintel.db.database import get_engine, get_sessionmaker, init_db
from regintel.db.repository import save_analysis, updates_needing_analysis
from regintel.llm.analyze import PROMPT_VERSION, AnalysisError, analyze_update

log = logging.getLogger("regintel.llm")


def run(session, client, model: str, limit: int) -> dict[str, int]:
    counts = {"analyzed": 0, "failed": 0, "citations_all_supported": 0}
    for update in updates_needing_analysis(session, PROMPT_VERSION, limit):
        try:
            result = analyze_update(
                client,
                model,
                title=update.title,
                source=update.source,
                source_type=update.source_type,
                body_text=update.body_text,
            )
        except (AnalysisError, anthropic.APIError) as exc:
            log.warning("Update %s (%s) failed: %s", update.id, update.source_id, exc)
            counts["failed"] += 1
            continue
        save_analysis(session, update, result)
        counts["analyzed"] += 1
        counts["citations_all_supported"] += result.all_citations_supported
        log.info(
            "Update %s: %s / %s / %s",
            update.id,
            result.analysis.topic,
            result.analysis.relevance,
            result.analysis.therapeutic_areas,
        )
    return counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Analyze stored updates with Claude")
    parser.add_argument(
        "--limit", type=int, default=5, help="Max updates to analyze this run"
    )
    parser.add_argument("--model", default=config.ANTHROPIC_MODEL)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    if not config.ANTHROPIC_API_KEY:
        raise SystemExit("ANTHROPIC_API_KEY is not set. Add it to your .env file.")

    engine = get_engine()
    init_db(engine)
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    with get_sessionmaker(engine)() as session:
        counts = run(session, client, args.model, args.limit)
    log.info("Done: %s", counts)


if __name__ == "__main__":
    main()
