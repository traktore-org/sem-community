"""#1213 — the setup check a new user sees.

Two new users (#1051, #1103) could not finish setup: SEM guessed a sensor
wrong and they could not fix it there. Setup now shows the found values as
watts, and asks one plain question only when SEM is not sure of the grid
meter. "I don't know" is always an answer, and a prefilled picker sent back
unchanged pins nothing.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management import config_flow as cf
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)
from custom_components.solar_energy_management.setup_check import (
    ASK_GUESSED, ASK_MISSING, SetupCheck, answer_updates,
    build_setup_check, fmt_w,
)

ROOT = Path(__file__).resolve().parents[1]


class _Hass:
    """Only what the check reads: states with a unit."""

    def __init__(self, values):
        self.states = SimpleNamespace(get=lambda eid: (
            SimpleNamespace(state=str(values[eid][0]),
                            attributes={"unit_of_measurement": values[eid][1]})
            if eid in values else None))
        self.config = SimpleNamespace(language="en")


def _cfg(**kw):
    cfg = EnergyDashboardConfig()
    cfg.has_solar = cfg.has_grid = True
    cfg.solar_power = "sensor.pv"
    cfg.solar_power_list = ["sensor.pv"]
    cfg.grid_import_power = "sensor.meter"
    cfg.battery_power = "sensor.batt"
    cfg.battery_power_list = ["sensor.batt"]
    cfg.battery_soc = "sensor.soc"
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


HOME = {"sensor.pv": (4152, "W"), "sensor.meter": (310, "W"),
        "sensor.batt": (1.45, "kW"), "sensor.soc": (64, "%")}


# ── what is shown ──────────────────────────────────────────────────────────

def test_all_from_the_dashboard_asks_nothing():
    check = build_setup_check(_Hass(HOME), _cfg())
    assert check.ask is None
    assert check.grid_from == "dashboard"
    assert check.battery_w == pytest.approx(1450)          # kW read as W
    assert check.soc == 64


def test_a_guessed_grid_meter_is_asked_about():
    cfg = _cfg()
    cfg.derived_power = {"grid": "sensor.meter"}
    check = build_setup_check(_Hass(HOME), cfg)
    assert check.ask == ASK_GUESSED


def test_no_grid_power_opens_the_picker():
    check = build_setup_check(_Hass(HOME), _cfg(grid_import_power=None))
    assert check.ask == ASK_MISSING


def test_a_meter_that_reads_plus_while_sending_is_not_questioned():
    """Huawei's meter reads + while sending. At night with an idle battery
    a + reading must not make setup doubt a correct install: setup claims
    no direction, so it has nothing to doubt."""
    values = {"sensor.pv": (0, "W"), "sensor.meter": (-800, "W"),
              "sensor.batt": (0, "W"), "sensor.soc": (40, "%")}
    assert build_setup_check(_Hass(values), _cfg()).ask is None


def test_a_dashboard_pair_is_read_as_bought_minus_sent():
    values = dict(HOME, **{"sensor.in": (0, "W"), "sensor.out": (900, "W")})
    check = build_setup_check(_Hass(values), _cfg(
        grid_import_power=None, grid_power_from="sensor.in",
        grid_power_to="sensor.out"))
    assert check.ask is None
    assert check.grid_w == -900


def test_the_other_meter_is_offered_only_when_there_is_one():
    proposals = {"grid_import_power_sensor": {"entity": "sensor.meter2"}}
    cfg = _cfg()
    cfg.derived_power = {"grid": "sensor.meter"}
    check = build_setup_check(_Hass(dict(HOME, **{"sensor.meter2": (0, "W")})),
                              cfg, proposals)
    assert check.other_grid == "sensor.meter2"
    assert "other" in check.answers()
    same = build_setup_check(_Hass(HOME), cfg,
                             {"grid_import_power_sensor": {"entity": "sensor.meter"}})
    assert same.other_grid is None and "other" not in same.answers()


def test_the_other_meter_is_named_even_when_the_grid_reading_was_not_guessed():
    """(#1213 review) The "other" option can appear on the plain
    buying/sending screen too — it must still say which sensor and what
    it reads, not just on the ASK_GUESSED screen."""
    check = SetupCheck(grid_entity="sensor.meter", grid_w=900, grid_from="dashboard",
                       other_grid="sensor.meter2", other_grid_w=150, ask=None)
    why = cf.SolarEnergyManagementConfigFlow._why(dict(cf._SETUP_WORDS_EN), check)
    assert "sensor.meter2" in why
    assert "150" in why


# ── what an answer writes ──────────────────────────────────────────────────

def _guessed(w):
    return SetupCheck(grid_entity="sensor.meter", grid_w=w, grid_from="guessed",
                      other_grid="sensor.meter2", ask=ASK_GUESSED)


@pytest.mark.parametrize("w, answer, invert", [
    (1240, "buying", True),     # + while buying: turn it around
    (1240, "sending", False),
    (-1240, "buying", False),
    (-1240, "sending", True),
])
def test_buying_or_sending_sets_the_sign(w, answer, invert):
    out = answer_updates(_guessed(w), answer)
    assert out.get("grid_sign_invert", False) is invert
    # a confirmed guess pins nothing: it keeps following the Energy dashboard
    assert "grid_power_sensor" not in out


def test_a_sign_answer_is_dropped_when_the_user_picks_another_grid_sensor():
    """The answer was about the meter shown. A different pick in the same
    submit must not be turned around by it."""
    check = _guessed(1240)
    assert answer_updates(check, "buying") == {"grid_sign_invert": True}
    assert answer_updates(check, "buying", picked_grid="sensor.other") == {}
    assert answer_updates(check, "buying", picked_grid="sensor.meter") == {
        "grid_sign_invert": True}


def test_a_quiet_meter_cannot_tell_the_sign():
    check = _guessed(12)
    assert check.answers() == ("keep", "other", "unknown")
    assert answer_updates(check, "keep") == {}
    assert "grid_sign_invert" not in answer_updates(check, "buying")


def test_other_and_unknown():
    assert answer_updates(_guessed(800), "other") == {
        "grid_power_sensor": "sensor.meter2"}
    assert answer_updates(_guessed(800), "unknown") == {}


def test_watts_read_as_a_person_reads_them():
    assert fmt_w(4152.4) == "4 152 W"
    assert fmt_w(-310) == "310 W"
    assert fmt_w(None) == "?"


# ── the flow ───────────────────────────────────────────────────────────────

def _flow(values, cfg, proposals=None):
    flow = cf.SolarEnergyManagementConfigFlow()
    flow.hass = _Hass(values)
    patches = [
        patch.object(cf, "read_energy_dashboard_config", AsyncMock(return_value=cfg)),
        patch("custom_components.solar_energy_management.hardware_detection."
              "propose_energy_sources", return_value=proposals or {}),
        patch.object(cf, "_power_sensor_selector", return_value=MagicMock()),
        patch.object(cf, "discover_inverter_from_registry", return_value=None),
    ]
    return flow, patches


async def _run(flow, patches, first_input=None, then=None):
    for p in patches:
        p.start()
    try:
        result = await flow.async_step_user(first_input)
        if then is not None:
            step = getattr(flow, f"async_step_{result['step_id']}")
            result = await step(then)
        return result
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_the_common_case_is_one_screen_and_one_click():
    flow, patches = _flow(HOME, _cfg())
    shown = await _run(flow, patches)
    assert shown["step_id"] == "user"
    assert shown["description_placeholders"]["grid"] == "310 W"
    assert shown["description_placeholders"]["battery"] == "1\u202f450 W, 64 %"
    flow, patches = _flow(HOME, _cfg())
    done = await _run(flow, patches, first_input={})
    assert done["step_id"] == "hardware"
    assert "grid_power_sensor" not in flow._data
    assert "grid_sign_invert" not in flow._data


@pytest.mark.asyncio
async def test_the_question_carries_its_answer_into_the_install():
    cfg = _cfg()
    cfg.derived_power = {"grid": "sensor.meter"}
    values = dict(HOME, **{"sensor.meter": (1240, "W")})
    flow, patches = _flow(values, cfg)
    asked = await _run(flow, patches)
    assert asked["step_id"] == "check_grid"
    flow, patches = _flow(values, cfg)
    done = await _run(flow, patches, then={"grid_answer": "buying"})
    assert done["step_id"] == "hardware"
    assert flow._data["grid_sign_invert"] is True
    assert "grid_power_sensor" not in flow._data


@pytest.mark.asyncio
async def test_a_missing_meter_never_blocks_setup():
    flow, patches = _flow(HOME, _cfg(grid_import_power=None))
    done = await _run(flow, patches, then={})
    assert done["step_id"] == "hardware"
    assert not flow._data.get("grid_power_sensor")


@pytest.mark.asyncio
async def test_an_unchanged_picker_pins_nothing_and_a_changed_one_does():
    picks = {"own_sensors": {"solar_production_sensor": "sensor.pv",
                             "grid_power_sensor": "sensor.meter",
                             "battery_power_sensor": "sensor.other_batt",
                             "battery_soc_sensor": "sensor.soc"}}
    flow, patches = _flow(HOME, _cfg())
    await _run(flow, patches, first_input=picks)
    assert flow._data["battery_power_sensor"] == "sensor.other_batt"
    assert "solar_production_sensor" not in flow._data
    assert "grid_power_sensor" not in flow._data


# ── every answer is readable in every language ─────────────────────────────

def test_every_answer_and_word_is_translated():
    answers = {"buying", "sending", "keep", "other", "unknown"}
    words = set(cf._SETUP_WORDS_EN)
    for path in [ROOT / "strings.json", *sorted((ROOT / "translations").glob("*.json"))]:
        sel = json.loads(path.read_text(encoding="utf-8"))["selector"]
        assert set(sel["setup_grid_answer"]["options"]) == answers, path.name
        assert set(sel["setup_words"]["options"]) == words, path.name


def test_the_preselected_answer_writes_nothing():
    """HA preselects the first option of a required choice. Submit pressed
    without reading must not turn a sign around."""
    for w in (1240, -1240, 12):
        check = _guessed(w)
        assert answer_updates(check, check.answers()[0]) == {}, w


# ── the docs the setup points to ───────────────────────────────────────────

def _slug(heading: str) -> str:
    import re
    h = re.sub(r"[^\w\s-]", "", heading.strip().lower())
    return re.sub(r"\s", "-", h)


def _slugs(path: Path) -> set:
    import re
    return {_slug(m.group(1))
            for m in re.finditer(r"^#{1,6}\s+(.+)$", path.read_text(encoding="utf-8"), re.M)}


def test_every_setup_link_and_picture_in_the_docs_exists():
    """The manifest's documentation link (HA's "?" in the setup dialog), the
    Quick Start and the Setup Guide point at Step 1 by anchor, and Step 1
    shows its screens as pictures. A renamed heading or a missing image
    fails here."""
    import re
    docs = ROOT / "docs"
    guide = docs / "SETUP_GUIDE.md"
    targets = []
    manifest = json.loads((ROOT / "manifest.json").read_text())["documentation"]
    targets.append(manifest.split("/blob/develop/docs/")[1])
    for doc in (docs / "QUICK_START.md", guide, docs / "TROUBLESHOOTING.md"):
        for m in re.finditer(r"\]\((SETUP_GUIDE\.md)?(#[\w-]+|SETUP_GUIDE\.md#[\w-]+)\)",
                             doc.read_text(encoding="utf-8")):
            link = m.group(2)
            if doc == guide and not link.startswith("#"):
                continue
            targets.append("SETUP_GUIDE.md" + link.replace("SETUP_GUIDE.md", ""))
    assert len(targets) >= 6
    slugs = _slugs(guide)
    for t in targets:
        anchor = t.split("#", 1)[1]
        assert anchor in slugs, f"no heading for #{anchor}"
    pics = re.findall(r"\]\((screenshots/setup-flow/[^)]+)\)",
                      guide.read_text(encoding="utf-8"))
    assert {"01a-step1-one-question.png", "01b-step1-pick-grid.png",
            "04-sensor-sources-check.png"} <= {Path(p).name for p in pics}
    for p in pics:
        assert (docs / p).is_file(), p
