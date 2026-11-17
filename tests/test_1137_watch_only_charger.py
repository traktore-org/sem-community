"""#1137 — "Detected hardware: tesla_wall_connector — no role matched".

The roles did match. A Tesla Wall Connector reports power, plug, charging
and session energy, but it has no control at all: no current number, no
start/stop, no charge mode. With no car integration that has its own charge
control, the near miss carries those roles, ``missing == ["control"]`` and
no offer. The card read every near miss without an offer as "entities
present, no role matched" and offered a prefilled "please report" issue.

The card now says what was found and that SEM has no control it can drive
(dashboard/card/src/util/detect-rows.js ``nearMissAction`` → ``watch``).
These pins hold the backend half of that contract — the fields the card
reads — and the copy the card shows. The card's own decision is pinned in
dashboard/card/test/detect-rows.test.js.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .integrations_rig.rig import crawl, load_capture, replay

_ROOT = Path(__file__).resolve().parent.parent
_KEYS = ("config_detect_watch_only", "config_detect_watch_only_help",
         "config_detect_choose_vehicle_help")


def _wall_connector(rep):
    (wc,) = [n for n in rep["near_misses"]
             if n["platform"] == "tesla_wall_connector"]
    return wc


def _card_says_watch(m) -> bool:
    """The card's rule (detect-rows.js ``isWatchOnlyCharger``), restated."""
    offer = m.get("suggested_charger") or {}
    return (not offer.get("id") and m.get("missing") == ["control"]
            and bool(m.get("charger_roles")))


async def test_the_wall_connector_alone_is_a_charger_with_no_control(hass):
    await replay(hass, load_capture("tesla_wall_connector"))
    wc = _wall_connector(crawl(hass))
    assert {"power", "plug", "charging"} <= set(wc["charger_roles"])
    assert wc["missing"] == ["control"]
    assert not (wc["suggested_charger"] or {}).get("id")
    assert _card_says_watch(wc)


async def test_with_one_car_it_is_an_offer_not_watch_only(hass):
    """Vacuity twin: R4 pairs the one car, and the row becomes an offer."""
    await replay(hass, load_capture("tesla_wall_connector"))
    await replay(hass, load_capture("tesla_fleet"))
    wc = _wall_connector(crawl(hass))
    assert wc["suggested_charger"].get("id")
    assert not _card_says_watch(wc)


async def test_with_two_cars_the_row_names_the_choice(hass):
    await replay(hass, load_capture("tessie"), suffix="_car2")
    await replay(hass, load_capture("tesla_wall_connector"))
    await replay(hass, load_capture("tesla_fleet"))
    wc = _wall_connector(crawl(hass))
    assert _card_says_watch(wc)
    assert len(wc["choose_vehicle"]) == 2


def test_a_device_with_no_roles_still_reads_as_no_role_matched():
    assert not _card_says_watch({"missing": ["control"], "suggested_charger": {}})
    assert not _card_says_watch({"charger_roles": ["plug"],
                                 "missing": ["power reading", "control"]})


def test_the_copy_is_in_every_language_and_names_the_roles():
    data = json.loads((_ROOT / "dashboard" / "translations.json")
                      .read_text(encoding="utf-8"))
    for lang, strings in data.items():
        for key in _KEYS:
            assert strings.get(key), (lang, key)
        assert "{roles}" in strings["config_detect_watch_only"], lang
    en = " ".join(data["en"][k] for k in _KEYS)
    assert not re.search(r"no role matched|please report", en, re.I), en


