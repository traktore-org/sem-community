"""#595/#614/#923 — absent hardware is hidden.

The EV tab is removed when no charger is configured (#595 — the EV tab is
the control surface for a charger SEM was told about), the Battery tab when
the battery module is ABSENT (#923), and the diagram cards get show_ev /
show_battery flags so they don't draw ghost nodes (#614).

Since #923 the battery verdict is not recomputed here: the generator asks
the coordinator for the verdict its platforms were built with
(``setup_presence``), so the dashboard and the entity set cannot disagree.
Which configuration means "battery" is the oracle's to test
(tests/test_923_install_modules.py)."""

from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)
from custom_components.solar_energy_management.features.dashboard_generator import (
    DashboardGenerator,
)

PRESENT = {m: Presence.PRESENT for m in Module}
ABSENT = {m: Presence.ABSENT for m in Module}
NO_BATTERY = {**PRESENT, Module.BATTERY: Presence.ABSENT}


def _generator(full_config, presence=None):
    hass = MagicMock()
    entry = MagicMock()
    entry.data = full_config
    entry.options = {}
    if presence is not None:
        entry.runtime_data.setup_presence = presence
    hass.config_entries.async_entries.return_value = [entry]
    hass.data = {}
    return DashboardGenerator(hass)


def _template():
    return {"views": [
        {"title": "Home", "path": "home"},
        {"title": "EV", "path": "ev"},
        {"title": "Battery", "path": "battery"},
    ]}


def test_ev_tab_removed_when_no_charger():
    gen = _generator({})  # no ev_chargers, no ev_charging_power_sensor
    tpl = _template()
    gen._prune_absent_modules(tpl)
    paths = [v["path"] for v in tpl["views"]]
    assert "ev" not in paths
    assert paths == ["home", "battery"]  # battery verdict UNKNOWN → kept


def test_ev_tab_kept_when_charger_configured():
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]})
    tpl = _template()
    gen._prune_absent_modules(tpl)
    assert "ev" in [v["path"] for v in tpl["views"]]


def test_ev_tab_kept_with_legacy_power_sensor():
    gen = _generator({"ev_charging_power_sensor": "sensor.keba_power"})
    tpl = _template()
    gen._prune_absent_modules(tpl)
    assert "ev" in [v["path"] for v in tpl["views"]]


def test_no_entries_is_a_noop():
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []
    gen = DashboardGenerator(hass)
    tpl = _template()
    gen._prune_absent_modules(tpl)
    assert len(tpl["views"]) == 3  # unchanged


def test_battery_tab_removed_when_the_battery_is_absent():
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]}, NO_BATTERY)
    tpl = _template()
    gen._prune_absent_modules(tpl)
    assert [v["path"] for v in tpl["views"]] == ["home", "ev"]


def test_battery_tab_kept_while_the_verdict_is_unknown():
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]})
    tpl = _template()
    gen._prune_absent_modules(tpl)
    assert "battery" in [v["path"] for v in tpl["views"]]


def _template_with_diagram_cards():
    return {"views": [
        {"title": "Home", "path": "home", "cards": [
            {"type": "vertical-stack", "cards": [
                {"type": "custom:sem-system-diagram-card", "entity_prefix": "sensor.sem_"},
            ]},
        ]},
        {"title": "EV", "path": "ev", "cards": []},
        {"title": "Energy", "path": "energy", "cards": [
            {"type": "custom:sem-flow-card", "entity_prefix": "sensor.sem_"},
        ]},
    ]}


def test_diagram_cards_get_show_ev_false_when_no_charger():
    """#595 follow-up — the reporter's circled complaint: the system
    overview diagram still drew an EV node. Both SEM diagram cards must
    receive show_ev:false, including when nested in stacks."""
    gen = _generator({})
    tpl = _template_with_diagram_cards()
    gen._prune_absent_modules(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    flow = tpl["views"][1]["cards"][0]  # EV view pruned → energy shifts up
    assert diagram["show_ev"] is False
    assert flow["show_ev"] is False


def test_diagram_cards_untouched_when_everything_is_present():
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]}, PRESENT)
    tpl = _template_with_diagram_cards()
    gen._prune_absent_modules(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert "show_ev" not in diagram
    assert "show_battery" not in diagram


def test_battery_flag_injected_when_the_battery_is_absent():
    """#614 — battery sibling of the ghost-node class."""
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]}, NO_BATTERY)
    tpl = _template_with_diagram_cards()
    gen._prune_absent_modules(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert diagram["show_battery"] is False
    assert "show_ev" not in diagram          # EV present → untouched
    assert "ev" in [v["path"] for v in tpl["views"]]


def test_battery_flag_not_injected_when_the_battery_is_present():
    gen = _generator({}, {**ABSENT, Module.BATTERY: Presence.PRESENT})
    tpl = _template_with_diagram_cards()
    gen._prune_absent_modules(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert "show_battery" not in diagram
    assert diagram["show_ev"] is False       # no charger → EV hidden


def test_battery_flag_not_injected_while_unknown():
    """A battery-less verdict must never come from an incomplete read."""
    gen = _generator({})
    tpl = _template_with_diagram_cards()
    gen._prune_absent_modules(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert "show_battery" not in diagram


def test_both_flags_when_solar_only_install():
    gen = _generator({}, ABSENT)
    tpl = _template_with_diagram_cards()
    gen._prune_absent_modules(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert diagram["show_ev"] is False
    assert diagram["show_battery"] is False
