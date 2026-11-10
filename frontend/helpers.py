"""Pure helper functions for the Streamlit app (no Streamlit imports, so they are testable)."""

import html
import re

LABEL_NAMES = {
    "drug_enforcement": "FDA drug recall",
    "device_enforcement": "FDA device recall",
    "drug_safety_update": "MHRA Drug Safety Update",
    "medical_safety_alert": "MHRA safety alert",
}

RELEVANCE_BADGES = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟢 Low"}
REVIEW_BADGES = {
    "pending": "⏳ Pending",
    "approved": "✅ Approved",
    "corrected": "✏️ Corrected",
    "rejected": "❌ Rejected",
}


def pretty(value: str | None) -> str:
    """'infectious_disease' -> 'Infectious disease'."""
    if not value:
        return "—"
    return LABEL_NAMES.get(value, value.replace("_", " ").capitalize())


def quote_pattern(quote: str) -> re.Pattern | None:
    """Regex that finds a quote in the source despite case, spacing and bullet differences."""
    words = re.findall(r"\w+", quote)
    if not words:
        return None
    return re.compile(r"\W+".join(re.escape(w) for w in words), re.IGNORECASE)


def highlight_quotes(source: str, quotes: list[str]) -> str:
    """Return HTML-safe source text with each found quote wrapped in <mark>."""
    spans: list[tuple[int, int]] = []
    for quote in quotes:
        pattern = quote_pattern(quote)
        match = pattern.search(source) if pattern else None
        if match:
            spans.append(match.span())

    # Merge overlapping spans, then build the escaped output
    spans.sort()
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    out, cursor = [], 0
    for start, end in merged:
        out.append(html.escape(source[cursor:start]))
        out.append(f"<mark>{html.escape(source[start:end])}</mark>")
        cursor = end
    out.append(html.escape(source[cursor:]))
    return "".join(out).replace("\n", "<br>")
