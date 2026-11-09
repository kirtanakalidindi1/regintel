"""Check that every quoted passage really appears in the source text."""

import re

_QUOTE_CHARS = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
)


def normalize(text: str) -> str:
    """Lower-case, unify quote marks and dashes, and collapse whitespace."""
    text = text.translate(_QUOTE_CHARS).lower()
    text = re.sub(r"^[-#\s]+", "", text, flags=re.MULTILINE)  # list/heading markers
    return re.sub(r"\s+", " ", text).strip().strip(".")


def quote_in_source(quote: str, source: str) -> bool:
    q = normalize(quote)
    return bool(q) and q in normalize(source)


def verify_points(points: list[dict], source: str) -> list[dict]:
    """Return the points with a `supported` flag added to each."""
    return [{**p, "supported": quote_in_source(p["quote"], source)} for p in points]
