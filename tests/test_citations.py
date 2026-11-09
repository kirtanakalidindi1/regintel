from regintel.llm.citations import quote_in_source, verify_points

SOURCE = """Summary: Healthcare professionals should advise male patients.
## Advice for healthcare professionals
- Discuss the potential risk with male patients.
Reason for recall: Failed dissolution specifications."""


def test_exact_quote_is_supported():
    assert quote_in_source("Failed dissolution specifications.", SOURCE)


def test_quote_survives_case_whitespace_and_smart_quotes():
    assert quote_in_source("discuss the  potential risk\nwith male patients", SOURCE)
    assert quote_in_source(
        "Healthcare professionals should advise male patients", SOURCE
    )


def test_bullet_markers_are_ignored():
    assert quote_in_source("- Discuss the potential risk with male patients.", SOURCE)


def test_paraphrase_is_not_supported():
    assert not quote_in_source("Doctors must warn men about the risk.", SOURCE)


def test_empty_quote_is_not_supported():
    assert not quote_in_source("   ", SOURCE)


def test_verify_points_adds_flags():
    points = verify_points(
        [
            {"claim": "a", "quote": "Failed dissolution"},
            {"claim": "b", "quote": "made up"},
        ],
        SOURCE,
    )
    assert [p["supported"] for p in points] == [True, False]
