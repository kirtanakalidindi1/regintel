import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontend"))

from helpers import highlight_quotes, pretty


def test_pretty_labels():
    assert pretty("infectious_disease") == "Infectious disease"
    assert pretty("drug_enforcement") == "FDA drug recall"
    assert pretty(None) == "—"


def test_highlight_handles_case_spacing_and_bullets():
    source = "## Advice\n- Discuss the potential risk\nwith male patients."
    out = highlight_quotes(source, ["discuss the potential risk with male patients"])
    assert "<mark>Discuss the potential risk<br>with male patients</mark>" in out


def test_highlight_escapes_html_and_skips_missing_quotes():
    out = highlight_quotes("Use <5 mg & stop.", ["5 mg", "not present"])
    assert out == "Use &lt;<mark>5 mg</mark> &amp; stop."


def test_overlapping_quotes_are_merged():
    out = highlight_quotes("alpha beta gamma", ["alpha beta", "beta gamma"])
    assert out == "<mark>alpha beta gamma</mark>"
