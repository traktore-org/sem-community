"""#1168 Part A — the crawler names a price sensor by its own declared key.

Discovery only. The tariff code still finds its price sensor by brand name
(Part B was declined: it reads live prices on every Tibber, Amber, Octopus,
Nord Pool and aWATTar home). This part adds one read role, ``import_price``,
for the integrations that declare a key for it, and pins what the others do
NOT declare so a later reader does not think they were forgotten:

- Amber declares ``current`` and ``forecasts`` for import, feed-in and
  controlled load alike, so no key tells its directions apart.
- Octopus Energy, aWATTar and the Nord Pool the roster lists declare no
  translation keys at all.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.consts import (
    integration_roster as roster,
)
from custom_components.solar_energy_management.consts import role_lexicon as lex


class TestTheRole:
    @pytest.mark.parametrize("domain, key", [
        ("tibber", "electricity_price"),
        ("tibber_prices", "current_interval_price"),
        ("entsoe", "current_price"),
    ])
    def test_a_declared_price_key_is_the_import_price(self, domain, key):
        assert lex.role_for("sensor", key, domain) == "import_price"

    def test_current_price_counts_in_entsoe_only(self):
        # a heat pump, a car or a plug can call its own tariff this too
        for other in ("", "lambda_heat_pumps", "kia_uvo", "nordpool"):
            assert lex.role_for("sensor", "current_price", other) != "import_price"

    @pytest.mark.parametrize("key", [
        "average_price_today", "current_hour_average_price",
        "current_interval_price_level", "current_interval_price_rating",
        "current_interval_price_base", "current_interval_price_rank_today",
        "next_hour_price", "min_price", "max_price", "avg_price",
        "percentage_of_max", "highest_price_time_today",
    ])
    def test_a_near_miss_is_not_the_price(self, key):
        for domain in ("tibber_prices", "entsoe", "tibber"):
            assert lex.role_for("sensor", key, domain) != "import_price"

    def test_a_number_or_a_switch_is_not_a_price_reading(self):
        assert lex.role_for("number", "electricity_price", "tibber") != "import_price"
        assert lex.role_for("switch", "current_price", "entsoe") != "import_price"


class TestTheShippedRoster:
    @pytest.mark.parametrize("domain, key", [
        ("tibber", "electricity_price"),
        ("tibber_prices", "current_interval_price"),
        ("entsoe", "current_price"),
    ])
    def test_the_roster_carries_the_role(self, domain, key):
        body = roster.ROLE_VOCAB[domain]["import_price"]
        assert body["platform"] == "sensor"
        assert body["keys"] == (key,)

    @pytest.mark.parametrize("domain", [
        "amberelectric", "amber", "octopus_energy", "awattar", "nordpool",
    ])
    def test_a_brand_with_no_declared_key_has_no_price_role(self, domain):
        assert "import_price" not in roster.ROLE_VOCAB.get(domain, {})

    def test_no_feed_in_price_role_exists_to_be_guessed(self):
        # no integration declares a distinct feed-in key; do not invent one
        assert not [r for r in {**lex.ROLE_RULES, **lex.READ_ROLE_RULES}
                    if "feed_in" in r and "price" in r]

    def test_the_tariff_code_does_not_use_the_role(self):
        # Part A changes no behaviour: the live price path imports neither
        # the lexicon nor the roster, so it keeps finding prices by brand.
        import ast
        from pathlib import Path

        from custom_components.solar_energy_management.tariff import tariff_provider
        tree = ast.parse(Path(tariff_provider.__file__).read_text(encoding="utf-8"))
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                names.add(n.module or "")
                names.update(a.name for a in n.names)
            elif isinstance(n, ast.Import):
                names.update(a.name for a in n.names)
        assert not [x for x in names if "role_lexicon" in x or "integration_roster" in x]
