"""The product and drug-class watchlist that updates are checked against."""

import json
from functools import lru_cache
from pathlib import Path

from regintel.config import PORTFOLIO_PATH


@lru_cache
def load_portfolio(path: str | None = None) -> list[dict]:
    data = json.loads(Path(path or PORTFOLIO_PATH).read_text(encoding="utf-8"))
    items = data["items"]
    names = [item["name"] for item in items]
    if len(names) != len(set(names)):
        raise ValueError("Portfolio item names must be unique")
    return items


def portfolio_names(path: str | None = None) -> list[str]:
    return [item["name"] for item in load_portfolio(path)]


def describe_portfolio(items: list[dict]) -> str:
    return "\n".join(
        f"- {item['name']} ({item.get('area', 'unspecified')}): "
        f"e.g. {', '.join(item.get('examples', []))}"
        for item in items
    )
