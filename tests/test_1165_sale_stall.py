"""#1165 — Force discharge never ended when the pack stops early.

#1131 puts Force discharge back on Auto at the reserve. Some inverters stop
a sale at their own lower level (30 % while SEM's reserve is 20 %), so the
pack never got there: the mode stayed on, and the next day's sun was sold
the same way.

A sale is also done when the pack sends no more: at most 100 W in or out
for 15 minutes, its level not falling, while SEM's sale is on and asks for
at least one step — and the home buys at least 100 W from the grid with no
sun. An export limit holds back only what goes out, and a home that buys
sends nothing out; a hybrid inverter full with sun has no room for the
pack. So an export limit or the sun can never end the mode.

Links, each driven for real:

* ``sale_stall_read`` / ``sale_stall_step`` / ``manual_mode_done`` — the
  pure rule and its window;
* ``SEMCoordinator._finish_manual_battery_modes`` — on a real config entry
  and the real select platform, with the adapter's own "sale landed" flag
  and the power the actuator last sent it;
* ``actuate_battery`` records what it SENT, and ``_run_battery_pipeline``
  hands over the home's grid and sun only when they are measurements.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import textwrap
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
    BatteryRuntime,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    FORCED_CHARGE_STEP_W,
    MANUAL_CHARGE_STALL_GAP_S,
    MANUAL_CHARGE_STALL_S,
    MANUAL_CHARGE_STALL_W,
    MANUAL_SALE_STALL_IMPORT_W,
    MANUAL_SALE_STALL_SUN_W,
    charge_stall_step,
    manual_mode_done,
    sale_stall_read,
    sale_stall_site,
    sale_stall_step,
)
from custom_components.solar_energy_management.consts.core import (
    BATTERY_SOC_STEP_CONFIRM_READS as READS,
)
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)
from custom_components.solar_energy_management.tests.test_1164_force_charge_stall import (  # noqa: E501
    _Adapter,
    _Stop,
    _coordinator,
    _decision,
    _entry,
    _selects,
    _shows,
    clock,  # noqa: F401 — the fixture
)

_HAS_PHACC = importlib.util.find_spec("pytest_homeassistant_custom_component") is not None

#: Night: the home buys 400 W, no sun.
_NIGHT = (400.0, 0.0)
_SALE = dict(soc_read=True, power_read=True, asked_w=5000.0, sem_selling=True,
             site=_NIGHT)


# ── 1. The rule ────────────────────────────────────────────────────────────

class TestTheRule:
    def test_a_pack_stopped_at_30_at_night_is_a_stall_read(self):
        assert sale_stall_read(30.0, 0.0, **_SALE) is True

    @pytest.mark.parametrize("power_w", [-2500.0, -MANUAL_CHARGE_STALL_W - 1,
                                         MANUAL_CHARGE_STALL_W + 1])
    def test_a_pack_that_moves_power_still_sells(self, power_w):
        assert sale_stall_read(30.0, power_w, **_SALE) is False

    @pytest.mark.parametrize("power_w", [-MANUAL_CHARGE_STALL_W, -40.0,
                                         MANUAL_CHARGE_STALL_W])
    def test_a_trickle_or_standby_draw_is_no_more(self, power_w):
        assert sale_stall_read(30.0, power_w, **_SALE) is True

    @pytest.mark.parametrize("why,site", [
        ("the sun feeds the home: an export limit may hold the pack",
         (0.0, 3000.0)),
        ("another pack feeds the home: an export limit may hold this one",
         (0.0, 0.0)),
        ("the home buys, but a hybrid inverter full with sun has no room",
         (2000.0, 9000.0)),
        ("just under the import", (MANUAL_SALE_STALL_IMPORT_W - 1, 0.0)),
        ("just over the sun", (400.0, MANUAL_SALE_STALL_SUN_W + 1)),
        ("the grid or sun is no measurement", None),
    ])
    def test_no_stall_unless_the_home_buys_with_no_sun(self, why, site):
        assert sale_stall_read(30.0, 0.0, **{**_SALE, "site": site}) is False, why

    def test_the_thresholds_are_100_w(self):
        # A standby draw is no "home that buys"; a dull day's sun is sun.
        assert (MANUAL_SALE_STALL_IMPORT_W, MANUAL_SALE_STALL_SUN_W) == (100.0, 100.0)
        assert sale_stall_read(30.0, 0.0, **{**_SALE, "site": (60.0, 0.0)}) is False
        assert sale_stall_read(30.0, 0.0, **{**_SALE, "site": (400.0, 150.0)}) is False

    def test_the_edges_are_a_stall_read(self):
        site = (MANUAL_SALE_STALL_IMPORT_W, MANUAL_SALE_STALL_SUN_W)
        assert sale_stall_read(30.0, 0.0, **{**_SALE, "site": site}) is True

    @pytest.mark.parametrize("change", [
        {"soc_read": False}, {"power_read": False}, {"sem_selling": None},
        {"sem_selling": False}, {"asked_w": 0.0},
        {"asked_w": FORCED_CHARGE_STEP_W - 1}])
    def test_no_stall_without_every_reading_and_a_sale_asked(self, change):
        assert sale_stall_read(30.0, 0.0, **{**_SALE, **change}) is False

    def test_no_stall_on_a_missing_value(self):
        assert sale_stall_read(None, 0.0, **_SALE) is False
        assert sale_stall_read(30.0, None, **_SALE) is False

    @pytest.mark.parametrize("limit_w", [0.0, 99.0, FORCED_CHARGE_STEP_W - 1])
    def test_no_stall_while_sems_own_limit_holds_the_pack(self, limit_w):
        # (review) A sale does not lift the limit SEM wrote before it (a
        # night hold at 0 W): the pack may be held by SEM, not its inverter.
        assert sale_stall_read(30.0, 0.0, **_SALE, limit_w=limit_w) is False

    @pytest.mark.parametrize("limit_w", [None, -1.0, FORCED_CHARGE_STEP_W,
                                         5000.0])
    def test_no_limit_or_one_of_a_step_or_more_is_no_hold(self, limit_w):
        assert sale_stall_read(30.0, 0.0, **_SALE, limit_w=limit_w) is True

    def _walk(self, start_s, end_s, soc=30.0, step_s=30.0, w=None):
        done = False
        t = start_s
        while t <= end_s:
            w, done = sale_stall_step(w, t, soc, True)
            t += step_s
        return w, done

    def test_the_window_lasts_its_time(self):
        w, done = sale_stall_step(None, 1000.0, 30.0, True)
        assert done is False
        w, done = self._walk(1030.0, 1000.0 + MANUAL_CHARGE_STALL_S - 30, w=w)
        assert done is False
        _, done = sale_stall_step(w, 1000.0 + MANUAL_CHARGE_STALL_S, 30.0, True)
        assert done is True

    def test_a_level_that_falls_starts_the_window_again(self):
        w, _ = self._walk(0.0, MANUAL_CHARGE_STALL_S - 30)
        w, done = sale_stall_step(w, MANUAL_CHARGE_STALL_S, 29.6, True)
        assert done is False
        assert w == (MANUAL_CHARGE_STALL_S, 29.6, MANUAL_CHARGE_STALL_S)

    def test_a_level_that_rises_keeps_the_window(self):
        w, _ = self._walk(0.0, MANUAL_CHARGE_STALL_S - 30)
        _, done = sale_stall_step(w, MANUAL_CHARGE_STALL_S, 30.2, True)
        assert done is True

    def test_one_cycle_without_a_stall_read_ends_the_window(self):
        w, _ = self._walk(0.0, 600.0)
        w, done = sale_stall_step(w, 630.0, 30.0, False)
        assert (w, done) == (None, False)

    def test_a_gap_between_two_checks_starts_the_window_again(self):
        w, _ = self._walk(0.0, 300.0)
        w, done = sale_stall_step(w, 300.0 + MANUAL_CHARGE_STALL_GAP_S + 1,
                                  30.0, True)
        assert done is False and w[0] == 300.0 + MANUAL_CHARGE_STALL_GAP_S + 1

    def test_the_charge_window_still_restarts_on_a_rise_only(self):
        # The two windows share one body: a charge's moves the other way.
        w, _ = charge_stall_step(None, 0.0, 95.0, True)
        w, _ = charge_stall_step(w, 30.0, 94.6, True)
        assert w[0] == 0.0, "a falling level keeps a charge's window"
        w, _ = charge_stall_step(w, 60.0, 95.4, True)
        assert w[0] == 60.0, "a rising level starts a charge's window again"

    def test_a_stall_ends_a_sale_only(self):
        assert manual_mode_done("force_discharge", 30.0, soc_read=True,
                                reserve=20.0, sale_stalled=True) is True
        assert manual_mode_done("force_discharge", 30.0, soc_read=True,
                                reserve=20.0) is False
        assert manual_mode_done("force_charge", 30.0, soc_read=True,
                                reserve=20.0, sale_stalled=True) is False
        assert manual_mode_done("auto", 30.0, soc_read=True,
                                reserve=20.0, sale_stalled=True) is False
        assert manual_mode_done("force_discharge", 30.0, soc_read=False,
                                reserve=20.0, sale_stalled=True) is False


class TestTheSite:
    """``sale_stall_site``: the home's grid import and sun, when they are a
    measurement."""

    def _fleet(self, **kw):
        return SimpleNamespace(**{"grid_import_power": 400.0,
                                  "solar_power": 0.0, "inputs_degraded": False,
                                  "dark_inputs": (),
                                  "home_residual_clamped_w": 0.0, **kw})

    def test_a_measured_home_is_handed_over(self):
        assert sale_stall_site(self._fleet()) == (400.0, 0.0)
        assert sale_stall_site(self._fleet(
            grid_import_power=0.0, solar_power=3000.0)) == (0.0, 3000.0)

    def test_a_balance_that_did_not_close_is_none(self):
        # A grid sign read the wrong way shows an export as import.
        assert sale_stall_site(self._fleet(home_residual_clamped_w=300.0),
                               sun_down=True) is None

    def test_a_dark_solar_read_at_night_is_no_sun(self):
        # (#1165 review 2) Many inverters go offline at night.
        fleet = self._fleet(inputs_degraded=True, dark_inputs=("solar",),
                            solar_power=0.0)
        assert sale_stall_site(fleet, sun_down=True) == (400.0, 0.0)

    @pytest.mark.parametrize("why,dark,sun_down", [
        ("the sun is up", ("solar",), False),
        ("the grid is dark", ("grid",), True),
        ("the grid and the solar are dark", ("grid", "solar"), True),
        ("the battery is dark", ("battery",), True),
        ("dark, but no name", (), True),
    ])
    def test_any_other_dark_read_is_none(self, why, dark, sun_down):
        fleet = self._fleet(inputs_degraded=True, dark_inputs=dark)
        assert sale_stall_site(fleet, sun_down=sun_down) is None, why


# ── 2. The coordinator ends the mode ───────────────────────────────────────

def _seller(landed=True, asked_w=5000.0, limit_w=-1.0):
    # What actuate_battery leaves on an adapter whose sale landed;
    # ``limit_w`` is the discharge limit SEM last wrote (-1: none).
    return SimpleNamespace(_sem_forced_charge=None, _sem_forced_discharge=landed,
                           _sem_charge_asked_w=0.0,
                           _sem_discharge_asked_w=asked_w,
                           last_discharge_limit_w=limit_w)


def _sale_coordinator(hass, entry, slugs, ids):
    coordinator = _coordinator(hass, entry, slugs, ids)
    coordinator._battery_adapters = {bid: _seller() for bid in ids}
    coordinator._manual_sale_stalls = {}
    return coordinator


def _sell(coordinator, clock, packs, minutes, *, site=_NIGHT, step_s=30.0,
          count=None, power_read=True, unread=()):
    """Cycles every ``step_s`` for ``minutes``; ``packs`` is
    {battery id: (SOC, W)}; ``site`` is the home's (grid import W, sun W)."""
    items = [(bid, BatteryRuntime(battery_id=bid, last_known_soc=soc,
                                  last_known_w=w))
             for bid, (soc, w) in packs.items()]
    read = {bid: bid not in unread for bid in packs}
    power = {bid: bool(power_read) for bid in packs}
    for _ in range(int(minutes * 60 / step_s)):
        clock.t += step_s
        SEMCoordinator._finish_manual_battery_modes(
            coordinator, items, read, count or len(items),
            power_read=power, site=site)


_WINDOW_MIN = MANUAL_CHARGE_STALL_S / 60
_SETTLE_MIN = 1 + READS * 30 / 60


@pytest.mark.skipif(not _HAS_PHACC, reason="pytest-homeassistant-custom-component not installed")
class TestAPackThatStopsAt30:
    @pytest.mark.asyncio
    async def test_the_issues_pack_goes_back_to_auto(self, hass, clock):
        entry = _entry(hass, {"battery_mode": "auto", "battery_reserve_soc": 20})
        coordinator = _sale_coordinator(hass, entry, (), ["primary"])
        selects = await _selects(hass, entry)
        await selects["battery_mode"].async_select_option("force_discharge")

        _sell(coordinator, clock, {"primary": (30.0, 0.0)}, _WINDOW_MIN - 1)
        assert entry.options["battery_mode"] == "force_discharge", (
            "14 minutes are not enough")
        _sell(coordinator, clock, {"primary": (30.0, 0.0)}, _SETTLE_MIN)
        assert entry.options["battery_mode"] == "auto"
        assert _shows(selects["battery_mode"]) == "auto"
        assert coordinator._manual_sale_stalls == {}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("why,pack,site,change", [
        ("still selling", (30.0, -2500.0), _NIGHT, {}),
        ("the sun feeds the home (an export limit may hold it)",
         (60.0, 0.0), (0.0, 3000.0), {}),
        ("the home buys, but the sun is up", (60.0, 0.0), (900.0, 1500.0), {}),
        ("the grid or sun is no measurement", (30.0, 0.0), None, {}),
        ("nothing asked", (30.0, 0.0), _NIGHT,
         {"_battery_adapters": {"primary": _seller(asked_w=0.0)}}),
        ("less than one step asked", (30.0, 0.0), _NIGHT,
         {"_battery_adapters": {"primary": _seller(asked_w=FORCED_CHARGE_STEP_W - 1)}}),
        ("a damaged asked power", (30.0, 0.0), _NIGHT,
         {"_battery_adapters": {"primary": _seller(asked_w=True)}}),
        ("an adapter never asked to sell", (30.0, 0.0), _NIGHT,
         {"_battery_adapters": {"primary": SimpleNamespace(
             _sem_forced_charge=None, _sem_forced_discharge=True)}}),
        ("the sale never landed", (30.0, 0.0), _NIGHT,
         {"_battery_adapters": {"primary": _seller(landed=None)}}),
        ("SEM stopped the sale", (30.0, 0.0), _NIGHT,
         {"_battery_adapters": {"primary": _seller(landed=False)}}),
        ("no adapter", (30.0, 0.0), _NIGHT, {"_battery_adapters": {}}),
        ("SEM's own limit holds the pack", (30.0, 0.0), _NIGHT,
         {"_battery_adapters": {"primary": _seller(limit_w=0.0)}}),
        ("a limit that is no number", (30.0, 0.0), _NIGHT,
         {"_battery_adapters": {"primary": _seller(limit_w="n/a")}}),
        ("observer sends nothing", (30.0, 0.0), _NIGHT, {"_observer_mode": True}),
    ])
    async def test_the_mode_stays(self, hass, clock, why, pack, site, change):
        entry = _entry(hass, {"battery_mode": "force_discharge",
                              "battery_reserve_soc": 20})
        coordinator = _sale_coordinator(hass, entry, (), ["primary"])
        for attr, value in change.items():
            setattr(coordinator, attr, value)
        _sell(coordinator, clock, {"primary": pack}, 120, site=site)
        assert entry.options["battery_mode"] == "force_discharge", why

    @pytest.mark.asyncio
    async def test_a_limit_at_the_max_is_no_hold(self, hass, clock):
        # ``command_normal`` writes the max back: that limit holds nothing.
        entry = _entry(hass, {"battery_mode": "force_discharge"})
        coordinator = _sale_coordinator(hass, entry, (), ["primary"])
        coordinator._battery_adapters = {"primary": _seller(limit_w=5000.0)}
        _sell(coordinator, clock, {"primary": (30.0, 0.0)},
              _WINDOW_MIN + _SETTLE_MIN)
        assert entry.options["battery_mode"] == "auto"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("limit_eid,sale_eid,ends", [
        ("number.sale_power", "number.sale_power", True),
        ("number.max_discharge", "number.sale_power", False),
        ("", "", False),
        # a sale by service writes no entity (Huawei with a device id)
        ("number.max_discharge", "", False),
    ])
    async def test_a_limit_on_the_sales_own_register_is_no_hold(
            self, hass, clock, limit_eid, sale_eid, ends):
        # (#1165 review 2) One entity for the limit and the sale power: the
        # sale wrote over the 0 W limit, so it holds nothing (#1175 skips
        # the hand-back there too). Two entities, or none: the limit stands.
        entry = _entry(hass, {"battery_mode": "force_discharge"})
        coordinator = _sale_coordinator(hass, entry, (), ["primary"])
        seller = _seller(limit_w=0.0)
        seller._discharge_control_entity = limit_eid
        seller.sale_setpoint_entity = lambda: sale_eid
        coordinator._battery_adapters = {"primary": seller}
        _sell(coordinator, clock, {"primary": (30.0, 0.0)},
              _WINDOW_MIN + _SETTLE_MIN)
        assert entry.options["battery_mode"] == (
            "auto" if ends else "force_discharge")

    @pytest.mark.asyncio
    async def test_a_dark_power_or_level_read_keeps_the_mode(self, hass, clock):
        entry = _entry(hass, {"battery_mode": "force_discharge"})
        coordinator = _sale_coordinator(hass, entry, (), ["primary"])
        _sell(coordinator, clock, {"primary": (30.0, 0.0)}, 120, power_read=False)
        _sell(coordinator, clock, {"primary": (30.0, 0.0)}, 120, unread={"primary"})
        assert entry.options["battery_mode"] == "force_discharge"

    @pytest.mark.asyncio
    async def test_one_sunny_cycle_starts_the_window_again(self, hass, clock):
        entry = _entry(hass, {"battery_mode": "force_discharge"})
        coordinator = _sale_coordinator(hass, entry, (), ["primary"])
        _sell(coordinator, clock, {"primary": (30.0, 0.0)}, _WINDOW_MIN - 1)
        _sell(coordinator, clock, {"primary": (30.0, 0.0)}, 0.5,
              site=(0.0, 2000.0))
        _sell(coordinator, clock, {"primary": (30.0, 0.0)}, _WINDOW_MIN - 1)
        assert entry.options["battery_mode"] == "force_discharge"
        _sell(coordinator, clock, {"primary": (30.0, 0.0)}, _SETTLE_MIN)
        assert entry.options["battery_mode"] == "auto"

    @pytest.mark.asyncio
    async def test_a_slow_fall_keeps_the_sale_going(self, hass, clock):
        entry = _entry(hass, {"battery_mode": "force_discharge"})
        coordinator = _sale_coordinator(hass, entry, (), ["primary"])
        for soc in (40.0, 39.5, 39.0, 38.5, 38.0, 37.5, 37.0):
            _sell(coordinator, clock, {"primary": (soc, -80.0)}, _WINDOW_MIN - 1)
        assert entry.options["battery_mode"] == "force_discharge"

    @pytest.mark.asyncio
    async def test_a_stopped_pack_on_one_shared_control_waits_for_the_other(
            self, hass, clock):
        entry = _entry(hass, {"battery_mode": "force_discharge",
                              "battery_reserve_soc": 20})
        coordinator = _sale_coordinator(hass, entry, (), ["b1", "b2"])
        _sell(coordinator, clock, {"b1": (30.0, 0.0), "b2": (60.0, -2500.0)}, 60)
        assert entry.options["battery_mode"] == "force_discharge", (
            "b2 still sells: the shared job is not done")
        _sell(coordinator, clock, {"b1": (30.0, 0.0), "b2": (20.0, 0.0)}, 2)
        assert entry.options["battery_mode"] == "auto"

    @pytest.mark.asyncio
    async def test_per_battery_controls_only_the_stopped_pack_moves(
            self, hass, clock):
        entry = _entry(hass, {"battery_modes": ["force_discharge",
                                                "force_discharge"]})
        coordinator = _sale_coordinator(hass, entry, ("b1", "b2"), ["b1", "b2"])
        selects = await _selects(hass, entry)
        _sell(coordinator, clock, {"b1": (30.0, 0.0), "b2": (60.0, -2500.0)}, 20)
        assert entry.options["battery_modes"] == ["auto", "force_discharge"]
        assert _shows(selects["battery_b1_mode"]) == "auto"
        assert _shows(selects["battery_b2_mode"]) == "force_discharge"

    @pytest.mark.asyncio
    async def test_each_pack_answers_with_its_own_flag(self, hass, clock):
        entry = _entry(hass, {"battery_modes": ["force_discharge",
                                                "force_discharge"]})
        coordinator = _sale_coordinator(hass, entry, ("b1", "b2"), ["b1", "b2"])
        coordinator._battery_adapters["b2"] = _seller(landed=None)
        _sell(coordinator, clock, {"b1": (30.0, 0.0), "b2": (30.0, 0.0)}, 20)
        assert entry.options["battery_modes"] == ["auto", "force_discharge"]

    @pytest.mark.asyncio
    async def test_a_cold_start_drops_the_window(self, hass, clock):
        entry = _entry(hass, {"battery_modes": ["force_discharge",
                                                "force_discharge"]})
        coordinator = _sale_coordinator(hass, entry, ("b1", "b2"), ["b1", "b2"])
        _sell(coordinator, clock, {"b1": (30.0, 0.0), "b2": (60.0, -2500.0)},
              _WINDOW_MIN - 1)
        _sell(coordinator, clock, {"primary": (30.0, 0.0)}, 0.5, count=1)
        assert coordinator._manual_sale_stalls == {}
        _sell(coordinator, clock, {"b1": (30.0, 0.0), "b2": (60.0, -2500.0)},
              _WINDOW_MIN - 1)
        assert entry.options["battery_modes"] == ["force_discharge",
                                                  "force_discharge"]

    @pytest.mark.asyncio
    async def test_a_charge_window_is_no_sale_window(self, hass, clock):
        # 14 idle minutes of Force charge at 95 %, then a sale is picked: its
        # own window starts at the pick, not 14 minutes before.
        entry = _entry(hass, {"battery_mode": "force_charge"})
        coordinator = _sale_coordinator(hass, entry, (), ["primary"])
        coordinator._battery_adapters = {"primary": SimpleNamespace(
            _sem_forced_charge=True, _sem_forced_discharge=True,
            _sem_charge_asked_w=5000.0, _sem_discharge_asked_w=5000.0)}
        _sell(coordinator, clock, {"primary": (95.0, 0.0)}, _WINDOW_MIN - 1)
        assert set(coordinator._manual_charge_stalls) == {"primary"}
        selects = await _selects(hass, entry)
        await selects["battery_mode"].async_select_option("force_discharge")
        _sell(coordinator, clock, {"primary": (95.0, 0.0)}, _SETTLE_MIN)
        assert coordinator._manual_charge_stalls == {}
        assert entry.options["battery_mode"] == "force_discharge"

    @pytest.mark.asyncio
    async def test_force_charge_is_not_ended_by_a_home_that_buys(
            self, hass, clock):
        # Below 90 % a pack that takes nothing is no full pack (#1164), the
        # home's grid says nothing about a charge.
        entry = _entry(hass, {"battery_mode": "force_charge"})
        coordinator = _sale_coordinator(hass, entry, (), ["primary"])
        coordinator._battery_adapters = {"primary": SimpleNamespace(
            _sem_forced_charge=True, _sem_forced_discharge=True,
            _sem_charge_asked_w=5000.0, _sem_discharge_asked_w=5000.0)}
        _sell(coordinator, clock, {"primary": (60.0, 0.0)}, 120)
        assert entry.options["battery_mode"] == "force_charge"
        assert coordinator._manual_sale_stalls == {}


# ── 3. What was sent, and the pipeline ─────────────────────────────────────

class _Seller(_Adapter):
    """``_Adapter`` whose sale can fail (``refuse``: ``last_error`` set and
    the intent kept) or answer like Deye (``True``, no intent recorded)."""

    def __init__(self, deye=False):
        super().__init__()
        self.deye = deye

    async def command_force_discharge(self, *a, **kw):
        if self.refuse:
            self.last_error = "write_force_discharge failed"
            return False if self.deye else None
        self.sent.append(("sell",))
        if self.deye:
            return True
        self.last_error = None
        self.last_intent = BatteryIntent.FORCE_DISCHARGE
        return None


@pytest.mark.asyncio
class TestTheActuatorRecordsWhatItSent:
    async def _send(self, adapter, decision, **kw):
        from custom_components.solar_energy_management.coordinator.actuate_battery import (
            actuate_battery,
        )
        await actuate_battery(decision, adapter, **kw)
        return adapter._sem_discharge_asked_w

    @pytest.mark.parametrize("deye", [False, True])
    async def test_a_sale_sent_is_asked(self, deye):
        a = _Seller(deye=deye)
        assert await self._send(a, _decision(BatteryIntent.FORCE_DISCHARGE)) == 3000.0
        assert a.sent == [("sell",)] and a._sem_forced_discharge is True
        assert a._sem_charge_asked_w == 0.0

    @pytest.mark.parametrize("intent", [
        BatteryIntent.STOP_FORCE_DISCHARGE, BatteryIntent.NORMAL,
        BatteryIntent.FORCE_CHARGE, BatteryIntent.OFF])
    async def test_anything_else_asks_for_no_sale(self, intent):
        a = _Seller()
        await self._send(a, _decision(BatteryIntent.FORCE_DISCHARGE))
        assert await self._send(a, _decision(intent)) == 0.0

    async def test_a_yielded_battery_asks_for_nothing(self):
        # (#1079) SEM yields to another party: nothing goes out, so a sale
        # asked before is no longer asked.
        a = _Seller()
        await self._send(a, _decision(BatteryIntent.FORCE_DISCHARGE))
        assert await self._send(a, _decision(BatteryIntent.FORCE_DISCHARGE),
                                yielded=True) == 0.0
        assert a.sent == [("sell",)]

    async def test_observer_asks_for_nothing(self):
        a = _Seller()
        await self._send(a, _decision(BatteryIntent.FORCE_DISCHARGE))
        assert await self._send(a, _decision(BatteryIntent.FORCE_DISCHARGE),
                                observer=True) == 0.0

    @pytest.mark.parametrize("deye", [False, True])
    async def test_a_sale_that_failed_asks_for_nothing(self, deye):
        # The intent from the last cycle still reads FORCE_DISCHARGE.
        a = _Seller(deye=deye)
        await self._send(a, _decision(BatteryIntent.FORCE_DISCHARGE))
        a.refuse = True
        assert await self._send(a, _decision(BatteryIntent.FORCE_DISCHARGE)) == 0.0
        a.refuse = False
        assert await self._send(a, _decision(BatteryIntent.FORCE_DISCHARGE)) == 3000.0

    async def test_an_adapter_that_cannot_sell_is_asked_nothing(self):
        a = _Seller()
        a.supports_forced_discharge = False
        assert await self._send(a, _decision(BatteryIntent.FORCE_DISCHARGE)) == 0.0

    async def test_a_huawei_sale_that_stands_is_asked(self):
        # (review) The real Huawei adapter calls the service once, then
        # repeats without a write. An error from an earlier write must not
        # make the standing sale read as "nothing asked".
        from custom_components.solar_energy_management.tests.test_589_battery_command_honesty import (  # noqa: E501
            _make_huawei,
        )
        a = _make_huawei()
        a._startup_orphan_checked = True
        d = _decision(BatteryIntent.FORCE_DISCHARGE)
        assert await self._send(a, d) == 3000.0
        assert a._hass.services.async_call.await_count == 1
        a._last_error = "write not reflected by number.max_discharge"
        assert await self._send(a, d) == 3000.0
        assert a._hass.services.async_call.await_count == 1, "a repeat, no write"
        assert a.last_error is None

    async def test_a_huawei_sale_that_failed_asks_for_nothing(self):
        from custom_components.solar_energy_management.tests.test_589_battery_command_honesty import (  # noqa: E501
            _make_huawei,
        )
        a = _make_huawei(service_raises=True)
        a._startup_orphan_checked = True
        assert await self._send(a, _decision(BatteryIntent.FORCE_DISCHARGE)) == 0.0
        assert a.last_error is not None


def _readings(**kw):
    from custom_components.solar_energy_management.coordinator.types import (
        PowerReadings,
    )
    pr = PowerReadings(**{"solar_power": 0.0, "grid_power": -400.0,
                          "battery_power": 0.0, "battery_soc": 30.0,
                          "battery_power_read": True, **kw})
    pr.calculate_derived()
    return pr


@pytest.mark.asyncio
class TestThePipeline:
    async def test_a_home_that_buys_at_night_is_handed_over(self, monkeypatch):
        seen = await _pipeline_seen(monkeypatch, _readings())
        assert seen == (400.0, 0.0)

    async def test_the_sun_is_handed_over(self, monkeypatch):
        seen = await _pipeline_seen(monkeypatch, _readings(
            solar_power=3000.0, grid_power=2600.0))
        assert seen == (0.0, 3000.0)

    @pytest.mark.parametrize("why,change", [
        ("a dark steering read", {"inputs_degraded": True}),
        ("a balance that did not close", {"home_residual_clamped_w": 300.0}),
    ])
    async def test_no_measurement_hands_over_nothing(self, monkeypatch, why,
                                                     change):
        power = _readings()
        for attr, value in change.items():
            setattr(power, attr, value)
        assert await _pipeline_seen(monkeypatch, power) is None, why

    @pytest.mark.parametrize("sun,seen", [
        ("below_horizon", (400.0, 0.0)), ("above_horizon", None), (None, None),
    ])
    async def test_a_dark_solar_read_counts_only_after_sunset(
            self, monkeypatch, sun, seen):
        # (#1165 review 2) The pipeline asks ``sun.sun`` itself.
        power = _readings()
        power.inputs_degraded, power.dark_inputs = True, ("solar",)
        assert await _pipeline_seen(monkeypatch, power, sun=sun) == seen


async def _pipeline_seen(monkeypatch, power, sun=None):
    """The ``site`` ``_run_battery_pipeline`` hands the end check."""
    from custom_components.solar_energy_management.coordinator import (
        decide_battery as db,
    )
    seen: dict = {}
    stub = MagicMock()
    stub.setup_presence = {m: Presence.PRESENT for m in Module}
    stub._observer_mode = False
    stub._battery_charge_scheduler.enabled = False
    stub.config = {}
    stub._vpp_apply_battery_override = lambda pbc: {}
    stub.hass.states.get = lambda eid: (
        SimpleNamespace(state=sun) if eid == "sun.sun" and sun else None)

    def _finish(items, soc_read, count, power_read=None, site="unset"):
        seen["site"] = site

    def _decide(view):
        raise _Stop

    stub._finish_manual_battery_modes = _finish
    monkeypatch.setattr(db, "decide_battery", _decide)
    with pytest.raises(_Stop):
        await SEMCoordinator._run_battery_pipeline(
            stub, power, SimpleNamespace(), "idle")
    assert seen["site"] != "unset", "the pipeline handed no site"
    return seen["site"]


_PIPELINE = ast.parse(textwrap.dedent(
    inspect.getsource(SEMCoordinator._run_battery_pipeline)))


def test_the_check_is_handed_the_site_by_name():
    """Guard: the one end-check call passes ``site=sale_stall_site(...)``."""
    calls = [n for n in ast.walk(_PIPELINE) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_finish_manual_battery_modes"]
    assert len(calls) == 1, "the end check moved: update this guard"
    site = [k.value for k in calls[0].keywords if k.arg == "site"]
    assert len(site) == 1 and isinstance(site[0], ast.Call)
    assert ast.unparse(site[0].func) == "sale_stall_site"
