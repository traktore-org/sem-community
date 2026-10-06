"""#1025 A5 — battery boost for one charge.

"Tonight, put the battery into the car down to 40 %." A one-off per charger,
started by a service (the card's button), never persisted — a restart ends
it — and never a change to the standing permission:

* consent: an active boost for THIS charger is treated like the open morning
  window (#892) — the pack may feed the car below the solar gate;
* floor: the boost's own (D4: defaulting to the morning drain floor, 50 %),
  on both sides — what the charger is offered, and what the battery is
  allowed to give;
* it ends when the car unplugs, the charger's mode changes, the pack reaches
  the floor, or the permission is switched off — each with its reason;
* it is refused while ``may_assist_ev`` is explicitly off (D5).
"""
from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator.battery_boost import (
    BatteryBoost,
    BoostRefused,
    boost_end_reason,
    boost_remaining_kwh,
    start_boost,
)

ROOT = Path(__file__).resolve().parents[1]
ZRH = ZoneInfo("Europe/Zurich")
EVENING = datetime(2026, 10, 9, 20, 30, tzinfo=ZRH)
KEBA = {"id": "keba", "charge_mode": "min_plus_solar"}


def _boost(floor=40.0, mode="min_plus_solar"):
    return BatteryBoost(charger_id="keba", floor_soc=floor, mode=mode,
                        started=EVENING)


# ── Starting ─────────────────────────────────────────────────────────────

def test_a_plugged_car_starts_a_boost_with_its_floor():
    b = start_boost("keba", KEBA, {}, mode="min_plus_solar", connected=True,
                    floor_soc=40, now=EVENING)
    assert (b.charger_id, b.floor_soc, b.mode) == ("keba", 40.0,
                                                   "min_plus_solar")


def test_the_floor_defaults_to_the_morning_drain_floor():
    """D4: its own value on the card, defaulting to
    battery_morning_drain_floor_soc (50 %)."""
    b = start_boost("keba", KEBA, {}, mode="min_plus_solar", connected=True,
                    now=EVENING)
    assert b.floor_soc == 50.0
    b = start_boost("keba", KEBA, {"battery_morning_drain_floor_soc": 35},
                    mode="min_plus_solar", connected=True, now=EVENING)
    assert b.floor_soc == 35.0


def test_an_explicit_no_outranks_a_button():
    """D5: the standing permission off — for the install or this charger —
    refuses the boost, and says why."""
    with pytest.raises(BoostRefused) as err:
        start_boost("keba", {**KEBA, "ev_battery_may_assist": False}, {},
                    mode="min_plus_solar", connected=True, now=EVENING)
    assert err.value.key == "battery_boost_not_permitted"
    with pytest.raises(BoostRefused):
        start_boost("keba", KEBA,
                    {"battery_permissions": {"may_assist_ev": False}},
                    mode="min_plus_solar", connected=True, now=EVENING)


def test_an_unplugged_car_cannot_be_boosted():
    with pytest.raises(BoostRefused) as err:
        start_boost("keba", KEBA, {}, mode="min_plus_solar", connected=False,
                    now=EVENING)
    assert err.value.key == "battery_boost_not_connected"


@pytest.mark.parametrize("floor", [-5, 101, "soon"])
def test_a_floor_that_is_no_percentage_is_refused(floor):
    with pytest.raises(BoostRefused) as err:
        start_boost("keba", KEBA, {}, mode="min_plus_solar", connected=True,
                    floor_soc=floor, now=EVENING)
    assert err.value.key == "battery_boost_bad_floor"


# ── Ending ───────────────────────────────────────────────────────────────

def _end(**kw):
    args = {"connected": True, "mode": "min_plus_solar", "soc": 80.0,
            "may_assist": True}
    args.update(kw)
    return boost_end_reason(_boost(), **args)


def test_it_runs_while_nothing_has_changed():
    assert _end() is None
    assert _end(connected=None) is None      # unknown is not an unplug
    assert _end(soc=None) is None            # an unread SOC is not a floor


@pytest.mark.parametrize("change, reason", [
    ({"connected": False}, "unplugged"),
    ({"mode": "solar_only"}, "mode changed"),
    ({"soc": 40.0}, "battery at its floor"),
    ({"soc": 38.5}, "battery at its floor"),
    ({"may_assist": False}, "permission off"),
])
def test_each_end_has_its_reason(change, reason):
    assert _end(**change) == reason


def test_the_remaining_boost_energy():
    """(SOC − floor) × measured capacity, never negative."""
    assert boost_remaining_kwh(80.0, 40.0, 10.0) == pytest.approx(4.0)
    assert boost_remaining_kwh(39.0, 40.0, 10.0) == 0.0
    assert boost_remaining_kwh(80.0, 40.0, 0.0) == 0.0


# ── Consent and floor in the deciders ─────────────────────────────────────

def _charger_view(*, soc, boost_for="keba", floor=40.0, surplus_w=0.0,
                  may_assist=True):
    from custom_components.solar_energy_management.coordinator import decide
    fleet = SimpleNamespace(
        battery_may_assist_ev=may_assist, battery_soc=soc,
        battery_soc_known=True, buffer_soc=50.0, auto_start_soc=90.0,
        priority_soc=30.0, battery_assist_max_power_w=4000.0,
        battery_assist_min_surplus_w=1200.0, dynamic_floor_pct=None,
        assist_committed_w=0.0, ev_morning_window_open=False,
        forecast_spending_enabled=False, battery_spendable_kwh=0.0,
        boost_charger_id=boost_for, boost_floor_soc=floor)
    view = SimpleNamespace(fleet=fleet, mode="min_plus_solar",
                           power=SimpleNamespace(charger_id="keba"))
    return decide, view, surplus_w


@pytest.fixture
def _no_surplus(monkeypatch):
    from custom_components.solar_energy_management.coordinator import decide
    monkeypatch.setattr(decide, "self_consumption_surplus_w", lambda v: 0.0)


def test_after_sunset_the_boost_offers_the_pack(_no_surplus):
    """Plugged, SOC 80 %, floor 40 %: assist offered after sunset."""
    decide, view, _ = _charger_view(soc=80.0)
    _, assist = decide._battery_assist_split(view)
    assert assist > 0


def test_without_a_boost_the_evening_stays_closed(_no_surplus):
    decide, view, _ = _charger_view(soc=80.0, boost_for=None, floor=None)
    _, assist = decide._battery_assist_split(view)
    assert assist == 0.0


def test_a_boost_for_another_charger_is_not_this_ones(_no_surplus):
    decide, view, _ = _charger_view(soc=80.0, boost_for="zoe")
    _, assist = decide._battery_assist_split(view)
    assert assist == 0.0


def test_the_boost_goes_below_the_buffer_to_its_own_floor(_no_surplus):
    """Buffer 50 %, boost floor 40 %: at 45 % the pack still feeds the car;
    at 39 % it does not."""
    decide, view, _ = _charger_view(soc=45.0)
    assert decide._battery_assist_split(view)[1] > 0
    decide, view, _ = _charger_view(soc=39.0)
    assert decide._battery_assist_split(view)[1] == 0.0


def test_the_permission_off_still_wins_in_the_decider(_no_surplus):
    decide, view, _ = _charger_view(soc=80.0, may_assist=False)
    assert decide._battery_assist_split(view)[1] == 0.0


def test_the_battery_side_allows_the_boost_floor():
    from custom_components.solar_energy_management.coordinator.charger_types import (
        BatteryView,
    )
    fields = {f.name for f in BatteryView.__dataclass_fields__.values()}
    assert "battery_boost_floor_soc" in fields


# ── Wiring ───────────────────────────────────────────────────────────────

def _kwargs_of(path, callee):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    out = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call)
                and getattr(n.func, "id", getattr(n.func, "attr", None)) == callee):
            out.append({k.arg for k in n.keywords if k.arg})
    return out


def test_both_producers_of_the_fleet_context_carry_the_boost():
    """Two producers of one context is a known bug class here (#955,
    #1003): the boost must ride both."""
    for path in ("coordinator/build_view.py", "coordinator/coordinator.py"):
        sites = _kwargs_of(path, "FleetContext")
        assert sites, path
        for kw in sites:
            assert {"boost_charger_id", "boost_floor_soc"} <= kw, (path, kw)


def test_the_services_exist():
    import yaml
    described = yaml.safe_load((ROOT / "services.yaml").read_text(encoding="utf-8"))
    assert {"start_battery_boost", "stop_battery_boost"} <= set(described)
    registered = set()
    tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "async_register"
                and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant)):
            registered.add(n.args[1].value)
    assert {"start_battery_boost", "stop_battery_boost"} <= registered


def test_the_refusals_are_translated():
    import json
    for lang in sorted((ROOT / "translations").glob("*.json")):
        ex = json.loads(lang.read_text(encoding="utf-8")).get("exceptions", {})
        for key in ("battery_boost_not_permitted", "battery_boost_not_connected",
                    "battery_boost_bad_floor"):
            assert key in ex and ex[key].get("message"), (lang.name, key)


# ── The coordinator's one boost ──────────────────────────────────────────

def _coordinator(charge_mode="min_plus_solar"):
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.hass = None
    c.config = {"battery_capacity_kwh": 10.0,
                "ev_chargers": [{"id": "keba", "charge_mode": charge_mode,
                                 "ev_connected_sensor": "binary_sensor.plug"}]}
    c._battery_boost = None
    c._battery_boost_ended = None
    return c


def _power(connected=True, soc=80.0):
    return SimpleNamespace(ev_connected_per_charger={"keba": connected},
                           ev_connected=connected, battery_soc=soc,
                           battery_soc_known=True)


def test_the_boost_runs_until_the_pack_is_at_its_floor():
    c = _coordinator()
    c._tick_battery_boost(_power())
    c.start_battery_boost("keba", 40)
    c._tick_battery_boost(_power(soc=60.0))
    status = c.battery_boost_status(_power(soc=60.0))
    assert status["active"] and status["remaining_kwh"] == pytest.approx(2.0)
    c._tick_battery_boost(_power(soc=40.0))
    assert c._battery_boost is None
    status = c.battery_boost_status(_power(soc=40.0))
    assert status == {"active": False, "last_end": c._battery_boost_ended}
    assert c._battery_boost_ended["reason"] == "battery at its floor"


def test_a_mode_change_ends_it():
    c = _coordinator()
    c._tick_battery_boost(_power())
    c.start_battery_boost("keba")
    c.config["ev_chargers"][0]["charge_mode"] = "solar_only"
    c._tick_battery_boost(_power())
    assert c._battery_boost_ended["reason"] == "mode changed"


def test_a_seen_unplug_refuses_the_start():
    c = _coordinator()
    c._tick_battery_boost(_power(connected=False))
    with pytest.raises(BoostRefused) as err:
        c.start_battery_boost("keba")
    assert err.value.key == "battery_boost_not_connected"


def test_an_unknown_charger_is_not_found():
    c = _coordinator()
    with pytest.raises(BoostRefused) as err:
        c.start_battery_boost("ghost")
    assert err.value.key == "device_not_found"


def test_the_battery_view_gets_the_floor():
    kws = _kwargs_of("coordinator/coordinator.py", "BatteryView")
    assert kws and all("battery_boost_floor_soc" in k for k in kws), kws


def _battery_view(*, soc, boost_floor=None, window=False):
    from custom_components.solar_energy_management.coordinator.charger_types import (
        BatteryRuntime, BatteryView, FleetContext,
    )
    cfg = {"battery_max_discharge_power": 4000, "battery_max_charge_power_w": 5000,
           "battery_mode": "auto", "battery_morning_drain_floor_soc": 50.0}
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc), config=cfg,
        fleet=FleetContext(), charging_state="idle", ev_charging=True,
        ev_connected=True, home_consumption_w=800.0, scheduler_decision=None,
        sink_verdicts={}, morning_window_open=window,
        battery_boost_floor_soc=boost_floor)


def test_the_battery_gives_to_the_boost_floor():
    from custom_components.solar_energy_management.coordinator.charger_types import (
        BatteryIntent,
    )
    from custom_components.solar_energy_management.coordinator.decide_battery import (
        decide_battery,
    )
    d = decide_battery(_battery_view(soc=45.0, boost_floor=40.0))
    assert d.intent is BatteryIntent.NORMAL and "battery boost" in d.reason
    assert "40%" in d.reason
    d = decide_battery(_battery_view(soc=39.0, boost_floor=40.0))
    assert "battery boost" not in d.reason


def test_with_the_morning_window_open_too_the_deeper_floor_holds():
    from custom_components.solar_energy_management.coordinator.decide_battery import (
        decide_battery,
    )
    d = decide_battery(_battery_view(soc=45.0, boost_floor=40.0, window=True))
    assert "down to 40%" in d.reason
    d = decide_battery(_battery_view(soc=55.0, boost_floor=60.0, window=True))
    assert "morning window" in d.reason
    assert "down to 50%" in d.reason
