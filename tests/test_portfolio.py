import json

import pytest

from regintel.portfolio import describe_portfolio, load_portfolio, portfolio_names


def test_repo_watchlist_loads_with_unique_names():
    names = portfolio_names()
    assert len(names) == len(set(names)) >= 5


def test_duplicate_names_are_rejected(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"items": [{"name": "A"}, {"name": "A"}]}))
    with pytest.raises(ValueError):
        load_portfolio(str(path))


def test_description_includes_examples():
    text = describe_portfolio(
        [
            {
                "name": "PARP inhibitors",
                "area": "oncology",
                "examples": ["olaparib", "niraparib"],
            }
        ]
    )
    assert text == "- PARP inhibitors (oncology): e.g. olaparib, niraparib"
