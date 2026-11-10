"""Pure helper functions for the Streamlit app (no Streamlit imports, so they are testable)."""

import html
import re

LABEL_NAMES = {
    "drug_enforcement": "FDA drug recall",
    "device_enforcement": "FDA device recall",
    "drug_safety_update": "MHRA Drug Safety Update",
    "medical_safety_alert": "MHRA safety alert",
    "smpc": "SmPC",
    "pil": "PIL",
    "us_label": "US label",
    "ifu": "IFU",
    "cell_gene_therapy": "Cell or gene therapy",
    "quality_supply": "Quality and supply",
    "healthcare_professionals": "Healthcare professionals",
}

RELEVANCE_LABELS = {
    "high": "High relevance",
    "medium": "Medium relevance",
    "low": "Low relevance",
}
REVIEW_LABELS = {
    "pending": "Needs review",
    "approved": "Approved",
    "corrected": "Corrected",
    "rejected": "Rejected",
}


def pretty(value: str | None) -> str:
    """'infectious_disease' -> 'Infectious disease'."""
    if not value:
        return "—"
    return LABEL_NAMES.get(value, value.replace("_", " ").capitalize())


def chip(text: str, kind: str = "neutral") -> str:
    """A small HTML label. `kind` maps to a CSS class in the app's stylesheet."""
    return f'<span class="ri-chip ri-chip-{kind}">{html.escape(text)}</span>'


def quote_pattern(quote: str) -> re.Pattern | None:
    """Regex that finds a quote in the source despite case, spacing and bullet differences."""
    words = re.findall(r"\w+", quote)
    if not words:
        return None
    return re.compile(r"\W+".join(re.escape(w) for w in words), re.IGNORECASE)


def highlight_quotes(source: str, quotes: list[str], numbered: bool = False) -> str:
    """Return HTML-safe source text with each found quote wrapped in <mark>.

    With numbered=True, each highlight carries the number of the claim it supports, so
    claim 2 in the summary points to the passage marked 2.
    """
    spans: list[tuple[int, int, int]] = []
    for number, quote in enumerate(quotes, start=1):
        pattern = quote_pattern(quote)
        match = pattern.search(source) if pattern else None
        if match:
            spans.append((*match.span(), number))

    # Merge overlapping spans, keeping every claim number that points at the merged passage
    spans.sort()
    merged: list[list] = []
    for start, end, number in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2].append(number)
        else:
            merged.append([start, end, [number]])

    out, cursor = [], 0
    for start, end, numbers in merged:
        out.append(html.escape(source[cursor:start]))
        badge = (
            f'<sup class="ri-cite">{",".join(str(n) for n in sorted(numbers))}</sup>'
            if numbered
            else ""
        )
        out.append(f"<mark>{html.escape(source[start:end])}</mark>{badge}")
        cursor = end
    out.append(html.escape(source[cursor:]))
    return "<br>".join(_style_line(line) for line in "".join(out).split("\n"))


def _style_line(line: str) -> str:
    """Show stored '## ' headings as headings and '- ' items as bullets."""
    if line.startswith("## "):
        return f'<span class="ri-doc-h">{line[3:]}</span>'
    if line.startswith("- "):
        return f"&bull;&nbsp;{line[2:]}"
    return line
