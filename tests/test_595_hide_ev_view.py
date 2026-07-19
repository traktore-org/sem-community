"""#595/#614 — absent hardware is hidden: the EV tab is removed when no
charger is configured, and the diagram cards get show_ev/show_battery
flags so they don't draw ghost nodes."""

from unittest.mock import MagicMock

from custom_components.solar_energy_management.features.dashboard_generator import (
    DashboardGenerator,
)


def _generator(full_config, *, ed_has_battery=None):
    hass = MagicMock()
    entry = MagicMock()
    entry.data = full_config
    entry.options = {}
    hass.config_entries.async_entries.return_value = [entry]
    # Real dict — the #614 coordinator lookup iterates hass.data[DOMAIN].
    hass.data = {}
    if ed_has_battery is not None:
        coord = MagicMock()
        coord._energy_dashboard_config = MagicMock(has_battery=ed_has_battery)
        from custom_components.solar_energy_management.const import DOMAIN
        hass.data[DOMAIN] = {"entry": coord}
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
    gen._prune_ev_view_if_no_charger(tpl)
    paths = [v["path"] for v in tpl["views"]]
    assert "ev" not in paths
    assert paths == ["home", "battery"]  # others untouched


def test_ev_tab_kept_when_charger_configured():
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]})
    tpl = _template()
    gen._prune_ev_view_if_no_charger(tpl)
    assert "ev" in [v["path"] for v in tpl["views"]]


def test_ev_tab_kept_with_legacy_power_sensor():
    gen = _generator({"ev_charging_power_sensor": "sensor.keba_power"})
    tpl = _template()
    gen._prune_ev_view_if_no_charger(tpl)
    assert "ev" in [v["path"] for v in tpl["views"]]


def test_no_entries_is_a_noop():
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []
    gen = DashboardGenerator(hass)
    tpl = _template()
    gen._prune_ev_view_if_no_charger(tpl)
    assert len(tpl["views"]) == 3  # unchanged


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
    gen._prune_ev_view_if_no_charger(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    flow = tpl["views"][1]["cards"][0]  # EV view pruned → energy shifts up
    assert diagram["show_ev"] is False
    assert flow["show_ev"] is False


def test_diagram_cards_untouched_when_charger_configured():
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]})
    tpl = _template_with_diagram_cards()
    gen._prune_ev_view_if_no_charger(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert "show_ev" not in diagram


def test_battery_flag_injected_when_no_battery():
    """#614 — battery sibling of the ghost-node class: no battery sensor
    anywhere → diagram cards get show_battery:false (independent of EV)."""
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]})  # EV yes, battery no
    tpl = _template_with_diagram_cards()
    gen._prune_ev_view_if_no_charger(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert diagram["show_battery"] is False
    assert "show_ev" not in diagram          # EV present → untouched
    assert "ev" in [v["path"] for v in tpl["views"]]  # EV view kept


def test_battery_flag_not_injected_with_soc_sensor():
    gen = _generator({"battery_soc_sensor": "sensor.batt_soc"})
    tpl = _template_with_diagram_cards()
    gen._prune_ev_view_if_no_charger(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert "show_battery" not in diagram
    assert diagram["show_ev"] is False       # no charger → EV hidden


def test_battery_flag_not_injected_with_ed_detected_battery():
    """A battery detected only via the Energy Dashboard config (no explicit
    sensor keys) must NOT be hidden — same test K-Flow uses."""
    gen = _generator({}, ed_has_battery=True)
    tpl = _template_with_diagram_cards()
    gen._prune_ev_view_if_no_charger(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert "show_battery" not in diagram


def test_both_flags_when_solar_only_install():
    gen = _generator({})
    tpl = _template_with_diagram_cards()
    gen._prune_ev_view_if_no_charger(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert diagram["show_ev"] is False
    assert diagram["show_battery"] is False
