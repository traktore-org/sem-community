"""#782 — a counter that resets and recovers books its whole lifetime.

onkelfu's energy-balance health check: "members sum to 15512.77 kWh against
a fleet total of 33.47 kWh". One member did it —
``energy_dashboard_warmepumpe_energy_gesamt_2 = 15508.51 kWh`` today; every
other device is between 0.00 and 1.48.

The sequence takes three cycles. The counter reads its lifetime total; the
integration restarts and it reads 0; it comes back. ``delta < 0`` catches
the drop and re-baselines to 0 — and there the guard's memory ends. The
next reading is 15508.51 against a baseline of 0, a positive delta, so it
is booked as consumption. 15508.51 kWh in one ~10 s cycle is 5.6 GW.

The fix is not #774's error. ``rated_power`` is an estimate about THIS
device and must never overrule its meter. This is a bound on what any
window can physically deliver — no house circuit hands a single load
100 kW — so it only ever catches counter pathology, never usage. And the
window is the one the delta actually spans, blind seconds included, so a
delta that bridges an unreadable stretch (#755 contract 1, #768) survives.

Beside it, the drop remembers what it dropped FROM, so a counter that
recovers books the genuine consumption across the outage instead of
everything or nothing.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
    DeviceState,
    SwitchDevice,
)

TODAY = date(2026, 8, 16)
_START = datetime(2026, 8, 16, 12, 0, 0)
_CURSOR = {"t": _START}


class _Clock:
    def __init__(self):
        self._states = {}
        self.states = SimpleNamespace(get=lambda e: self._states.get(e))

    def set(self, entity: str, value) -> None:
        self._states[entity] = (
            None if value is None
            else SimpleNamespace(state=str(value), attributes={})
        )


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    import custom_components.solar_energy_management.devices.base as base_mod

    _CURSOR["t"] = _START
    fake = MagicMock()
    fake.now.side_effect = lambda: _CURSOR["t"]
    fake.side_effect = lambda *a, **kw: datetime(*a, **kw)
    monkeypatch.setattr(base_mod, "datetime", fake)
    yield


def _device(hass) -> SwitchDevice:
    dev = SwitchDevice(
        hass=hass, device_id="hp", name="Wärmepumpe", rated_power=2000,
        entity_id="switch.hp", energy_entity_id="sensor.hp_kwh",
    )
    dev.control_mode = DeviceControlMode.SURPLUS
    dev._status.state = DeviceState.ACTIVE
    return dev


def _run(dev, cycles: int, seconds: float) -> None:
    if dev._daily_runtime_last_check is None:
        dev.update_daily_runtime(TODAY)
    for _ in range(cycles):
        _CURSOR["t"] = _CURSOR["t"] + timedelta(seconds=seconds)
        dev.update_daily_runtime(TODAY)


@pytest.mark.unit
class TestARecoveringCounterIsNotConsumption:

    def test_the_lifetime_total_is_not_booked_as_todays_energy(self):
        """onkelfu's exact sequence, at his cycle time."""
        hass = _Clock()
        hass.set("sensor.hp_kwh", 15508.51)
        dev = _device(hass)
        _run(dev, 1, 10)
        hass.set("sensor.hp_kwh", 0.0)      # integration restart
        _run(dev, 1, 10)
        hass.set("sensor.hp_kwh", 15508.51)  # and back
        _run(dev, 1, 10)

        assert dev.daily_energy_kwh == pytest.approx(0.0, abs=1e-6)

    def test_the_consumption_across_the_outage_is_kept(self):
        """The counter was away half an hour and the heat pump kept running.
        0.5 kWh over 30 min is 1 kW — real, and booked."""
        hass = _Clock()
        hass.set("sensor.hp_kwh", 100.0)
        dev = _device(hass)
        _run(dev, 1, 10)
        hass.set("sensor.hp_kwh", 0.0)
        _run(dev, 180, 10)                # 30 min reading a reset counter
        hass.set("sensor.hp_kwh", 100.5)
        _run(dev, 1, 10)

        assert dev.daily_energy_kwh == pytest.approx(0.5, abs=1e-3)

    def test_a_counter_that_truly_restarted_keeps_counting_from_zero(self):
        """The other half of the same ambiguity: a replaced meter really does
        count up from 0, and every one of those deltas is real energy."""
        hass = _Clock()
        hass.set("sensor.hp_kwh", 100.0)
        dev = _device(hass)
        _run(dev, 1, 60)
        hass.set("sensor.hp_kwh", 0.0)
        _run(dev, 1, 60)
        hass.set("sensor.hp_kwh", 0.02)
        _run(dev, 1, 60)
        hass.set("sensor.hp_kwh", 0.05)
        _run(dev, 1, 60)

        assert dev.daily_energy_kwh == pytest.approx(0.05, abs=1e-6)


@pytest.mark.unit
class TestNoWindowCouldDeliverThis:

    def test_a_jump_no_window_could_deliver_is_refused(self):
        """No preceding drop — the energy entity was swapped for a different
        meter. 5000 kWh in 10 s is 1.8 GW."""
        hass = _Clock()
        hass.set("sensor.hp_kwh", 10.0)
        dev = _device(hass)
        _run(dev, 1, 10)
        hass.set("sensor.hp_kwh", 5000.0)
        _run(dev, 1, 10)

        assert dev.daily_energy_kwh == pytest.approx(0.0, abs=1e-6)

    def test_the_refused_window_is_counted_blind_not_zero(self):
        """#755 contract 1: refusing to book is not measuring zero."""
        hass = _Clock()
        hass.set("sensor.hp_kwh", 10.0)
        dev = _device(hass)
        _run(dev, 1, 10)
        hass.set("sensor.hp_kwh", 5000.0)
        _run(dev, 1, 10)

        assert dev.daily_energy_blind_s == pytest.approx(10.0, abs=0.5)

    def test_the_counter_rebaselines_so_the_next_delta_is_real(self):
        """After the refusal the meter is trusted again from where it now
        stands — one bad window, not a permanently broken device."""
        hass = _Clock()
        hass.set("sensor.hp_kwh", 10.0)
        dev = _device(hass)
        _run(dev, 1, 10)
        hass.set("sensor.hp_kwh", 5000.0)
        _run(dev, 1, 10)
        hass.set("sensor.hp_kwh", 5000.04)
        _run(dev, 1, 10)

        assert dev.daily_energy_kwh == pytest.approx(0.04, abs=1e-6)


@pytest.mark.unit
class TestTheHonestDeltasAreUntouched:

    def test_an_ordinary_delta_still_books(self):
        hass = _Clock()
        hass.set("sensor.hp_kwh", 100.0)
        dev = _device(hass)
        _run(dev, 1, 60)
        hass.set("sensor.hp_kwh", 100.03)
        _run(dev, 1, 60)

        assert dev.daily_energy_kwh == pytest.approx(0.03, abs=1e-6)
        assert dev.daily_energy_source == "counter"

    def test_a_delta_spanning_a_blind_gap_survives(self):
        """The window a delta spans is not the cycle — it is the time since
        the counter was last readable. A heat pump that drew 2 kWh while its
        sensor was unavailable really drew it (#768)."""
        hass = _Clock()
        hass.set("sensor.hp_kwh", 100.0)
        dev = _device(hass)
        _run(dev, 1, 60)
        hass.set("sensor.hp_kwh", None)     # unavailable for half an hour
        _run(dev, 30, 60)
        hass.set("sensor.hp_kwh", 102.0)
        _run(dev, 1, 60)

        assert dev.daily_energy_kwh == pytest.approx(2.0, abs=1e-6)
        assert dev.daily_energy_blind_s == pytest.approx(1800.0, abs=1.0)
