"""#1294 — a HomeWizard P1 meter read its import as export after a restart.

@mzijderhand (Dutch HA, HomeWizard P1 "Vermogen" picked as Grid power, an
Anker battery read through a HomeWizard kWh meter): on 2.3.0-beta.1 the first
minutes after a restart read the P1's +976 W import as 1211 W of export. The
house read 0 W (the balance went negative and was clamped), the #589 audit
warned that the import counter was rising, and 3 minutes later the balance
self-heal flipped the sign back.

A P1 meter reads the utility meter, so its sign is known: + while importing.
SEM knew it (#1172 seeds it), but the seed ran only while nothing was locked.
The store held a lock that read import as export — the audit fires only on a
lock, so it was there from the first cycle — and that lock won. The balance
self-heal can write such a lock on this home: it blames the grid when the
battery is what is wrong.

Closed at the read: a meter whose model fixes its sign takes it on every
cycle, over any lock, and the self-heal stands down, as on a pair (#1215).
"""
from __future__ import annotations

import ast
import inspect
import logging
import textwrap
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import sensor_reader as sr
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.solar_energy_management.ha_energy_reader import _parse_prefs

from .test_1172_declared_power_key import (
    _KWH, _W, EXPORT, IMPORT, POWER, PREFS, _p1_meter,
)
from .test_1192_flip_with_no_grid_source import _press
from .test_diagnostics import coordinator, entry, mock_hass  # noqa: F401

SOLAR = "sensor.solaredge_current_power"
BATTERY = "sensor.alphaess_battery_power"
SOURCE = f"combined:{POWER}"
#: What the reporter's store held: a lock on the P1 that reads + as export.
WRONG_LOCK = {"grid_detected": True, "grid_inverted": False, "grid_source": SOURCE}


#: The P1 declared in the Energy Dashboard's own grid entry (power_config).
DECLARED = {**PREFS, "energy_sources": [
    {**PREFS["energy_sources"][0], "power_config": {"stat_rate": POWER}},
    *PREFS["energy_sources"][1:]]}


def _reader(hass, *, model_id="HWE-P1", pick=True, dashboard=True, lock=None,
            p1_w="976", solar_w="100", battery_w="90", prefs=None, **cfg):
    """The reporter's home after a restart: the P1 imports ``p1_w``."""
    _p1_meter(hass, model_id=model_id)
    hass.states.async_set(POWER, p1_w, _W)
    hass.states.async_set(SOLAR, solar_w, _W)
    hass.states.async_set(BATTERY, battery_w, _W)
    config = {"update_interval": 10, **cfg}
    if pick:
        config["grid_power_sensor"] = POWER        # Sensor sources → Grid power
    if not dashboard:
        config["solar_production_sensor"] = SOLAR
    reader = SensorReader(hass, config)
    if dashboard:
        reader.set_energy_dashboard_config(
            _parse_prefs(hass, prefs or PREFS, quiet=True))
    if lock is not None:
        reader.restore_sign_state(dict(lock))
    return reader


HOMES = {
    "pick": {"pick": True},                       # the reporter's
    "dashboard": {"pick": False},                 # #1172: SEM found it
    "no_dashboard": {"pick": True, "dashboard": False},
    "declared": {"pick": False, "prefs": DECLARED},   # never had a seed
}


# ═══════════════════════════════════════════════════════════════════════
# The issue: the first cycle after a restart
# ═══════════════════════════════════════════════════════════════════════

class TestTheRestart:
    @pytest.mark.parametrize("home", sorted(HOMES))
    async def test_a_saved_wrong_lock_reads_import_on_the_first_cycle(self, hass, home):
        reader = _reader(hass, lock=WRONG_LOCK, **HOMES[home])
        readings = reader.read_power()
        assert reader._grid_source_key == SOURCE
        assert readings.grid_import_power == pytest.approx(976)   # was export
        assert readings.grid_export_power == 0
        assert reader.grid_sign_fixed() is True

    async def test_control_without_the_fixed_model_the_lock_wins(self, hass, monkeypatch):
        """The same restart with the model table empty: the saved lock reads
        import as export — the reporter's 1211 W, so the test above passes
        because of the fix."""
        monkeypatch.setattr(sr, "PLATFORM_GRID_SIGN_MODELS", {})
        reader = _reader(hass, lock=WRONG_LOCK)
        readings = reader.read_power()
        assert readings.grid_export_power == pytest.approx(976)
        assert reader.grid_sign_fixed() is None

    async def test_a_kwh_meter_keeps_its_saved_lock(self, hass):
        """A HomeWizard kWh meter reads the way it was wired: its lock is
        still the one that decides."""
        reader = _reader(hass, model_id="HWE-KWH3", lock=WRONG_LOCK)
        readings = reader.read_power()
        assert reader.grid_sign_fixed() is None
        assert readings.grid_export_power == pytest.approx(976)

    async def test_the_store_now_holds_the_meters_sign(self, hass):
        reader = _reader(hass, lock=WRONG_LOCK)
        reader.read_power()
        state = reader.export_sign_state()
        assert state["grid_detected"] is True
        assert state["grid_inverted"] is True
        assert state["grid_source"] == SOURCE

    async def test_the_replaced_lock_is_said_once(self, hass, caplog):
        reader = _reader(hass, lock=WRONG_LOCK)
        with caplog.at_level(logging.INFO):
            for _ in range(3):
                reader.read_power()
        lines = [r for r in caplog.records if "#1294" in r.getMessage()]
        assert len(lines) == 1
        assert lines[0].levelno == logging.WARNING
        assert "replaced" in lines[0].getMessage()

    async def test_a_fresh_home_is_said_at_info(self, hass, caplog):
        reader = _reader(hass)
        with caplog.at_level(logging.INFO):
            readings = reader.read_power()
        assert readings.grid_import_power == pytest.approx(976)
        lines = [r for r in caplog.records if "#1294" in r.getMessage()]
        assert [r.levelno for r in lines] == [logging.INFO]

    async def test_a_right_lock_is_not_called_replaced(self, hass, caplog):
        reader = _reader(hass, lock={**WRONG_LOCK, "grid_inverted": True})
        with caplog.at_level(logging.INFO):
            reader.read_power()
        assert not [r for r in caplog.records
                    if "#1294" in r.getMessage() and r.levelno >= logging.WARNING]


# ═══════════════════════════════════════════════════════════════════════
# Every writer of the lock — the rule is kept at the read
# ═══════════════════════════════════════════════════════════════════════

class TestNoLockMovesTheMeter:
    async def test_a_lock_set_between_reads_is_put_back(self, hass):
        reader = _reader(hass)
        reader.read_power()
        reader._grid_sign_inverted = False                 # any writer
        readings = reader.read_power()
        assert readings.grid_import_power == pytest.approx(976)
        assert reader._grid_sign_inverted is True

    async def test_the_solar_override_does_not_flip_it(self, hass):
        """Solar evidence far past the override bar, and a swing that says
        SEM's own sign: the meter's sign stays."""
        reader = _reader(hass, battery_w="0", solar_w="0", p1_w="800")
        reader.read_power()
        reader._grid_sign_solar_evidence = 1e6
        reader._grid_sign_solar_mag = 1e6
        reader._grid_sign_solar_samples = 1000
        hass.states.async_set(SOLAR, "3000", _W)
        hass.states.async_set(POWER, "3800", _W)            # moves with solar
        readings = reader.read_power()
        assert readings.grid_import_power == pytest.approx(3800)
        assert reader._grid_sign_inverted is True

    async def test_a_reset_reads_import_at_once(self, hass):
        reader = _reader(hass)
        reader.read_power()
        reader.reset_sign_state()
        readings = reader.read_power()
        assert readings.grid_import_power == pytest.approx(976)

    async def test_the_counters_never_vote_it_away(self, hass):
        """Counters that say the opposite (export rising) for many cycles,
        with the seed already spent and no lock: the voter does not run on a
        fixed meter (before the fix it locked SEM's sign, so export)."""
        reader = _reader(hass)
        reader.read_power()
        reader._brand_seed_done = True
        reader._grid_sign_detected = False
        reader._grid_sign_inverted = False
        reader._sign_vote_warmup = 0
        for i in range(30):
            hass.states.async_set(IMPORT, "12.0", _KWH)
            hass.states.async_set(EXPORT, f"{12.0 + 0.01 * i:.2f}", _KWH)
            readings = reader.read_power()
        assert reader._grid_sign_samples == 0
        assert readings.grid_import_power == pytest.approx(976)

    async def test_a_flip_tapped_on_the_meters_sign_still_applies(self, hass):
        """Fix grid sign tapped against the meter's own sign is the user's
        choice, as on a pair (#1215)."""
        reader = _reader(hass, grid_sign_user_flip=True,
                         grid_sign_user_flip_source=SOURCE,
                         grid_sign_user_flip_on_fixed=True)
        readings = reader.read_power()
        assert readings.grid_export_power == pytest.approx(976)

    async def test_grid_sign_invert_is_applied_once(self, hass):
        """The option negates the raw read and skips every detector, so the
        meter's sign is not applied on top of it (that would read export)."""
        reader = _reader(hass, grid_sign_invert=True)
        readings = reader.read_power()
        assert readings.grid_import_power == pytest.approx(976)


# ═══════════════════════════════════════════════════════════════════════
# A flip tapped against the old lock (review): it undid that lock, and the
# read no longer has it, so applied it would turn the right sign around
# ═══════════════════════════════════════════════════════════════════════

class TestAFlipTappedOnTheOldLock:
    async def test_it_is_not_applied(self, hass, caplog):
        """The #589 warning told this home to tap Fix grid sign. The flip
        then read the wrong lock right; on top of the meter's sign it would
        read the 976 W import as export, with the audit and heal silent."""
        reader = _reader(hass, lock=WRONG_LOCK, grid_sign_user_flip=True,
                         grid_sign_user_flip_source=SOURCE)
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                readings = reader.read_power()
        assert readings.grid_import_power == pytest.approx(976)
        assert reader.user_flip_applies() is False
        said = [r for r in caplog.records
                if "#1294" in r.getMessage() and "flip" in r.getMessage()]
        assert len(said) == 1

    async def test_control_before_the_fix_it_read_import_too(self, hass, monkeypatch):
        """The same home without the fixed sign: lock and flip together read
        import, which is what the fix must keep."""
        monkeypatch.setattr(sr, "PLATFORM_GRID_SIGN_MODELS", {})
        reader = _reader(hass, lock=WRONG_LOCK, grid_sign_user_flip=True,
                         grid_sign_user_flip_source=SOURCE)
        assert reader.read_power().grid_import_power == pytest.approx(976)

    async def test_a_flip_from_before_the_binding_is_not_applied(self, hass):
        """A flip with no source saved (#971) applied to the found meter."""
        reader = _reader(hass, lock=WRONG_LOCK, grid_sign_user_flip=True)
        assert reader.read_power().grid_import_power == pytest.approx(976)

    async def test_a_kwh_meter_keeps_its_flip(self, hass):
        reader = _reader(hass, model_id="HWE-KWH3", lock=WRONG_LOCK,
                         grid_sign_user_flip=True,
                         grid_sign_user_flip_source=SOURCE)
        assert reader.read_power().grid_import_power == pytest.approx(976)
        assert reader.user_flip_applies() is True

    async def test_a_tap_now_turns_the_read_around(self, hass):
        """The old flip is off as read, so a tap turns a flip on, saved
        against the meter's sign, and that one applies."""
        reader = _reader(hass, grid_sign_user_flip=True,
                         grid_sign_user_flip_source=SOURCE)
        reader.read_power()
        assert reader.user_flip_on_for_tap() is False
        options = reader.user_flip_options({}, True)
        assert options["grid_sign_user_flip"] is True
        assert options["grid_sign_user_flip_source"] == SOURCE
        assert options["grid_sign_user_flip_on_fixed"] is True
        again = _reader(hass, **options)
        assert again.read_power().grid_export_power == pytest.approx(976)
        assert again.user_flip_on_for_tap() is True
        off = again.user_flip_options(options, False)
        assert off["grid_sign_user_flip"] is False
        assert "grid_sign_user_flip_on_fixed" not in off
        assert off["grid_sign_user_flip_source"] is None

    async def test_the_service_turns_it_on_then_off(self, hass):
        """The real flip_grid_sign handler, two taps (review)."""
        old = {"grid_sign_user_flip": True, "grid_sign_user_flip_source": SOURCE}
        reader = _reader(hass, **old)
        reader.read_power()
        result, saved = await _press(old, reader)
        assert result["user_flip"] is True
        assert saved["grid_sign_user_flip_source"] == SOURCE
        assert saved["grid_sign_user_flip_on_fixed"] is True
        again = _reader(hass, **saved)
        assert again.read_power().grid_export_power == pytest.approx(976)
        result, saved = await _press(saved, again)
        assert result["user_flip"] is False
        assert "grid_sign_user_flip_on_fixed" not in saved
        last = _reader(hass, **saved)
        assert last.read_power().grid_import_power == pytest.approx(976)

    async def test_a_tap_while_the_meter_is_out_clears_a_no_meter_flip(self, hass):
        """A flip bound to no meter is not about the P1: a tap while the P1
        is out turns it off, as #1192 has it (review)."""
        reader = _reader(hass, grid_sign_user_flip=True,
                         grid_sign_user_flip_source=sr.NO_GRID_SOURCE)
        reader.read_power()
        hass.states.async_set(POWER, "unavailable", _W)
        reader.read_power()
        assert reader._tap_source() == sr.NO_GRID_SOURCE
        assert reader.user_flip_on_for_tap() is True

    async def test_with_grid_sign_invert_the_flip_stays_as_it_was(self, hass, caplog):
        """That read takes no lock, so a flip on it was not undoing one: the
        home reads as before the fix, and nothing is said about it."""
        reader = _reader(hass, grid_sign_invert=True, grid_sign_user_flip=True,
                         grid_sign_user_flip_source=SOURCE)
        with caplog.at_level(logging.WARNING):
            readings = reader.read_power()
        assert readings.grid_export_power == pytest.approx(976)
        assert reader.user_flip_applies() is True
        assert "#1294" not in caplog.text

    async def test_a_tap_on_a_kwh_meter_saves_no_mark(self, hass):
        reader = _reader(hass, model_id="HWE-KWH3")
        reader.read_power()
        assert "grid_sign_user_flip_on_fixed" not in reader.user_flip_options({}, True)


# ═══════════════════════════════════════════════════════════════════════
# The self-heal: a fault elsewhere is not blamed on the meter
# ═══════════════════════════════════════════════════════════════════════

def _coord(reader):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c._sensor_reader = reader
    c._negative_balance_count = 0
    return c


def _run(coord, cycles):
    """The coordinator's cycle: read, the self-heal behind its own gate, and
    the read again after a flip."""
    reader = coord._sensor_reader
    power = None
    for _ in range(cycles):
        power = reader.read_power()
        if power.grid_power != 0 and power.solar_power > 0:
            if coord._check_sign_flip(power):
                power = reader.read_power()
    return power


#: The reporter's battery: discharging into the house, read as charging
#: 700 W. With 100 W of sun and 50 W of import the balance is −550 W, and the
#: grid is NOT what is wrong.
_FAULT = {"p1_w": "50", "solar_w": "100", "battery_w": "700"}


class TestTheSelfHealStandsDown:
    async def test_a_battery_fault_does_not_flip_the_meter(self, hass, caplog):
        reader = _reader(hass, **_FAULT)
        coord = _coord(reader)
        with caplog.at_level(logging.WARNING):
            power = _run(coord, 18 * 3)
        assert power.solar_power == 100                      # the gate was open
        assert power.grid_import_power == pytest.approx(50)
        assert reader.export_sign_state()["grid_inverted"] is True
        assert coord._negative_balance_count == 0
        assert not getattr(coord, "_sign_flip_attempted", False)
        assert "auto-correcting grid sign" not in caplog.text

    async def test_control_a_kwh_meter_is_still_healed(self, hass):
        """Unchanged, and proof the loop reaches the self-heal: the same
        balance on a kWh meter flips its lock."""
        reader = _reader(hass, model_id="HWE-KWH3",
                         lock={**WRONG_LOCK, "grid_inverted": True}, **_FAULT)
        coord = _coord(reader)
        power = _run(coord, 18 + 1)
        assert reader._grid_sign_inverted is False
        assert power.grid_export_power == pytest.approx(50)


# ═══════════════════════════════════════════════════════════════════════
# What support sees
# ═══════════════════════════════════════════════════════════════════════

class TestTheSignReport:
    async def test_the_sign_report_says_the_meter_sets_it(self, hass):
        reader = _reader(hass, lock=WRONG_LOCK)
        reader.read_power()
        diag = reader.grid_sign_diagnostics()
        assert diag["grid_sign_fixed"] is True
        assert diag["grid_source_kind"] == "combined"
        assert diag["auto_inverted"] is True

    async def test_a_kwh_meter_report_says_not_fixed(self, hass):
        reader = _reader(hass, model_id="HWE-KWH3")
        reader.read_power()
        assert reader.grid_sign_diagnostics()["grid_sign_fixed"] is None


_IDS = (POWER, IMPORT, EXPORT)


@pytest.mark.asyncio
async def test_the_diagnostics_file_has_the_grid_sign(hass, mock_hass, entry, coordinator):  # noqa: F811
    """The reporter's file had a battery sign block and no grid one, so the
    saved lock could only be inferred from a log line. The block is the real
    reader's, so a new key that carries an entity id fails here."""
    real = _reader(hass, lock=WRONG_LOCK, grid_sign_user_flip=True,
                   grid_sign_user_flip_source=SOURCE)
    real.read_power()
    reader = MagicMock()
    reader.grid_sign_diagnostics.return_value = real.grid_sign_diagnostics()
    reader.battery_sign_diagnostics.return_value = {}
    coordinator._sensor_reader = reader
    entry.runtime_data = coordinator
    mock_hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    out = (await async_get_config_entry_diagnostics(mock_hass, entry))["grid_sign"]
    assert out["grid_platform"] == "homewizard"
    assert out["grid_sign_fixed"] is True
    assert out["grid_read_model_id"] == "HWE-P1"
    assert out["grid_source_kind"] == "combined"
    assert out["auto_inverted"] is True
    assert out["user_flip_applies"] is False
    assert not [i for i in _IDS if i in str(out)]          # ids redacted (#1270)
    assert "p1_meter" not in str(out)


@pytest.mark.asyncio
async def test_a_broken_grid_report_does_not_break_the_file(mock_hass, entry, coordinator):  # noqa: F811
    reader = MagicMock()
    reader.grid_sign_diagnostics.side_effect = RuntimeError("boom")
    reader.battery_sign_diagnostics.return_value = {}
    coordinator._sensor_reader = reader
    entry.runtime_data = coordinator
    mock_hass.data = {"solar_energy_management": {entry.entry_id: coordinator}}
    out = await async_get_config_entry_diagnostics(mock_hass, entry)
    assert out["grid_sign"] == {"error": "diagnostics_failed"}


# ═══════════════════════════════════════════════════════════════════════
# Guards
# ═══════════════════════════════════════════════════════════════════════

def _calls(fn, name):
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == name]


def test_the_self_heal_asks_whether_the_meter_sets_the_sign():
    assert _calls(SEMCoordinator._check_sign_flip, "grid_sign_fixed"), (
        "_check_sign_flip no longer asks whether the meter's model sets the sign")


def test_the_read_asks_before_any_detector():
    """The fixed sign is asked before the seed, the solar check and the
    counter vote: each of them writes the lock."""
    src = textwrap.dedent(inspect.getsource(SensorReader._detect_grid_sign))
    first = src.index("self.grid_sign_fixed()")
    for later in ("self._seed_grid_sign_from_platform()",
                  "self._accumulate_solar_sign(", "self._counter_deltas("):
        assert first < src.index(later), later
