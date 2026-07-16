"""#600 — EnergyRateDeriver: derive live power from a lumpy kWh counter without
the fixed-window spike."""

import pytest

from custom_components.solar_energy_management.coordinator.energy_rate_deriver import (
    EnergyRateDeriver,
)


def test_first_reading_is_zero():
    d = EnergyRateDeriver()
    assert d.update(100.0, now_s=0.0) == 0.0


def test_normal_step_gives_average_power():
    d = EnergyRateDeriver()
    d.update(100.0, now_s=0.0)          # baseline
    # +0.5 kWh over 600 s → 0.5 * 3.6e6 / 600 = 3000 W
    assert d.update(100.5, now_s=600.0) == pytest.approx(3000.0)


def test_the_issue_spike_is_avoided():
    """The reported failure: 0.1 kWh step read in a tiny window = ~12 kW spike.
    With the actual inter-change dt (here 300 s) it's a sane 1.2 kW, and a step
    that arrives FASTER than min_dt is held (never divided by a tiny dt)."""
    d = EnergyRateDeriver(min_dt_s=5.0)
    d.update(50.0, now_s=0.0)
    # 0.1 kWh over 300 s → 1200 W (sane), not 12 kW
    assert d.update(50.1, now_s=300.0) == pytest.approx(1200.0)
    # another 0.1 kWh arriving only 2 s later (< min_dt) → held, NOT 180 kW
    assert d.update(50.2, now_s=302.0) == pytest.approx(1200.0)


def test_fast_steps_accumulate_until_min_dt():
    d = EnergyRateDeriver(min_dt_s=5.0)
    d.update(0.0, now_s=0.0)
    # steps every 2 s (< min_dt) are held while the baseline stays put …
    assert d.update(0.01, now_s=2.0) == 0.0     # baseline still at t=0
    assert d.update(0.02, now_s=4.0) == 0.0
    # … at t=6 (dt=6 ≥ 5) it divides the ACCUMULATED 0.03 kWh over 6 s = 18000 W
    assert d.update(0.03, now_s=6.0) == pytest.approx(18000.0)


def test_counter_reset_reads_zero():
    d = EnergyRateDeriver()
    d.update(9999.0, now_s=0.0)
    d.update(9999.5, now_s=600.0)               # 3000 W
    # yearly rollover: counter drops → re-baseline, read 0 (never a huge value)
    assert d.update(0.2, now_s=1200.0) == 0.0


def test_unchanged_holds_then_decays_when_idle():
    d = EnergyRateDeriver(idle_timeout_s=900.0)
    d.update(10.0, now_s=0.0)
    assert d.update(10.5, now_s=600.0) == pytest.approx(3000.0)
    # unchanged, still within idle_timeout of the last change → hold
    assert d.update(10.5, now_s=1000.0) == pytest.approx(3000.0)
    # unchanged past idle_timeout (1600 - 600 > 900) → device off → decay to 0
    assert d.update(10.5, now_s=1600.0) == 0.0


def test_max_power_clamp():
    d = EnergyRateDeriver(max_power_w=30000.0)
    d.update(0.0, now_s=0.0)
    # 10 kWh over 60 s = 600 kW → clamped to 30 kW
    assert d.update(10.0, now_s=60.0) == pytest.approx(30000.0)
    # per-reading override clamp (e.g. 2 × rated_power)
    d2 = EnergyRateDeriver()
    d2.update(0.0, now_s=0.0)
    assert d2.update(1.0, now_s=60.0, max_power_w=5000.0) == pytest.approx(5000.0)


def test_none_reading_holds_last():
    d = EnergyRateDeriver()
    d.update(10.0, now_s=0.0)
    d.update(10.5, now_s=600.0)                 # 3000 W
    assert d.update(None, now_s=700.0) == pytest.approx(3000.0)


def test_reset_forgets_baseline():
    d = EnergyRateDeriver()
    d.update(10.0, now_s=0.0)
    d.update(10.5, now_s=600.0)
    d.reset()
    assert d.last_power_w == 0.0
    # next reading is treated as a fresh baseline → 0, not a huge jump
    assert d.update(20.0, now_s=1200.0) == 0.0
