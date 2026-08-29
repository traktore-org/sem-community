"""#461 — accumulated sign-of-correlation for grid-sign autodetect.

The previous ±1 vote could lock the grid import/export convention from
as few as three consecutive instantaneous matches — fragile across
battery-flip transients, and able to lock from ONE direction only (the
export case was assumed, never measured). That mis-locked RienduPre's
Sessy P1 meter "negated" (#461).

The replacement accumulates magnitude-weighted evidence and locks only
when the dominant direction holds a strong majority of all observed
magnitude AND both an import and an export event have been physically
witnessed. A genuinely undecidable meter stays in passthrough.

Pinned here:
1. Consistent SEM convention + both directions → locks no-negate.
2. Consistent HA convention + both directions → locks negate.
3. A short single-direction transient burst does NOT lock (the old
   3-vote foot-gun).
4. A long, unanimous single-direction install eventually locks via the
   strong-single fallback.
5. Conflicting evidence (swapped/ambiguous meter) never locks.
"""
from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)

_ER_PATCH = "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get"


def _reader_with_grid(platform, entity="sensor.grid_power"):
    """Reader whose grid sensor resolves to a given integration platform."""
    hass = MagicMock()
    r = SensorReader(hass, {"grid_power_sensor": entity})
    r._sign_vote_warmup = 0
    r._energy_dashboard_config = None  # isolate from the counter path
    fake_entry = Mock()
    fake_entry.platform = platform
    fake_reg = Mock()
    fake_reg.async_get = Mock(return_value=fake_entry)
    return r, fake_reg


def _state(value):
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": "kWh"}
    return s


def _ed():
    ed = Mock()
    ed.grid_import_energy = "sensor.imp"
    ed.grid_export_energy = "sensor.exp"
    ed.grid_import_energy_list = []
    ed.grid_export_energy_list = []
    return ed


def _reader():
    hass = MagicMock()
    r = SensorReader(hass, {})
    r._energy_dashboard_config = _ed()
    r._sign_vote_warmup = 0
    return r, hass


def _drive(reader, hass, samples):
    """Feed (power, d_import_kwh, d_export_kwh) cycles; return last lock."""
    imp = [0.0]
    exp = [0.0]

    def get(eid):
        if eid == "sensor.imp":
            return _state(imp[0])
        if eid == "sensor.exp":
            return _state(exp[0])
        return None

    hass.states.get = get
    out = False
    for power, di, de in samples:
        imp[0] += di
        exp[0] += de
        readings = MagicMock()
        readings.grid_power = power
        out = reader._detect_grid_sign(readings)
    return out


def test_sem_convention_both_directions_locks_no_negate():
    """SEM meter (+export / -import) → no negation, locked False."""
    r, hass = _reader()
    # First cycle seeds the baseline (no vote). Then alternate clear
    # export (power>0, export grows) and import (power<0, import grows).
    samples = [(0, 0.0, 0.0)]
    for _ in range(12):
        samples.append((3000, 0.0, 0.02))   # exporting under SEM
        samples.append((-3000, 0.02, 0.0))  # importing under SEM
    _drive(r, hass, samples)
    assert r._grid_sign_detected is True
    assert r._grid_sign_inverted is False
    assert r._grid_sign_seen_import is True
    assert r._grid_sign_seen_export is True


def test_ha_convention_both_directions_locks_negate():
    """HA meter (+import / -export) → negation, locked True."""
    r, hass = _reader()
    samples = [(0, 0.0, 0.0)]
    for _ in range(12):
        samples.append((3000, 0.02, 0.0))   # power>0 while importing → negate
        samples.append((-3000, 0.0, 0.02))  # power<0 while exporting → negate
    _drive(r, hass, samples)
    assert r._grid_sign_detected is True
    assert r._grid_sign_inverted is True


def test_mixed_burst_with_three_in_a_row_does_not_lock():
    """The #461 regression: a 3-in-a-row run inside mixed evidence no
    longer locks. The old ±1 vote reset on each flip and locked on any
    three consecutive matches; the confidence gate now sees the run is a
    minority of all evidence and stays in passthrough."""
    r, hass = _reader()
    samples = [(0, 0.0, 0.0)]
    # 2 cycles voting "no-negate" (SEM export), then a 3-in-a-row
    # "negate" run (HA-looking). Net evidence is weakly negative →
    # confidence 1/5 = 0.2, far below the 0.75 bar.
    samples.append((3000, 0.0, 0.02))   # SEM export → no-negate
    samples.append((3000, 0.0, 0.02))   # SEM export → no-negate
    samples.append((3000, 0.02, 0.0))   # power>0 + import → negate
    samples.append((3000, 0.02, 0.0))   # negate
    samples.append((3000, 0.02, 0.0))   # negate (3-in-a-row)
    _drive(r, hass, samples)
    assert r._grid_sign_detected is False


def test_single_direction_install_locks():
    """An import-only install (no PV export) still locks — the both-
    directions requirement was dropped because a swapped meter reads
    consistently wrong in BOTH directions anyway (undecidable)."""
    r, hass = _reader()
    samples = [(0, 0.0, 0.0)]
    for _ in range(5):
        samples.append((3000, 0.02, 0.0))  # HA convention import only
    _drive(r, hass, samples)
    assert r._grid_sign_detected is True
    assert r._grid_sign_inverted is True
    assert r._grid_sign_seen_import is True
    assert r._grid_sign_seen_export is False


def test_brand_seed_huawei_no_negate():
    """Pattern A brand (huawei_solar) seeds no-negation immediately."""
    r, reg = _reader_with_grid("huawei_solar")
    with patch(_ER_PATCH, return_value=reg):
        readings = MagicMock()
        readings.grid_power = 2000.0
        readings.solar_power = None
        r._detect_grid_sign(readings)
    assert r._grid_sign_detected is True
    assert r._grid_sign_inverted is False


def test_brand_seed_solaredge_negate():
    """Pattern B brand (solaredge) seeds negation immediately."""
    r, reg = _reader_with_grid("solaredge")
    with patch(_ER_PATCH, return_value=reg):
        readings = MagicMock()
        readings.grid_power = 2000.0
        readings.solar_power = None
        r._detect_grid_sign(readings)
    assert r._grid_sign_detected is True
    assert r._grid_sign_inverted is True


def test_brand_seed_deyecloud_negate():
    """#554 — Deye via hass-deyecloud: totalgridpower is +=import /
    −=export (verified from the reporter's diagnostics); seeds negation
    deterministically so the direction is right from the first cycle."""
    r, reg = _reader_with_grid("deyecloud")
    with patch(_ER_PATCH, return_value=reg):
        readings = MagicMock()
        readings.grid_power = -4900.0  # exporting 4.9 kW, Deye convention
        readings.solar_power = None
        r._detect_grid_sign(readings)
    assert r._grid_sign_detected is True
    assert r._grid_sign_inverted is True


def test_unknown_platform_does_not_seed():
    """A separate P1/CT meter (unknown platform) falls through to stats."""
    r, reg = _reader_with_grid("sessy")
    with patch(_ER_PATCH, return_value=reg):
        readings = MagicMock()
        readings.grid_power = 2000.0
        readings.solar_power = None
        r._detect_grid_sign(readings)
    assert r._grid_sign_detected is False


def test_brand_seed_overridden_by_solar():
    """A wrong brand seed self-heals once solar disagrees with confidence."""
    r, reg = _reader_with_grid("huawei_solar")  # seeds no-negate (False)
    with patch(_ER_PATCH, return_value=reg):
        seed = MagicMock()
        seed.grid_power = 2000.0
        seed.solar_power = None
        seed.battery_power = None
        r._detect_grid_sign(seed)
        assert r._grid_sign_inverted is False  # brand-seeded
        # Feed sustained solar swings where grid moves AGAINST solar → HA.
        samples = [(1000.0, 500.0)]
        for _ in range(22):
            samples.append((4000.0, -2500.0))
            samples.append((1000.0, 500.0))
        for solar, grid in samples:
            rd = MagicMock()
            rd.solar_power = solar
            rd.grid_power = grid
            rd.battery_power = None
            r._detect_grid_sign(rd)
    assert r._grid_sign_inverted is True  # solar overrode the brand seed


def _reader_solar():
    """Reader with NO energy-dashboard counters — isolates the solar path."""
    hass = MagicMock()
    r = SensorReader(hass, {})
    r._energy_dashboard_config = None
    r._sign_vote_warmup = 0
    return r


def _drive_solar(reader, samples):
    """Feed (solar_w, raw_grid_w) cycles through the solar-anchored path."""
    out = False
    for solar, grid in samples:
        readings = MagicMock()
        readings.solar_power = solar
        readings.grid_power = grid
        out = reader._detect_grid_sign(readings)
    return out


def test_solar_comovement_locks_no_negate():
    """Grid rises with solar → +export meter (SEM) → no negation."""
    r = _reader_solar()
    samples = [(1000.0, 500.0)]
    for _ in range(4):
        samples.append((4000.0, 3500.0))  # solar up 3k, grid up 3k → SEM
        samples.append((1000.0, 500.0))   # solar down 3k, grid down 3k → SEM
    _drive_solar(r, samples)
    assert r._grid_sign_detected is True
    assert r._grid_sign_inverted is False


def test_solar_comovement_locks_negate():
    """Grid falls as solar rises → +import meter (HA) → negation."""
    r = _reader_solar()
    samples = [(1000.0, 500.0)]
    for _ in range(4):
        samples.append((4000.0, -2500.0))  # solar up 3k, grid down 3k → HA
        samples.append((1000.0, 500.0))    # solar down 3k, grid up 3k → HA
    _drive_solar(r, samples)
    assert r._grid_sign_detected is True
    assert r._grid_sign_inverted is True


def test_small_solar_swings_do_not_vote():
    """Sub-threshold solar wiggles never accumulate (load-jitter guard)."""
    r = _reader_solar()
    samples = [(1000.0, 500.0)]
    for _ in range(10):
        samples.append((1200.0, 700.0))  # Δsolar 200 < 500 → ignored
        samples.append((1000.0, 500.0))
    _drive_solar(r, samples)
    assert r._grid_sign_detected is False
    assert r._grid_sign_solar_samples == 0


def _drive_solar_batt(reader, samples):
    """Feed (solar_w, raw_grid_w, battery_w) cycles."""
    out = False
    for solar, grid, batt in samples:
        readings = MagicMock()
        readings.solar_power = solar
        readings.grid_power = grid
        readings.battery_power = batt
        out = reader._detect_grid_sign(readings)
    return out


def test_battery_absorbing_swing_does_not_vote():
    """A charging battery intercepts the solar swing → no vote cast."""
    r = _reader_solar()
    samples = [(1000.0, 500.0, 0.0)]
    for _ in range(6):
        samples.append((4000.0, 3500.0, 2000.0))  # battery charging 2 kW
        samples.append((1000.0, 500.0, 2000.0))
    _drive_solar_batt(r, samples)
    assert r._grid_sign_detected is False
    assert r._grid_sign_solar_samples == 0


def test_battery_quiet_swing_votes():
    """With the battery near-idle the swing reaches the grid → locks."""
    r = _reader_solar()
    samples = [(1000.0, 500.0, 50.0)]
    for _ in range(4):
        samples.append((4000.0, 3500.0, 50.0))  # battery idle
        samples.append((1000.0, 500.0, 50.0))
    _drive_solar_batt(r, samples)
    assert r._grid_sign_detected is True
    assert r._grid_sign_inverted is False


def test_solar_overrides_wrong_counter_lock():
    """A sustained, confident solar verdict self-heals a wrong prior lock."""
    r = _reader_solar()
    # Simulate a wrong counter-derived lock already in place (negating).
    r._grid_sign_detected = True
    r._grid_sign_inverted = True
    # Feed many big SEM-consistent swings (implied: no-negate) → override.
    samples = [(1000.0, 500.0)]
    for _ in range(22):
        samples.append((4000.0, 3500.0))
        samples.append((1000.0, 500.0))
    _drive_solar(r, samples)
    assert r._grid_sign_detected is True
    assert r._grid_sign_inverted is False  # healed to SEM


def test_solar_agreeing_lock_is_not_flipped():
    """A correct lock that the solar signal agrees with is never disturbed."""
    r = _reader_solar()
    r._grid_sign_detected = True
    r._grid_sign_inverted = False  # correct SEM lock
    samples = [(1000.0, 500.0)]
    for _ in range(22):
        samples.append((4000.0, 3500.0))  # SEM-consistent → agrees
        samples.append((1000.0, 500.0))
    _drive_solar(r, samples)
    assert r._grid_sign_inverted is False  # untouched


def test_conflicting_evidence_never_locks():
    """An ambiguous meter (50/50 contradictory votes) stays in passthrough."""
    r, hass = _reader()
    samples = [(0, 0.0, 0.0)]
    # Same direction counter, but power sign flips half the time — evidence
    # cancels, confidence stays far below the 0.85 bar.
    for i in range(30):
        power = 3000 if i % 2 == 0 else -3000
        samples.append((power, 0.02, 0.0))
    _drive(r, hass, samples)
    assert r._grid_sign_detected is False
