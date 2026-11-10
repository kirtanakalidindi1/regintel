import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontend"))

from helpers import chip, highlight_quotes, pretty


def test_pretty_labels():
    assert pretty("infectious_disease") == "Infectious disease"
    assert pretty("drug_enforcement") == "FDA drug recall"
    assert pretty("smpc") == "SmPC"
    assert pretty(None) == "—"


def test_chip_escapes_text():
    assert chip("A<B", "high") == '<span class="ri-chip ri-chip-high">A&lt;B</span>'


def test_highlight_handles_case_spacing_and_bullets():
    source = "## Advice\n- Discuss the potential risk\nwith male patients."
    out = highlight_quotes(source, ["discuss the potential risk with male patients"])
    assert "<mark>Discuss the potential risk<br>with male patients</mark>" in out
    assert out.startswith('<span class="ri-doc-h">Advice</span><br>&bull;&nbsp;<mark>')


def test_highlight_escapes_html_and_skips_missing_quotes():
    out = highlight_quotes("Use <5 mg & stop.", ["5 mg", "not present"])
    assert out == "Use &lt;<mark>5 mg</mark> &amp; stop."


def test_numbered_highlights_match_claim_order():
    out = highlight_quotes(
        "first fact. second fact.", ["second fact", "first fact"], True
    )
    assert out == (
        '<mark>first fact</mark><sup class="ri-cite">2</sup>. '
        '<mark>second fact</mark><sup class="ri-cite">1</sup>.'
    )


def test_overlapping_quotes_are_merged_with_both_numbers():
    out = highlight_quotes("alpha beta gamma", ["alpha beta", "beta gamma"], True)
    assert out == '<mark>alpha beta gamma</mark><sup class="ri-cite">1,2</sup>'
