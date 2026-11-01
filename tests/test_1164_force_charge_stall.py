"""#1164 — Force charge never ended on a pack that stops below 100 %.

#1131 put Force charge back on Auto at 100 %. Some inverters end a charge at
their own level (a Huawei set to 95 %), so the pack never got there: the
house took 1 % and SEM bought it back from the grid, as before #1131.

A charge is also done when the pack takes no more: at 90 % or above, at
most 100 W in or out for 15 minutes, its level not rising, while SEM's
forced charge is on and asks for at least one charge step.

Three links, each driven for real:

* ``charge_stall_read`` / ``charge_stall_step`` / ``manual_mode_done`` — the
  pure rule and its window;
* ``SEMCoordinator._finish_manual_battery_modes`` — on a real config entry
  and the real select platform, with the adapter's own "forced charge
  landed" flag and the power the actuator last sent it;
* ``actuate_battery`` records what it SENT (a held stop sends nothing), the
  reader says whether a battery power sensor was read at all, and
  ``_run_battery_pipeline`` hands that over.
"""
from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import (
    coordinator as cmod,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
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
    MANUAL_CHARGE_STALL_SOC,
    MANUAL_CHARGE_STALL_W,
    charge_stall_read,
    charge_stall_step,
    manual_mode_done,
)
from custom_components.solar_energy_management.consts.core import (
    BATTERY_SOC_STEP_CONFIRM_READS as READS,
)
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)

_HAS_PHACC = importlib.util.find_spec("pytest_homeassistant_custom_component") is not None

_STALL = dict(soc_read=True, power_read=True, asked_w=5000.0, sem_charging=True)


# ── 1. The rule ────────────────────────────────────────────────────────────

class TestTheRule:
    def test_the_reporters_huawei_at_95_is_a_stall_read(self):
        assert charge_stall_read(95.0, 0.0, **_STALL) is True

    def test_the_level_covers_huaweis_whole_end_of_charge_range(self):
        # Huawei's end-of-charge level is set between 90 and 100 %.
        assert MANUAL_CHARGE_STALL_SOC == 90.0
        assert charge_stall_read(90.0, 0.0, **_STALL) is True
        assert charge_stall_read(89.9, 0.0, **_STALL) is False

    @pytest.mark.parametrize("power_w", [
        MANUAL_CHARGE_STALL_W + 1, -(MANUAL_CHARGE_STALL_W + 1), 2000.0, -800.0])
    def test_a_pack_that_moves_power_is_not_full(self, power_w):
        # Charging: not done. Sending power out: not following the charge.
        assert charge_stall_read(95.0, power_w, **_STALL) is False

    @pytest.mark.parametrize("power_w", [0.0, 40.0, -60.0, MANUAL_CHARGE_STALL_W])
    def test_a_trickle_or_standby_draw_is_no_more(self, power_w):
        assert charge_stall_read(95.0, power_w, **_STALL) is True

    @pytest.mark.parametrize("change", [
        {"soc_read": False}, {"power_read": False},
        {"sem_charging": None}, {"sem_charging": False},
        {"asked_w": 0.0}, {"asked_w": FORCED_CHARGE_STEP_W - 1},
    ])
    def test_no_stall_without_every_reading_and_a_charge_asked(self, change):
        assert charge_stall_read(95.0, 0.0, **{**_STALL, **change}) is False

    def test_no_stall_on_a_missing_value(self):
        assert charge_stall_read(None, 0.0, **_STALL) is False
        assert charge_stall_read(95.0, None, **_STALL) is False

    @staticmethod
    def _walk(start_s, end_s, soc=95.0, step_s=30.0, w=None):
        """Checks every ``step_s`` from ``start_s`` to ``end_s``."""
        t, done = start_s, False
        while t <= end_s:
            w, done = charge_stall_step(w, t, soc, True)
            t += step_s
        return w, done

    def test_the_window_lasts_its_time(self):
        w, done = charge_stall_step(None, 1000.0, 95.0, True)
        assert w == (1000.0, 95.0, 1000.0) and done is False
        w, done = self._walk(1030.0, 1000.0 + MANUAL_CHARGE_STALL_S - 1, w=w)
        assert done is False
        w, done = charge_stall_step(w, 1000.0 + MANUAL_CHARGE_STALL_S, 95.0, True)
        assert done is True and w[:2] == (1000.0, 95.0)

    def test_a_level_that_rises_starts_the_window_again(self):
        w, _ = self._walk(0.0, MANUAL_CHARGE_STALL_S - 30)
        w, done = charge_stall_step(w, MANUAL_CHARGE_STALL_S, 95.4, True)
        assert w[:2] == (MANUAL_CHARGE_STALL_S, 95.4) and done is False
        _, done = self._walk(MANUAL_CHARGE_STALL_S + 30, MANUAL_CHARGE_STALL_S + 600,
                             soc=95.4, w=w)
        assert done is False, "the pack still charges, slowly"

    def test_a_level_that_falls_keeps_the_window(self):
        w, _ = self._walk(0.0, MANUAL_CHARGE_STALL_S - 30)
        _, done = charge_stall_step(w, MANUAL_CHARGE_STALL_S, 94.8, True)
        assert done is True

    def test_one_cycle_without_a_stall_read_ends_the_window(self):
        w, _ = self._walk(0.0, 570.0)
        w, done = charge_stall_step(w, 600.0, 95.0, False)
        assert w is None and done is False
        _, done = self._walk(630.0, MANUAL_CHARGE_STALL_S + 30)
        assert done is False, "the window starts again at 630 s"

    def test_a_gap_between_two_checks_starts_the_window_again(self):
        # The pipeline did not run for a while: what the pack did is unseen.
        w, _ = self._walk(0.0, 300.0)
        w, done = charge_stall_step(w, 300.0 + MANUAL_CHARGE_STALL_GAP_S + 1,
                                    95.0, True)
        assert done is False and w[0] == 300.0 + MANUAL_CHARGE_STALL_GAP_S + 1
        w, _ = self._walk(0.0, 300.0)
        _, done = charge_stall_step(w, 300.0 + MANUAL_CHARGE_STALL_GAP_S, 95.0, True)
        assert done is False
        # 60 s cycles (the slowest) keep the window.
        _, done = self._walk(0.0, MANUAL_CHARGE_STALL_S, step_s=60.0)
        assert done is True

    def test_a_stall_ends_a_charge_only(self):
        assert manual_mode_done("force_charge", 95.0, soc_read=True,
                                reserve=20.0, charge_stalled=True) is True
        assert manual_mode_done("force_charge", 95.0, soc_read=True,
                                reserve=20.0) is False
        assert manual_mode_done("force_discharge", 95.0, soc_read=True,
                                reserve=20.0, charge_stalled=True) is False
        assert manual_mode_done("auto", 95.0, soc_read=True,
                                reserve=20.0, charge_stalled=True) is False
        assert manual_mode_done("force_charge", 95.0, soc_read=False,
                                reserve=20.0, charge_stalled=True) is False


# ── 2. The coordinator ends the mode ───────────────────────────────────────

def _entry(hass, options):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.solar_energy_management.const import DOMAIN
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=dict(options),
                            title="SEM #1164")
    entry.add_to_hass(hass)
    return entry


def _adapter(landed=True, asked_w=5000.0):
    # What actuate_battery leaves on an adapter whose forced charge landed.
    return SimpleNamespace(_sem_forced_charge=landed, _sem_forced_discharge=None,
                           _sem_charge_asked_w=asked_w)


def _coordinator(hass, entry, slugs, ids):
    from custom_components.solar_energy_management.const import DOMAIN
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.config_entry = entry
    coordinator.hass = hass
    coordinator.setup_presence = {m: Presence.PRESENT for m in Module}
    coordinator.config = {**entry.data, **entry.options}
    coordinator.battery_control_slugs = slugs
    coordinator._manual_done_streaks = {}
    coordinator._manual_charge_stalls = {}
    coordinator._observer_mode = False
    coordinator._battery_adapters = {bid: _adapter() for bid in ids}
    coordinator._vpp_battery_override = None
    coordinator._sensor_reader._energy_dashboard_config.battery_power_list = []
    coordinator._per_battery_config = (
        lambda i, c=1: SEMCoordinator._per_battery_config(coordinator, i, c))
    coordinator._vpp_apply_battery_override = (
        lambda pbc: SEMCoordinator._vpp_apply_battery_override(coordinator, pbc))
    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    return coordinator


async def _selects(hass, entry):
    from custom_components.solar_energy_management import select
    added: list = []
    await select.async_setup_entry(hass, entry, added.extend)
    out = {}
    for ent in added:
        key = ent.entity_description.key
        if key.startswith("battery_") and key.endswith("_mode"):
            ent.hass = hass
            ent.async_write_ha_state = lambda: None
            out[key] = ent
    return out


class _Clock:
    def __init__(self):
        self.t = 10_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(cmod, "_manual_stall_clock", c)
    return c


def _run(coordinator, clock, packs, minutes, *, step_s=30.0, count=None,
         power_read=True, unread=()):
    """Cycles every ``step_s`` for ``minutes``; ``packs`` is
    {battery id: (SOC, W)}."""
    items = [(bid, BatteryRuntime(battery_id=bid, last_known_soc=soc,
                                  last_known_w=w))
             for bid, (soc, w) in packs.items()]
    read = {bid: bid not in unread for bid in packs}
    # (#1167) each battery's own power flag; a bool here sets every one
    power = {bid: bool(power_read) for bid in packs}
    for _ in range(int(minutes * 60 / step_s)):
        clock.t += step_s
        SEMCoordinator._finish_manual_battery_modes(
            coordinator, items, read, count or len(items),
            power_read=power)


def _shows(select_entity):
    select_entity._handle_coordinator_update()
    return select_entity.current_option


_WINDOW_MIN = MANUAL_CHARGE_STALL_S / 60


@pytest.mark.skipif(not _HAS_PHACC, reason="pytest-homeassistant-custom-component not installed")
class TestAPackThatStopsAt95:
    @pytest.mark.asyncio
    async def test_the_reporters_huawei_goes_back_to_auto(self, hass, clock):
        entry = _entry(hass, {"battery_mode": "auto"})
        coordinator = _coordinator(hass, entry, (), ["primary"])
        selects = await _selects(hass, entry)
        await selects["battery_mode"].async_select_option("force_charge")

        _run(coordinator, clock, {"primary": (95.0, 0.0)}, _WINDOW_MIN - 1)
        assert entry.options["battery_mode"] == "force_charge", (
            "14 minutes are not enough")
        # The window is done at 15 min; then the done state holds READS reads.
        _run(coordinator, clock, {"primary": (95.0, 0.0)},
             1 + READS * 30 / 60)
        assert entry.options["battery_mode"] == "auto"
        assert _shows(selects["battery_mode"]) == "auto"

    @pytest.mark.asyncio
    async def test_an_adapter_never_asked_to_charge_keeps_the_mode(self, hass, clock):
        # An adapter actuate_battery never touched has no asked power.
        entry = _entry(hass, {"battery_mode": "force_charge"})
        coordinator = _coordinator(hass, entry, (), ["primary"])
        coordinator._battery_adapters = {"primary": SimpleNamespace(
            _sem_forced_charge=True, _sem_forced_discharge=None)}
        _run(coordinator, clock, {"primary": (95.0, 0.0)}, 120)
        assert entry.options["battery_mode"] == "force_charge"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("why,pack,change", [
        ("still charging", (95.0, 1800.0), {}),
        ("below the level", (60.0, 0.0), {}),
        ("the grid limit asks for nothing", (95.0, 0.0),
         {"_battery_adapters": {"primary": _adapter(asked_w=0.0)}}),
        ("less than one charge step asked", (95.0, 0.0),
         {"_battery_adapters": {"primary": _adapter(asked_w=FORCED_CHARGE_STEP_W - 1)}}),
        ("a damaged asked power", (95.0, 0.0),
         {"_battery_adapters": {"primary": _adapter(asked_w=True)}}),
        ("the charge never landed", (95.0, 0.0),
         {"_battery_adapters": {"primary": _adapter(landed=None)}}),
        ("SEM stopped the charge", (95.0, 0.0),
         {"_battery_adapters": {"primary": _adapter(landed=False)}}),
        ("no adapter", (95.0, 0.0), {"_battery_adapters": {}}),
        ("observer sends nothing", (95.0, 0.0), {"_observer_mode": True}),
    ])
    async def test_the_mode_stays(self, hass, clock, why, pack, change):
        entry = _entry(hass, {"battery_mode": "force_charge"})
        coordinator = _coordinator(hass, entry, (), ["primary"])
        for attr, value in change.items():
            setattr(coordinator, attr, value)
        _run(coordinator, clock, {"primary": pack}, 120)
        assert entry.options["battery_mode"] == "force_charge", why

    @pytest.mark.asyncio
    async def test_a_dark_power_or_level_read_keeps_the_mode(self, hass, clock):
        entry = _entry(hass, {"battery_mode": "force_charge"})
        coordinator = _coordinator(hass, entry, (), ["primary"])
        _run(coordinator, clock, {"primary": (95.0, 0.0)}, 120, power_read=False)
        _run(coordinator, clock, {"primary": (95.0, 0.0)}, 120, unread={"primary"})
        assert entry.options["battery_mode"] == "force_charge"

    @pytest.mark.asyncio
    async def test_a_dark_power_read_starts_the_window_again(self, hass, clock):
        entry = _entry(hass, {"battery_mode": "force_charge"})
        coordinator = _coordinator(hass, entry, (), ["primary"])
        _run(coordinator, clock, {"primary": (95.0, 0.0)}, _WINDOW_MIN - 1)
        _run(coordinator, clock, {"primary": (95.0, 0.0)}, 0.5, power_read=False)
        _run(coordinator, clock, {"primary": (95.0, 0.0)}, _WINDOW_MIN - 1)
        assert entry.options["battery_mode"] == "force_charge"
        _run(coordinator, clock, {"primary": (95.0, 0.0)}, 1 + READS * 30 / 60)
        assert entry.options["battery_mode"] == "auto"

    @pytest.mark.asyncio
    async def test_a_slow_rise_keeps_the_charge_going(self, hass, clock):
        entry = _entry(hass, {"battery_mode": "force_charge"})
        coordinator = _coordinator(hass, entry, (), ["primary"])
        for soc in (95.0, 95.5, 96.0, 96.5, 97.0, 97.5, 98.0):
            _run(coordinator, clock, {"primary": (soc, 80.0)}, _WINDOW_MIN - 1)
        assert entry.options["battery_mode"] == "force_charge"

    @pytest.mark.asyncio
    async def test_the_window_lives_in_time_not_cycles(self, hass, clock):
        # 10 s cycles: 89 cycles is under 15 min.
        entry = _entry(hass, {"battery_mode": "force_charge"})
        coordinator = _coordinator(hass, entry, (), ["primary"])
        _run(coordinator, clock, {"primary": (95.0, 0.0)}, _WINDOW_MIN - 0.5,
             step_s=10.0)
        assert entry.options["battery_mode"] == "force_charge"
        _run(coordinator, clock, {"primary": (95.0, 0.0)}, 1, step_s=10.0)
        assert entry.options["battery_mode"] == "auto"

    @pytest.mark.asyncio
    async def test_a_stalled_pack_on_one_shared_control_waits_for_the_other(
            self, hass, clock):
        entry = _entry(hass, {"battery_mode": "force_charge"})
        coordinator = _coordinator(hass, entry, (), ["b1", "b2"])
        _run(coordinator, clock, {"b1": (95.0, 0.0), "b2": (60.0, 2500.0)}, 60)
        assert entry.options["battery_mode"] == "force_charge", (
            "b2 still charges: the shared job is not done")
        _run(coordinator, clock, {"b1": (95.0, 0.0), "b2": (100.0, 0.0)}, 2)
        assert entry.options["battery_mode"] == "auto"

    @pytest.mark.asyncio
    async def test_per_battery_controls_only_the_stalled_pack_moves(
            self, hass, clock):
        entry = _entry(hass, {"battery_modes": ["force_charge", "force_charge"]})
        coordinator = _coordinator(hass, entry, ("b1", "b2"), ["b1", "b2"])
        selects = await _selects(hass, entry)
        _run(coordinator, clock, {"b1": (95.0, 0.0), "b2": (60.0, 2500.0)}, 20)
        assert entry.options["battery_modes"] == ["auto", "force_charge"]
        assert _shows(selects["battery_b1_mode"]) == "auto"
        assert _shows(selects["battery_b2_mode"]) == "force_charge"

    @pytest.mark.asyncio
    async def test_each_pack_answers_with_its_own_flag(self, hass, clock):
        # b2's adapter landed no charge: its idle power says nothing.
        entry = _entry(hass, {"battery_modes": ["force_charge", "force_charge"]})
        coordinator = _coordinator(hass, entry, ("b1", "b2"), ["b1", "b2"])
        coordinator._battery_adapters["b2"] = _adapter(landed=None)
        _run(coordinator, clock, {"b1": (95.0, 0.0), "b2": (95.0, 0.0)}, 20)
        assert entry.options["battery_modes"] == ["auto", "force_charge"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("b1_w,b2_w,expect", [
        (0.0, 2500.0, ["auto", "force_charge"]),
        (2500.0, 0.0, ["force_charge", "auto"]),
    ])
    async def test_each_pack_answers_with_its_own_power(
            self, hass, clock, b1_w, b2_w, expect):
        # Same level, same flags: only the pack's own power tells them apart.
        entry = _entry(hass, {"battery_modes": ["force_charge", "force_charge"]})
        coordinator = _coordinator(hass, entry, ("b1", "b2"), ["b1", "b2"])
        _run(coordinator, clock, {"b1": (95.0, b1_w), "b2": (95.0, b2_w)}, 20)
        assert entry.options["battery_modes"] == expect

    @pytest.mark.asyncio
    async def test_a_cold_start_drops_the_window(self, hass, clock):
        # One synthetic battery while the per-battery selects own each unit:
        # no unit was watched, so its window starts again.
        entry = _entry(hass, {"battery_modes": ["force_charge", "force_charge"]})
        coordinator = _coordinator(hass, entry, ("b1", "b2"), ["b1", "b2"])
        _run(coordinator, clock, {"b1": (95.0, 0.0), "b2": (60.0, 2500.0)},
             _WINDOW_MIN - 1)
        _run(coordinator, clock, {"primary": (95.0, 0.0)}, 0.5, count=1)
        assert coordinator._manual_charge_stalls == {}
        _run(coordinator, clock, {"b1": (95.0, 0.0), "b2": (60.0, 2500.0)},
             _WINDOW_MIN - 1)
        assert entry.options["battery_modes"] == ["force_charge", "force_charge"]

    @pytest.mark.asyncio
    async def test_force_discharge_is_not_ended_by_an_idle_pack(self, hass, clock):
        entry = _entry(hass, {"battery_mode": "force_discharge",
                              "battery_reserve_soc": 20})
        coordinator = _coordinator(hass, entry, (), ["primary"])
        _run(coordinator, clock, {"primary": (95.0, 0.0)}, 60)
        assert entry.options["battery_mode"] == "force_discharge"
        assert coordinator._manual_charge_stalls == {}


# ── 3. What was sent, what was read, and the pipeline ──────────────────────

class _Adapter:
    """A battery adapter that takes every command (``refuse``: the start
    fails, as an adapter reports it — ``last_error`` set, intent kept)."""
    supports_forced_charge = True
    supports_forced_discharge = True
    last_intent = None
    last_error = None
    last_discharge_limit_w = -1.0

    def __init__(self):
        self.sent: list = []
        self.refuse = False

    async def command_force_charge(self, target_soc, power_w, duration_min):
        if self.refuse:
            self.last_error = "start_forced_charge failed"
            return None
        self.sent.append(("charge", power_w))
        self.last_error = None
        self.last_intent = BatteryIntent.FORCE_CHARGE
        return None

    async def command_stop_force_charge(self):
        self.sent.append(("stop",))
        self.last_intent = BatteryIntent.STOP_FORCE_CHARGE
        return True

    async def command_normal(self):
        self.sent.append(("normal",))
        self.last_intent = BatteryIntent.NORMAL

    async def command_force_discharge(self, *a, **kw):
        self.sent.append(("sell",))
        self.last_intent = BatteryIntent.FORCE_DISCHARGE
        return True

    async def command_stop_force_discharge(self):
        self.sent.append(("stop_sell",))
        return True

    async def command_off(self):
        self.sent.append(("off",))


def _decision(intent, power_w=4200.0, **kw):
    return BatteryDecision(battery_id="primary", intent=intent,
                           target_soc=100.0, charge_power_w=power_w,
                           discharge_power_w=3000.0, floor_soc=20.0,
                           duration_min=240, **kw)


@pytest.mark.asyncio
class TestTheActuatorRecordsWhatItSent:
    async def _send(self, adapter, decision, **kw):
        from custom_components.solar_energy_management.coordinator.actuate_battery import (
            actuate_battery,
        )
        await actuate_battery(decision, adapter, **kw)
        return adapter._sem_charge_asked_w

    async def test_a_charge_sent_is_asked(self):
        a = _Adapter()
        assert await self._send(a, _decision(BatteryIntent.FORCE_CHARGE)) == 4200.0
        assert a.sent == [("charge", 4200.0)] and a._sem_forced_charge is True

    @pytest.mark.parametrize("intent", [
        BatteryIntent.STOP_FORCE_CHARGE, BatteryIntent.NORMAL,
        BatteryIntent.FORCE_DISCHARGE, BatteryIntent.OFF])
    async def test_anything_else_asks_for_no_charge(self, intent):
        a = _Adapter()
        await self._send(a, _decision(BatteryIntent.FORCE_CHARGE))
        assert await self._send(a, _decision(intent)) == 0.0

    async def test_observer_asks_for_nothing(self):
        a = _Adapter()
        await self._send(a, _decision(BatteryIntent.FORCE_CHARGE))
        assert await self._send(a, _decision(BatteryIntent.FORCE_CHARGE),
                                observer=True) == 0.0

    async def test_a_held_stop_after_no_room_asks_for_nothing(self):
        # (review) The grid limit left room for one step after a no-room
        # stop: the decision asks 250 W, but the actuator holds the stop and
        # sends nothing, so the pack is answering the stop.
        a = _Adapter()
        await self._send(a, _decision(BatteryIntent.STOP_FORCE_CHARGE,
                                      room_capped=True))
        asked = await self._send(a, _decision(
            BatteryIntent.FORCE_CHARGE, power_w=FORCED_CHARGE_STEP_W,
            room_capped=True))
        assert a.sent == [("stop",)], "the stop is held, nothing sent"
        assert asked == 0.0

    async def test_a_start_that_failed_asks_for_nothing(self):
        # (review) A withheld setpoint (#978) or a failed start sends
        # nothing; the intent from the last cycle still reads FORCE_CHARGE.
        a = _Adapter()
        await self._send(a, _decision(BatteryIntent.FORCE_CHARGE))
        a.refuse = True
        assert await self._send(a, _decision(BatteryIntent.FORCE_CHARGE)) == 0.0
        assert a.last_intent is BatteryIntent.FORCE_CHARGE
        a.refuse = False
        assert await self._send(a, _decision(BatteryIntent.FORCE_CHARGE)) == 4200.0

    async def test_an_adapter_that_cannot_charge_is_asked_nothing(self):
        a = _Adapter()
        a.supports_forced_charge = False
        assert await self._send(a, _decision(BatteryIntent.FORCE_CHARGE)) == 0.0


def _state(value, unit):
    import homeassistant.util.dt as dt_util
    st = MagicMock()
    st.state = str(value)
    st.attributes = {"unit_of_measurement": unit}
    st.last_updated = st.last_reported = dt_util.utcnow()
    return st


def _reader(states, config):
    from custom_components.solar_energy_management.coordinator.sensor_reader import (
        SensorReader,
    )
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    r = SensorReader(hass, config)
    r._energy_dashboard_config = None
    return r


class TestTheReaderSaysWhetherPowerWasRead:
    def test_a_battery_power_sensor_that_answers_is_a_reading(self):
        p = _reader({"sensor.soc": _state(95, "%"), "sensor.bp": _state(0, "W")},
                    {"battery_soc_sensor": "sensor.soc",
                     "battery_power_sensor": "sensor.bp"}).read_power()
        assert p.battery_power_read is True

    def test_a_battery_with_no_power_sensor_is_no_reading(self):
        # (review) SOC only: battery_power is 0.0 and nothing is dark.
        p = _reader({"sensor.soc": _state(95, "%")},
                    {"battery_soc_sensor": "sensor.soc"}).read_power()
        assert p.battery_power == 0.0
        assert p.battery_power_unavailable is False
        assert p.battery_power_read is False

    def test_a_dark_power_sensor_is_no_reading(self):
        p = _reader({"sensor.soc": _state(95, "%"),
                     "sensor.bp": _state("unavailable", "W")},
                    {"battery_soc_sensor": "sensor.soc",
                     "battery_power_sensor": "sensor.bp"}).read_power()
        assert p.battery_power_read is False

    def test_an_impossible_power_is_no_reading(self):
        p = _reader({"sensor.soc": _state(95, "%"),
                     "sensor.bp": _state(22806824, "W")},
                    {"battery_soc_sensor": "sensor.soc",
                     "battery_power_sensor": "sensor.bp"}).read_power()
        assert p.battery_power_read is False

    def test_a_state_that_is_no_number_is_no_reading(self):
        # (review) "none" passes the unavailable check and fails the parse.
        p = _reader({"sensor.soc": _state(95, "%"), "sensor.bp": _state("none", "W")},
                    {"battery_soc_sensor": "sensor.soc",
                     "battery_power_sensor": "sensor.bp"}).read_power()
        assert p.battery_power == 0.0
        assert p.battery_power_read is False

    @pytest.mark.parametrize("b2,read", [("300", True), ("unavailable", False)])
    def test_the_energy_dashboard_path_reads_every_unit(self, b2, read):
        from custom_components.solar_energy_management.ha_energy_reader import (
            EnergyDashboardConfig,
        )
        r = _reader({"sensor.b1_power": _state(0, "W"),
                     "sensor.b2_power": _state(b2, "W")}, {})
        r.hass.states.async_all = MagicMock(return_value=[])
        r._sign_vote_warmup = 0
        r.set_energy_dashboard_config(EnergyDashboardConfig(
            battery_power="sensor.b1_power",
            battery_power_list=["sensor.b1_power", "sensor.b2_power"],
            has_battery=True, has_solar=False, has_grid=False))
        p = r.read_power()
        assert set(p.batteries) == {"b1", "b2"}
        assert p.battery_power_read is read

    def test_the_default_is_no_reading(self):
        from custom_components.solar_energy_management.coordinator.types import (
            PowerReadings,
        )
        assert PowerReadings().battery_power_read is False


class _Stop(Exception):
    """Raised by the patched decide_battery: the check has run."""


def _single(**kw):
    base = dict(batteries={}, battery_soc=95.0, battery_power=0.0,
                battery_soc_unavailable=False, battery_soc_known=True,
                battery_power_unavailable=False, battery_power_read=True)
    base.update(kw)
    return SimpleNamespace(**base)


async def _pipeline(monkeypatch, power):
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

    def _finish(items, soc_read, count, power_read=None, site=None):
        seen["soc_read"] = soc_read
        seen["power_read"] = power_read
        seen["power"] = [(bid, rt.last_known_w) for bid, rt in items]

    def _decide(view):
        raise _Stop

    stub._finish_manual_battery_modes = _finish
    monkeypatch.setattr(db, "decide_battery", _decide)
    with pytest.raises(_Stop):
        await SEMCoordinator._run_battery_pipeline(
            stub, power, SimpleNamespace(), "idle")
    return seen


@pytest.mark.asyncio
class TestThePipeline:
    async def test_a_readable_power_is_a_reading(self, monkeypatch):
        seen = await _pipeline(monkeypatch, _single(battery_power=12.0))
        assert seen["power_read"] == {"primary": True}
        assert seen["power"] == [("primary", 12.0)]

    @pytest.mark.parametrize("change", [
        {"battery_power_unavailable": True}, {"battery_power_read": False}])
    async def test_a_dark_or_missing_power_is_not(self, monkeypatch, change):
        seen = await _pipeline(monkeypatch, _single(**change))
        assert seen["power_read"] == {"primary": False}

    async def test_a_reading_without_the_flag_is_not(self, monkeypatch):
        power = _single()
        del power.battery_power_read
        seen = await _pipeline(monkeypatch, power)
        assert seen["power_read"] == {"primary": False}
