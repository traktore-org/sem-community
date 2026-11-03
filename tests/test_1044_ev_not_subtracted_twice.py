"""#1044 — the true baseload took the car out of ``home`` twice.

RienduPre, 2.1, Growatt + Wallbox Pulsar, after a ~49 kWh night session::

    sensor.sem_daily_home_energy           =   6.29 kWh
    sensor.sem_daily_true_baseload_energy  = −49.69 kWh

and ``true_baseload_power`` fell by the charging power while a car charged.

``home`` already excludes the EV — ``PowerReadings.calculate_derived`` books
``ev_power`` as its own outflow. But SEM's chargers are also devices in the
surplus controller, so the filing seam booked their kWh into the
controlled-loads mirror too, and ``true_baseload = home − controlled`` took
the car out a second time. The W twin did the same with the live draw.

#872 had drawn this line once — for the partition check, by device TYPE.
The baseload (#773) never drew it. Now one function (``home_members``)
answers for every reader, by IDENTITY: a load the user put under current
control is a ``CurrentControlDevice`` too, and its draw IS inside ``home``.
And only for the chargers ``ev_power`` actually read
(``chargers_outside_home``): a charger the reader never read is still
inside ``home``, and must still be taken away.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.health_check import (
    HealthCheck,
    chargers_outside_home,
    home_member_totals,
    home_members,
    sem_ev_chargers,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)
from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)

from .cycle_rig import CycleRig

TODAY = date(2026, 10, 3)
_NOW = datetime(2026, 10, 3, 6, 30, 0)
_COORD_DT = (
    "custom_components.solar_energy_management.coordinator.coordinator.dt_util")
_CALC_DT = (
    "custom_components.solar_energy_management.coordinator."
    "energy_calculator.dt_util")

#: RienduPre's day (#1044): home, and the car's night session.
HIS_HOME_KWH = 6.29
HIS_EV_KWH = 49.0


def _ccd(device_id, power_entity=None, current_entity=None):
    """A REAL ``CurrentControlDevice`` — the charger class, and the class a
    load under current control is built as (``device_registry``)."""
    return CurrentControlDevice(
        MagicMock(), device_id=device_id, name=device_id,
        power_entity_id=power_entity, current_entity_id=current_entity,
    )


def _booked(device, kwh, source="power"):
    """This cycle's increment, the way ``_book_energy`` leaves it."""
    device._last_cycle_energy_kwh = kwh
    device._daily_energy_kwh = kwh
    device._daily_energy_source = source
    return device


def _coord(devices, *, ev_devices=None, ev_device=None, calc=None):
    """A coordinator stub carrying exactly what the filing seam reads."""
    coord = SimpleNamespace(
        _energy_calculator=calc or EnergyCalculator({}, MagicMock()),
        _surplus_controller=SimpleNamespace(
            _devices={d.device_id: d for d in devices}),
        _ev_devices=dict(ev_devices or {}),
        _ev_device=ev_device,
    )
    coord._comfort_split_for = SEMCoordinator._comfort_split_for.__get__(coord)
    return coord


def _read(entities=(), fleet=None):
    """This cycle's readings, saying what ``ev_power`` was read from."""
    p = PowerReadings()
    p.ev_power_entities = frozenset(entities)
    p.ev_power_fleet_entity = fleet
    return p


def _file(coord, power):
    with patch(_COORD_DT) as dt:
        dt.now.return_value = _NOW
        SEMCoordinator._file_device_energy(coord, TODAY, power)


# ───────────────────────────────────────────────────────────────────────
# 1. the rule — who is inside ``home``
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheRule:
    def test_sem_charger_is_not_a_home_member(self):
        wallbox = _ccd("wallbox")
        heat_pump = SimpleNamespace(device_id="heat_pump")
        members = home_members([wallbox, heat_pump], [wallbox])
        assert wallbox not in members
        assert heat_pump in members

    def test_a_load_under_current_control_is_a_home_member(self):
        """Same class as the charger, not one of SEM's chargers: its draw is
        not in ``ev``, so it is inside ``home`` — the reason the rule is
        identity, not type."""
        wallbox, heater = _ccd("wallbox"), _ccd("heater")
        assert home_members([wallbox, heater], [wallbox]) == [heater]

    def test_identity_not_id_string(self):
        """A load that happens to share a charger's id string is still a
        different object, and still a load."""
        wallbox, namesake = _ccd("ev_charger"), _ccd("ev_charger")
        assert home_members([wallbox, namesake], [wallbox]) == [namesake]

    def test_both_charger_shapes_are_found_once(self):
        """The dict AND the late-found legacy ``_ev_device`` — deduped."""
        a, b, late = _ccd("a"), _ccd("b"), _ccd("ev_charger")
        coord = SimpleNamespace(_ev_devices={"a": a, "b": b}, _ev_device=a)
        assert sem_ev_chargers(coord) == [a, b]
        coord = SimpleNamespace(_ev_devices={}, _ev_device=late)
        assert sem_ev_chargers(coord) == [late]
        assert sem_ev_chargers(SimpleNamespace()) == []

    def test_only_chargers_ev_power_read_are_outside(self):
        a = _ccd("a", "sensor.a_power")
        b = _ccd("b", "sensor.global_power")   # no sensor of its own
        assert chargers_outside_home([a, b], _read({"sensor.a_power"})) == [a]
        assert chargers_outside_home([a, b], _read()) == []

    def test_one_fleet_sensor_stands_for_every_charger(self):
        late = _ccd("ev_charger", "sensor.box_power")
        power = _read(fleet="sensor.ed_ev_power")
        assert chargers_outside_home([late], power) == [late]

    def test_partition_members_use_the_same_rule(self):
        """#872's check, now on the shared rule: the charger is out, the
        current-controlled heater (out under #872's type rule) is in."""
        wallbox = _booked(_ccd("wallbox"), HIS_EV_KWH)
        heater = _booked(_ccd("heater"), 1.2)
        totals = home_member_totals(
            [wallbox, heater], [wallbox],
            {"wallbox": HIS_EV_KWH, "heater": 1.2})
        assert totals == {"heater": pytest.approx(1.2)}


# ───────────────────────────────────────────────────────────────────────
# 2. the kWh side — the filing seam into the midnight mirror
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheMirrorLeavesTheCarOut:
    def _his_day(self, *, chargers_known=True, late=False,
                 power=None, home=HIS_HOME_KWH):
        wallbox = _booked(_ccd("wallbox", "sensor.wallbox_power"), HIS_EV_KWH)
        heater = _booked(_ccd("heater", "sensor.heater_power"), 1.2)
        calc = EnergyCalculator({}, MagicMock())
        calc._daily_accumulators[f"home_{TODAY}"] = home
        if not chargers_known:
            coord = _coord([wallbox, heater], calc=calc)
        elif late:
            coord = _coord([wallbox, heater], ev_device=wallbox, calc=calc)
        else:
            coord = _coord([wallbox, heater],
                           ev_devices={"wallbox": wallbox}, calc=calc)
        _file(coord, power or _read({"sensor.wallbox_power"}))
        return calc

    def test_his_day_reads_a_house_not_minus_49(self):
        calc = self._his_day()
        b = calc.get_true_baseload(TODAY)
        assert b["controlled_today_kwh"] == pytest.approx(1.2)
        assert b["today_kwh"] == pytest.approx(HIS_HOME_KWH - 1.2)
        assert b["today_kwh"] > 0

    def test_the_charger_keeps_its_own_ledger_row(self):
        """Left out of the mirror, NOT out of the ledger — per-device energy
        is still published for the car."""
        calc = self._his_day()
        assert calc.get_device_energy("wallbox", TODAY)["daily_kwh"] == \
            pytest.approx(HIS_EV_KWH)
        assert calc.get_device_energy("heater", TODAY)["daily_kwh"] == \
            pytest.approx(1.2)

    def test_a_late_found_charger_is_left_out_too(self):
        """The legacy ``_ev_device`` shape, read through a fleet sensor."""
        calc = self._his_day(late=True, power=_read(fleet="sensor.ed_ev"))
        assert calc.get_true_baseload(TODAY)["controlled_today_kwh"] == \
            pytest.approx(1.2)

    def test_a_charger_ev_power_never_read_is_still_taken_away(self):
        """Review #1044: with no EV sensor read, ``home`` still holds the car
        (6.29 + 49). It must be taken away once — not zero times."""
        b = self._his_day(power=_read(),
                          home=HIS_HOME_KWH + HIS_EV_KWH).get_true_baseload(TODAY)
        assert b["controlled_today_kwh"] == pytest.approx(1.2 + HIS_EV_KWH)
        assert b["today_kwh"] == pytest.approx(HIS_HOME_KWH - 1.2)

    def test_twin_without_the_rule_reproduces_his_number(self):
        """Vacuity twin: the same seam, with no charger known, books the car
        into the mirror and the baseload goes deeply negative — the shape he
        reported. Proves the charger's kWh really reaches the seam above."""
        b = self._his_day(chargers_known=False).get_true_baseload(TODAY)
        assert b["today_kwh"] == pytest.approx(HIS_HOME_KWH - 1.2 - HIS_EV_KWH)
        assert b["today_kwh"] < -40

    def test_a_charger_never_flags_the_day_as_estimated(self):
        """A charger whose kWh is an estimate must not disqualify the
        house's day — it is not a term of it."""
        wallbox = _booked(_ccd("wallbox"), 3.0, source="rated")
        calc = EnergyCalculator({}, MagicMock())
        calc._daily_accumulators[f"home_{TODAY}"] = HIS_HOME_KWH
        _file(_coord([wallbox], ev_devices={"wallbox": wallbox}, calc=calc),
              _read(fleet="sensor.ev"))
        b = calc.get_true_baseload(TODAY)
        assert b["estimated_today_kwh"] == 0.0
        assert b["measured"] is True


# ───────────────────────────────────────────────────────────────────────
# 3. the W side — the real cycle, a real charger drawing
# ───────────────────────────────────────────────────────────────────────

WIRED = {
    "solar_production_sensor": "sensor.solar",
    "grid_power_sensor": "sensor.grid",
    "battery_power_sensor": "sensor.batt",
    "battery_soc_sensor": "sensor.soc",
    "ev_power_sensor": "sensor.ev",
    "battery_capacity_kwh": 10.0,
    "battery_reserve_soc": 20,
}
CHARGER = {
    "id": "wallbox",
    "name": "Wallbox Pulsar",
    "ev_min_current": 6,
    "ev_max_current": 16,
    "ev_phases": 3,
    "ev_voltage": 230,
    "charger_service": "keba.set_current",
    "ev_power_sensor": "sensor.ev",
    "charge_mode": "solar_only",
}
EV_W = 7000.0
HEATER_W = 300.0


async def _night_cycle(*, register_charger=True, nested=False):
    """A night: no sun, the car charging, the house importing all of it.

    ``nested``: the config-flow shape — no top-level EV sensor, the
    charger's own ``ev_charging_power_sensor`` summed per charger."""
    config, charger = dict(WIRED), dict(CHARGER)
    if nested:
        config.pop("ev_power_sensor")
        charger["ev_charging_power_sensor"] = charger["ev_power_sensor"]
    rig = CycleRig(
        config=config, chargers=[charger],
        states={"sensor.solar": 0, "sensor.grid": -8000, "sensor.batt": 0,
                "sensor.soc": 50, "sensor.ev": EV_W,
                "sensor.heater_power": HEATER_W},
    )
    wallbox = rig.coord._ev_devices["wallbox"]
    if register_charger:
        # What ``__init__.py`` does: the charger is a surplus device too.
        rig.coord._surplus_controller.register_device(wallbox)
        wallbox.managed_externally = True
    heater = _ccd("heater", "sensor.heater_power", "number.heater_amps")
    heater.hass = rig.hass
    rig.coord._surplus_controller.register_device(heater)
    result = {}
    for _ in range(3):
        result = await rig.tick()
    return rig, result


@pytest.mark.asyncio
class TestTheLivePowerLeavesTheCarOut:
    async def test_baseload_power_is_home_minus_the_house_loads(self):
        """The rig reads the car through the top-level fleet sensor — the
        same entity the charger's own power sensor names."""
        rig, data = await _night_cycle()
        assert rig.coord._ev_devices["wallbox"].observed_power_w() == EV_W
        assert data["ev_power"] == pytest.approx(EV_W, abs=1), \
            "the car must really be charging in this cycle"
        home = data["home_consumption_power"]
        assert home > HEATER_W
        assert data["true_baseload_power"] == pytest.approx(
            home - HEATER_W, abs=1)
        assert data["true_baseload_power"] > 0

    async def test_the_per_charger_sum_leaves_the_car_out_too(self):
        """The config-flow shape, end to end: the reader sums the charger's
        own sensor, and that same entity is the device's power sensor."""
        rig, data = await _night_cycle(nested=True)
        assert data["ev_power"] == pytest.approx(EV_W, abs=1)
        home = data["home_consumption_power"]
        assert home > HEATER_W
        assert data["true_baseload_power"] == pytest.approx(
            home - HEATER_W, abs=1)

    async def test_twin_the_charger_is_registered_so_the_old_sum_saw_it(self):
        """Vacuity twin: the charger sits in the surplus controller, so a sum
        over every device (the pre-fix loop) would subtract ``EV_W`` and go
        negative. The rule, not luck, keeps it out."""
        rig, data = await _night_cycle()
        devices = rig.coord._surplus_controller._devices.values()
        old_sum = sum(float(d.observed_power_w() or 0.0) for d in devices)
        assert old_sum == pytest.approx(EV_W + HEATER_W)
        assert data["home_consumption_power"] - old_sum < 0


# ───────────────────────────────────────────────────────────────────────
# 4. the drift check — chargers are not its suspects, old days are gaps
# ───────────────────────────────────────────────────────────────────────

def _row(day, baseload, *, devices=None, clean=True):
    row = {
        "date": str(day), "baseload_kwh": baseload,
        "home_kwh": baseload + 2.0, "controlled_kwh": 2.0,
        "measured": True, "estimated_kwh": 0.0,
        "devices": devices or {},
    }
    if clean is not None:
        row["home_members_only"] = clean
    return row


@pytest.mark.unit
class TestTheDriftCheck:
    def _days(self, values, **kw):
        return [_row(TODAY - timedelta(days=len(values) - 1 - i), v, **kw)
                for i, v in enumerate(values)]

    def test_a_charger_is_never_named_as_the_mover(self):
        hist = self._days([6.0, 6.0, 6.0, 6.0])
        for r in hist[:-1]:
            r["devices"] = {"wallbox": 0.0, "pool": 2.0}
        hist[-1]["baseload_kwh"] = 14.0
        hist[-1]["devices"] = {"wallbox": 49.0, "pool": 2.5}
        msg = HealthCheck().check_baseload_drift(hist, ["wallbox"])
        assert len(msg) == 1
        assert "wallbox" not in msg[0]
        # Twin: without the charger ids it is the obvious (wrong) suspect.
        assert "wallbox" in HealthCheck().check_baseload_drift(hist)[0]

    def test_old_days_are_gaps_on_a_charger_install(self):
        """Sealed before the fix, a day subtracted the car twice. With a
        charger present, such a day neither judges nor is judged."""
        old = self._days([-40.0, 6.0, -43.0, 6.0], clean=None)
        assert HealthCheck().check_baseload_drift(old, ["wallbox"]) == []
        mixed = old[:3] + [_row(TODAY, 6.0)]
        assert HealthCheck().check_baseload_drift(mixed, ["wallbox"]) == []

    def test_old_days_still_count_without_a_charger(self):
        """No charger, nothing was subtracted twice: unchanged behaviour."""
        old = self._days([6.0, 6.0, 6.0, 14.0], clean=None)
        assert len(HealthCheck().check_baseload_drift(old, [])) == 1

    def test_clean_days_are_judged_on_a_charger_install(self):
        hist = self._days([6.0, 6.0, 6.0, 14.0])
        assert len(HealthCheck().check_baseload_drift(hist, ["wallbox"])) == 1


@pytest.mark.unit
class TestTheSealStamp:
    def _power(self):
        p = PowerReadings(solar_power=0.0)
        p.calculate_derived()
        return p

    def _cycle(self, calc, now):
        with patch(_CALC_DT) as dt:
            dt.now.return_value = now
            calc.calculate_energy(self._power())

    def _seal_day(self, calc, day):
        calc._daily_accumulators[f"home_{day}"] = 6.0
        nxt = day + timedelta(days=1)
        calc._check_rollover(nxt, calc._month_key(nxt), str(nxt.year))
        return [r for r in calc.baseload_history if r["date"] == str(day)][-1]

    def test_the_upgrade_day_is_not_clean_the_next_is(self):
        calc = EnergyCalculator({}, MagicMock())
        calc.restore_state({"baseload_history": []})    # an old store
        self._cycle(calc, _NOW)
        assert calc._home_members_since == TODAY
        assert self._seal_day(calc, TODAY)["home_members_only"] is False
        nxt = TODAY + timedelta(days=1)
        assert self._seal_day(calc, nxt)["home_members_only"] is True

    def test_the_day_before_the_upgrade_is_not_clean(self):
        """A restart sealing yesterday before the first cycle stamps it."""
        calc = EnergyCalculator({}, MagicMock())
        row = self._seal_day(calc, TODAY - timedelta(days=1))
        assert row["home_members_only"] is False

    def test_the_start_day_survives_a_restart(self):
        """Storage round trip: a string on disk, a ``date`` in memory — or
        every restart would look like the upgrade day."""
        calc = EnergyCalculator({}, MagicMock())
        self._cycle(calc, _NOW)
        state = calc.get_state()
        assert state["home_members_since"] == TODAY.isoformat()
        fresh = EnergyCalculator({}, MagicMock())
        fresh.restore_state(state)
        assert fresh._home_members_since == TODAY
        later = datetime(2026, 10, 9, 12, 0, 0)
        self._cycle(fresh, later)
        assert fresh._home_members_since == TODAY

    def test_a_junk_start_day_is_dropped(self):
        calc = EnergyCalculator({}, MagicMock())
        calc.restore_state({"home_members_since": "not-a-date"})
        assert calc._home_members_since is None


# ───────────────────────────────────────────────────────────────────────
# 5. the guard — every reader that adds devices up against ``home``
# ───────────────────────────────────────────────────────────────────────

def _coordinator_tree():
    src = pathlib.Path(
        "custom_components/solar_energy_management/coordinator/coordinator.py")
    if not src.exists():
        src = pathlib.Path(__file__).parent.parent / "coordinator" / \
            "coordinator.py"
    return ast.parse(src.read_text())


def _calls(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and (
        (isinstance(n.func, ast.Attribute) and n.func.attr == name)
        or (isinstance(n.func, ast.Name) and n.func.id == name))]


@pytest.mark.unit
class TestEveryHomeReaderAsksTheRule:
    """A function that books the mirror, writes the W twin, or hands the
    partition check its members must also ask ``home_members`` (directly
    or through ``home_member_totals``) — and every ``home_member_totals``
    call must pass the chargers. Keyed on the OPERATIONS, not on function
    names, so a new reader is caught where it is written."""

    def _functions(self):
        return [n for n in ast.walk(_coordinator_tree())
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def _writes_baseload_w(self, fn):
        return any(
            isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Attribute) and t.attr == "true_baseload_power"
                for t in n.targets)
            for n in ast.walk(fn))

    def test_each_reader_asks(self):
        readers = []
        for fn in self._functions():
            if (_calls(fn, "accumulate_controlled_load")
                    or self._writes_baseload_w(fn)
                    or _calls(fn, "home_member_totals")):
                readers.append(fn)
                assert _calls(fn, "home_members") or \
                    _calls(fn, "home_member_totals"), (
                    f"{fn.name} adds devices up against home without "
                    "asking home_members — SEM's chargers are not in home")
                assert _calls(fn, "chargers_outside_home"), (
                    f"{fn.name} takes chargers out without asking which "
                    "ones ev_power read")
        names = {fn.name for fn in readers}
        assert "_file_device_energy" in names, "guard reads nothing"
        assert len(readers) >= 2

    def test_totals_always_get_the_chargers(self):
        for call in _calls(_coordinator_tree(), "home_member_totals"):
            assert len(call.args) + len(call.keywords) >= 2, (
                "home_member_totals without the chargers")

    def test_the_drift_check_gets_the_chargers(self):
        kwargs = set()
        for call in _calls(_coordinator_tree(), "run_all_checks"):
            kwargs |= {k.arg for k in call.keywords}
        assert "charger_ids" in kwargs


# ───────────────────────────────────────────────────────────────────────
# 6. the reader says what ``ev_power`` was read from
# ───────────────────────────────────────────────────────────────────────

def _mk_reader(states, chargers):
    r = SensorReader.__new__(SensorReader)
    r._ev_power_hist, r._ev_power_last, r._ev_power_hold = {}, {}, {}
    r._raw_config = {"ev_chargers": chargers}
    r._read_sensor = lambda eid, kind, **kw: states.get(eid, 0.0)
    return r


@pytest.mark.unit
class TestTheReaderSaysWhatItRead:
    def test_the_per_charger_sum_names_its_sensors(self):
        chargers = [{"id": "a", "ev_charging_power_sensor": "sensor.a"},
                    {"id": "b"}]                       # none of its own
        r = _mk_reader({"sensor.a": 4000.0}, chargers)
        readings = PowerReadings()
        assert r._read_ev_fleet_power(readings, chargers) is True
        assert readings.ev_power_entities == frozenset({"sensor.a"})
        assert readings.ev_power_fleet_entity is None

    def test_every_ev_power_write_says_its_source(self):
        """AST: each statement list in ``sensor_reader`` that sets
        ``readings.ev_power`` also sets ``ev_power_entities`` or
        ``ev_power_fleet_entity`` — the ED, legacy and per-charger
        branches, and any branch added later."""
        src = pathlib.Path(
            "custom_components/solar_energy_management/coordinator/"
            "sensor_reader.py")
        if not src.exists():
            src = pathlib.Path(__file__).parent.parent / "coordinator" / \
                "sensor_reader.py"
        tree = ast.parse(src.read_text())

        def _sets(stmt, attr):
            return isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Attribute) and t.attr == attr
                and isinstance(t.value, ast.Name) and t.value.id == "readings"
                for t in stmt.targets)

        writes = 0
        for node in ast.walk(tree):
            for field in ("body", "orelse"):
                block = getattr(node, field, None)
                if not isinstance(block, list):
                    continue
                if any(_sets(st, "ev_power") for st in block):
                    writes += 1
                    assert any(_sets(st, "ev_power_entities")
                               or _sets(st, "ev_power_fleet_entity")
                               for st in block), (
                        f"line {block[0].lineno}: ev_power set without "
                        "saying what it was read from")
        assert writes >= 4, "guard reads nothing"
