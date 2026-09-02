"""#889 — a solar-sign vote must be an OBSERVATION of the grid answering solar.

On .175 (Huawei modbus, polled) the solar-anchored voter locked "normal
(SEM convention)" at confidence 1.00 on an install whose meter is HA
convention. Every one of its votes was cast on a cycle in which the grid
had NOT moved:

* the inverter and meter registers are polled separately (p50 2.9 s,
  p90 12 s apart), so a solar step and the meter's answer to it land in
  DIFFERENT 10-s cycles — Δsolar = 3 kW with Δgrid = 0, then Δsolar = 0
  with Δgrid = −3 kW;
* a solar dropout (``unavailable`` → 0.0 in ``_read_sensor``, 104 times on
  01.09) looks like a ±4 kW swing while the meter holds.

``(d_grid * d_solar) < 0`` is False when ``d_grid == 0``, so each of those
artefact cycles was a full-weight "normal" vote. Four of them locked the
wrong sign; the counter voter, gated on the lock, never got a turn.

These tests drive ``_detect_grid_sign`` directly (as the #461 tests do)
and manage the per-cycle dark tally the way ``read_power`` does.
"""
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)


def _reader():
    hass = MagicMock()
    r = SensorReader(hass, {})
    r._energy_dashboard_config = None
    r._sign_vote_warmup = 0
    return r


def _cycle(r, solar_w, grid_raw_w, *, dark=()):
    """One read cycle: ``dark`` names the inputs that read unavailable."""
    r._input_dark = {name: 1 for name in dark}
    rd = MagicMock()
    rd.solar_power = float(solar_w)
    rd.grid_power = float(grid_raw_w)
    rd.battery_power = 0.0
    r._detect_grid_sign(rd)


def _drive(r, samples):
    for solar_w, grid_raw_w in samples:
        _cycle(r, solar_w, grid_raw_w)


def test_889_skewed_polls_ha_convention_must_not_lock_normal():
    """HA convention (+ = import): solar +3 kW must show as grid −3 kW —
    one cycle LATER, because the meter register lags the inverter's."""
    r = _reader()
    _drive(r, [
        (1000,   500),   # baseline: 500 W import
        (4000,   500),   # solar step lands; meter not polled yet -> Δgrid = 0
        (4000, -2500),   # meter catches up; Δsolar = 0
        (1000, -2500),   # cloud: solar drops; meter stale        -> Δgrid = 0
        (1000,   500),   # meter catches up; Δsolar = 0
        (4000,   500),
        (4000, -2500),
        (1000, -2500),
        (1000,   500),
    ])
    # Not one of those cycles showed the grid answering solar.
    assert r._grid_sign_solar_samples == 0, r._grid_sign_solar_samples
    assert not (r._grid_sign_detected and r._grid_sign_inverted is False), (
        "locked 'normal' on an HA-convention meter")


def test_889_solar_dropout_to_zero_is_not_a_swing():
    """``unavailable`` → 0.0 fakes a ±4 kW swing while the meter holds."""
    r = _reader()
    _drive(r, [(4000, -2500)])
    for _ in range(3):
        _cycle(r, 0, -2500, dark=("solar",))   # read as 0.0; grid held
        _cycle(r, 4000, -2500)                 # solar back; grid held
    assert r._grid_sign_solar_samples == 0, r._grid_sign_solar_samples
    assert r._grid_sign_detected is False


def test_889_a_dark_input_drops_the_baseline():
    """A cycle with a dark steering input is not a sample AND not a baseline:
    the delta INTO it and the delta OUT of it are both artefacts, even when
    the meter happens to move (here: a 2 kW home load switching on)."""
    r = _reader()
    _cycle(r, 1000, 500)
    _cycle(r, 0, 2500, dark=("solar",))   # Δsolar −1000, Δgrid +2000: artefact
    assert r._grid_sign_solar_samples == 0
    _cycle(r, 1000, 2500)                 # first clean cycle: baseline only
    assert r._grid_sign_solar_samples == 0
    _cycle(r, 4000, -500)                 # solar +3 kW, grid −3 kW: a real vote
    assert r._grid_sign_solar_samples == 1


def test_889_the_grid_must_answer_a_material_share_of_the_swing():
    """A meter that moved 10 % of the solar step did not answer it (a stale
    register, or the swing went somewhere the voter cannot see)."""
    r = _reader()
    _cycle(r, 1000, 500)
    _cycle(r, 4000, 200)      # Δsolar +3000, Δgrid −300 (10 %): abstain
    assert r._grid_sign_solar_samples == 0
    _cycle(r, 1000, 500)      # Δsolar −3000, Δgrid +300 (10 %): abstain
    assert r._grid_sign_solar_samples == 0
    _cycle(r, 4000, -400)     # Δsolar +3000, Δgrid −900 (30 %): a vote
    assert r._grid_sign_solar_samples == 1
    assert r._grid_sign_solar_evidence < 0   # grid moved against solar → HA


def test_889_clean_swings_still_lock_ha_convention():
    """Same install, registers polled in the same cycle: locks as before."""
    r = _reader()
    samples = [(1000, 500)]
    for _ in range(4):
        samples += [(4000, -2500), (1000, 500)]
    _drive(r, samples)
    assert r._grid_sign_detected is True
    assert r._grid_sign_inverted is True
