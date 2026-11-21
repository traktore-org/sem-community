"""#1405 — the first charger counts from its own car's level.

The first charger's car level estimate was set each cycle from the car
level in the main settings (``vehicle_soc_entity``). When that setting
names the car on another charger, the first charger's estimate started
from the other car's level. Its stop check caps the sensor with that
estimate (#708), so a fuller car on the other charger stopped solar
charging on the first one early — even when the first charger's own
sensor read a lower level.

The same flat read sat in four more places: the seed every charger in
the loop starts from (a second charger with no sensor read the first
car's level), the session tracking loop, the first charger's need in the
base context, and the level that ends the first detector's session.
All now read ``SEMCoordinator._own_vehicle_soc(cid)``.

The cycle tests run the real cycle (``CycleRig``).
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import (
    per_charger_context as _pcc_mod,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

from .ast_contracts import calls, reads_attribute
from .test_1403_full_power_state import _amps_sent, _charger, _day_rig

CAR_A = "sensor.car_a_soc"
CAR_B = "sensor.car_b_soc"


def _fleet(a_soc="unavailable", b_soc=90, *, a_sensor=True, b_sensor=True):
    """Two chargers by day with sun to spare. Charger a (first) stops at
    80 %; the main-settings car level names car B, on charger b."""
    a_over = {"ev_target_type": "soc", "ev_target_soc": 80,
              "ev_target_soc_max": 80, "ev_battery_capacity_kwh": 60,
              "ev_power_sensor": "sensor.a_ev"}
    if a_sensor:
        a_over["vehicle_soc_entity"] = CAR_A
    b_over = {"ev_power_sensor": "sensor.b_ev", "ev_battery_capacity_kwh": 60}
    if b_sensor:
        b_over["vehicle_soc_entity"] = CAR_B
    rig = _day_rig(
        [_charger("a", mode="solar_only", **a_over),
         _charger("b", mode="solar_only", **b_over)],
        solar=14000, grid=9000, soc=95, ev=0)
    rig.coord.config["vehicle_soc_entity"] = CAR_B
    rig.coord.config["ev_enable_delay_seconds"] = 0
    rig.hass.states.set("sensor.a_ev", 0)
    rig.hass.states.set("sensor.b_ev", 0)
    rig.hass.states.set(CAR_A, a_soc)
    rig.hass.states.set(CAR_B, b_soc)
    return rig


def _spy_need(rig):
    """Every ``_calculate_remaining_need`` call: (charger id, level, bound,
    result)."""
    seen = []
    real = rig.coord._calculate_remaining_need

    def _spy(energy, vehicle_soc=None, charger_cfg=None, bound="min"):
        out = real(energy, vehicle_soc, charger_cfg, bound)
        seen.append(((charger_cfg or {}).get("id"), vehicle_soc, bound, out))
        return out

    rig.coord._calculate_remaining_need = _spy
    return seen


# ── the reported case ─────────────────────────────────────────────────

@pytest.mark.asyncio
class TestTheFirstChargerCountsFromItsOwnCar:

    async def test_a_dark_own_sensor_is_not_the_other_cars_level(self):
        """Car A's sensor is dark; car B, on charger b, is at 90 %. The
        first charger's estimate must not start from 90 %."""
        rig = _fleet(a_soc="unavailable", b_soc=90)
        for _ in range(2):
            await rig.tick()
        det = rig.coord._ev_taper_detectors["a"]
        assert det._soc_anchor_value != 90.0
        assert det.energy_accounted_soc() is None

    async def test_solar_on_the_first_charger_does_not_stop(self):
        """The reported harm: car B at 90 % read as car A's level met
        charger a's 80 % target, so its surplus charge stopped."""
        rig = _fleet(a_soc="unavailable", b_soc=90)
        seen = _spy_need(rig)
        for _ in range(3):
            await rig.tick()
        a_max = [out for cid, _soc, bound, out in seen
                 if cid == "a" and bound == "max"]
        assert a_max, "charger a's need was never asked"
        assert all(out > 0.1 for out in a_max), a_max
        assert any((v or 0) >= 6 for v in _amps_sent(rig, "a")), \
            _amps_sent(rig, "a")

    async def test_a_working_own_sensor_is_not_capped_by_the_other_car(self):
        """Car A reads 60 %. The other car's 90 % anchored the first
        charger's estimate before the loop each cycle, and the stop check
        took the higher of the two: charger a stopped at 60 %."""
        rig = _fleet(a_soc=60, b_soc=90)
        seen = _spy_need(rig)
        for _ in range(2):
            await rig.tick()
        det = rig.coord._ev_taper_detectors["a"]
        assert det._soc_anchor_value == 60.0
        assert det.energy_accounted_soc() == pytest.approx(60.0)
        a_max = [out for cid, _soc, bound, out in seen
                 if cid == "a" and bound == "max"]
        assert a_max and all(out > 0.1 for out in a_max), a_max

    async def test_the_estimate_is_not_moved_twice_a_cycle(self):
        """With both levels fed in turn, the anchor moved every cycle (a
        new timestamp each time). One level: it stays put."""
        rig = _fleet(a_soc=60, b_soc=90)
        await rig.tick()
        det = rig.coord._ev_taper_detectors["a"]
        first = det.anchor_at
        for _ in range(2):
            await rig.tick()
        assert det.anchor_at == first

    async def test_the_estimate_shown_is_its_own(self):
        rig = _fleet(a_soc=60, b_soc=90)
        res = None
        for _ in range(2):
            res = await rig.tick()
        assert rig.coord._last_ev_intelligence.estimated_soc_pct == 60.0
        per = rig.coord._build_per_charger_intelligence()
        assert per["a"]["estimated_soc"] == 60.0
        assert per["b"]["estimated_soc"] == 90.0
        assert res is not None


# ── the old setups keep working ───────────────────────────────────────

@pytest.mark.asyncio
class TestTheMainSettingIsTheFirstChargersCar:

    async def test_one_charger_with_only_the_main_setting(self):
        """Unchanged: one charger, its car level only in the main
        settings — that is its car."""
        rig = _day_rig([_charger("a", mode="solar_only", ev_target_type="soc",
                                 ev_target_soc=80)],
                       solar=14000, grid=9000, soc=95, ev=0)
        rig.coord.config["vehicle_soc_entity"] = CAR_A
        rig.hass.states.set(CAR_A, 55)
        seen = _spy_need(rig)
        await rig.tick()
        det = rig.coord._ev_taper_detectors["a"]
        assert det._soc_anchor_value == 55.0
        assert ("a", 55.0) in [(c, s) for c, s, _b, _o in seen]
        assert rig.coord._last_ev_intelligence.estimated_soc_pct == 55.0

    async def test_the_main_setting_named_by_another_charger_is_its_car(self):
        """Review: charger a names no sensor; the main setting names car
        B's sensor, which charger b names as its own. That is car B (a
        setting left from one-charger days), so charger a has no level."""
        rig = _fleet(a_soc="unavailable", b_soc=90, a_sensor=False)
        seen = _spy_need(rig)
        for _ in range(2):
            await rig.tick()
        assert rig.coord._ev_taper_detectors["a"]._soc_anchor_value != 90.0
        assert rig.coord._ev_taper_detectors["a"].energy_accounted_soc() is None
        assert ("a", 90.0) not in [(c, s) for c, s, _b, _o in seen]
        assert ("b", 90.0) in [(c, s) for c, s, _b, _o in seen]

    async def test_first_charger_with_no_own_sensor_reads_the_main_one(self):
        rig = _fleet(b_soc=70, a_sensor=False)
        rig.coord.config["vehicle_soc_entity"] = CAR_A
        rig.hass.states.set(CAR_A, 55)
        await rig.tick()
        assert rig.coord._ev_taper_detectors["a"]._soc_anchor_value == 55.0


# ── the siblings ──────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestNoOtherChargerReadsAnotherCar:

    async def test_a_second_charger_with_no_sensor_has_no_level(self):
        """Charger b names no sensor. The main-settings level is car A's
        (charger a has none of its own either); b used to read it."""
        rig = _fleet(b_soc=70, a_sensor=False, b_sensor=False)
        rig.coord.config["vehicle_soc_entity"] = CAR_A
        rig.hass.states.set(CAR_A, 55)
        # b in percent mode by the main-settings type (old setups)
        rig.coord.config["ev_chargers"][1]["ev_target_type"] = None
        rig.coord.config["ev_target_type"] = "soc"
        seen = _spy_need(rig)
        await rig.tick()
        b_levels = [s for c, s, _b, _o in seen if c == "b"]
        assert b_levels, "charger b's need was never asked"
        assert 55.0 not in b_levels
        assert all(s is None for s in b_levels)

    async def test_the_base_context_reads_the_first_chargers_car(self):
        """The base context sizes the first charger's need before the
        loop; it used the main-settings level, car B's."""
        rig = _fleet(a_soc="unavailable", b_soc=90)
        seen = _spy_need(rig)
        await rig.tick()
        assert ("a", 90.0) not in [(c, s) for c, s, _b, _o in seen]

    async def test_the_session_end_reads_the_first_chargers_car(self):
        rig = _fleet(a_soc=60, b_soc=90)
        await rig.tick()
        det = rig.coord._ev_taper_detector
        det.on_session_end = MagicMock()
        rig.coord._last_ev_connected = True
        rig.coord._session_data.energy_kwh = 5.0
        rig.coord._finish_fleet_session(SimpleNamespace(ev_connected=False))
        assert det.on_session_end.call_args.kwargs["end_soc"] == 60.0

    async def test_the_seed_of_each_charger_is_its_own(self):
        """``PerChargerContext`` seeds each charger from its own car."""
        rig = _fleet(a_soc=60, b_soc=90)
        rig.coord._cycle_vehicle_soc = 90.0      # the main-settings read
        ctx = _pcc_mod.PerChargerContext
        with ctx(cid="a", ev_dev=MagicMock(), charger_cfg={}, _coord=rig.coord):
            assert rig.coord._cycle_vehicle_soc == 60.0
        with ctx(cid="b", ev_dev=MagicMock(), charger_cfg={}, _coord=rig.coord):
            assert rig.coord._cycle_vehicle_soc == 90.0
        rig.hass.states.set(CAR_A, "unavailable")
        with ctx(cid="a", ev_dev=MagicMock(), charger_cfg={}, _coord=rig.coord):
            assert rig.coord._cycle_vehicle_soc is None


# ── the helper on its own ─────────────────────────────────────────────

class TestOwnVehicleSoc:

    def _coord(self, chargers, states, flat=None):
        hass = MagicMock()
        hass.states.get = lambda eid: (
            SimpleNamespace(state=states[eid]) if eid in states else None)
        coord = SEMCoordinator(hass, {"ev_chargers": chargers})
        coord._cycle_vehicle_soc = flat
        return coord

    def test_own_sensor_wins_over_the_main_one(self):
        c = self._coord([{"id": "a", "vehicle_soc_entity": CAR_A}],
                        {CAR_A: "61.5"}, flat=90.0)
        assert c._own_vehicle_soc("a") == 61.5

    def test_dark_or_text_own_sensor_is_no_level(self):
        for state in ("unavailable", "unknown", "nan", "abc"):
            c = self._coord([{"id": "a", "vehicle_soc_entity": CAR_A}],
                            {CAR_A: state}, flat=90.0)
            assert c._own_vehicle_soc("a") is None, state

    def test_main_one_is_the_first_chargers_only(self):
        c = self._coord([{"id": "a"}, {"id": "b"}], {}, flat=55.0)
        assert c._own_vehicle_soc("a") == 55.0
        assert c._own_vehicle_soc("b") is None
        assert c._own_vehicle_soc(None) == 55.0

    def test_main_one_named_by_another_charger_is_not_the_first_cars(self):
        c = self._coord([{"id": "a"}, {"id": "b", "vehicle_soc_entity": CAR_B}],
                        {CAR_B: "90"}, flat=90.0)
        c.config["vehicle_soc_entity"] = CAR_B
        assert c._own_vehicle_soc("a") is None
        assert c._own_vehicle_soc("b") == 90.0
        c.config["vehicle_soc_entity"] = CAR_A      # a different sensor
        assert c._own_vehicle_soc("a") == 90.0

    def test_an_id_less_entry_is_found_by_its_registration_id(self):
        c = self._coord([{"name": "x"}, {"vehicle_soc_entity": CAR_B}],
                        {CAR_B: "42"}, flat=55.0)
        assert c._own_vehicle_soc("ev_charger_0") == 55.0
        assert c._own_vehicle_soc("ev_charger_1") == 42.0

    def test_no_charger_list_reads_the_main_one(self):
        c = self._coord([], {}, flat=55.0)
        assert c._own_vehicle_soc("ev_charger") == 55.0


# ── the guard ─────────────────────────────────────────────────────────

_FED = {"get_virtual_soc", "on_session_end", "_calculate_remaining_need"}


def _is_flat_read(node) -> bool:
    return (isinstance(node, ast.Attribute)
            and node.attr in ("_cycle_vehicle_soc", "_cycle_vehicle_soc_default")
            and isinstance(node.value, ast.Name) and node.value.id == "self")


class TestNoDetectorIsFedTheMainSettingDirectly:

    def test_no_call_passes_the_flat_level(self):
        """A detector, a session end or a need is fed a charger's own
        level (``_own_vehicle_soc``), never ``self._cycle_vehicle_soc``
        straight: out of the loop that is the main-settings car."""
        tree = ast.parse(textwrap.dedent(inspect.getsource(SEMCoordinator)))
        bad = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name not in _FED:
                continue
            args = list(node.args) + [k.value for k in node.keywords]
            if any(_is_flat_read(a) for a in args):
                bad.append(f"{name} at line {node.lineno}")
        assert not bad, bad

    def test_the_cycle_level_is_read_only_where_known(self):
        """Out of a charger's context ``self._cycle_vehicle_soc`` IS the
        main-settings car. Its reads are counted per function: the loop
        (one, in a charger's context), the fleet car level and range
        sensors (five), and the no-charger-list estimate (one). A new
        read — a local copy included — must say whose car it means; use
        ``_own_vehicle_soc(cid)`` for a charger."""
        allowed = {"_async_update_data": 6, "_update_ev_intelligence": 1}
        tree = ast.parse(textwrap.dedent(inspect.getsource(SEMCoordinator)))
        counts: dict = {}
        for fn in tree.body[0].body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if (_is_flat_read(node) and node.attr == "_cycle_vehicle_soc"
                        and isinstance(node.ctx, ast.Load)):
                    counts[fn.name] = counts.get(fn.name, 0) + 1
        assert counts, "premise: the known reads were found"
        over = {k: v for k, v in counts.items() if v > allowed.get(k, 0)}
        assert not over, over

    def test_the_flat_level_is_read_in_one_place(self):
        """Only the property and ``_own_vehicle_soc`` read the backing
        value of the main-settings car level."""
        tree = ast.parse(textwrap.dedent(inspect.getsource(SEMCoordinator)))
        readers = set()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Attribute)
                        and node.attr == "_cycle_vehicle_soc_default"
                        and isinstance(node.ctx, ast.Load)):
                    readers.add(fn.name)
                if (isinstance(node, ast.Constant)
                        and node.value == "_cycle_vehicle_soc_default"):
                    readers.add(fn.name)
        assert readers <= {"_cycle_vehicle_soc", "_own_vehicle_soc"}, readers

    def test_the_seed_asks_for_the_chargers_own_level(self):
        enter = _pcc_mod.PerChargerContext.__enter__
        assert calls(enter, "_own_vehicle_soc")
        assert not reads_attribute(enter, "coord", "_cycle_vehicle_soc")
