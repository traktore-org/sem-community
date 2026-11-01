"""#1235 — a counter that dips to 0 and comes back at the SAME value booked
nothing, correctly, but logged a WARNING that called it a reset. Only a
counter that came back higher has anything to say."""
from __future__ import annotations

import logging

import pytest

from .test_782_counter_recovery import _Clock, _clock, _device, _run  # noqa: F401

_LOG = "custom_components.solar_energy_management.devices.base"


def _dip(back_to, caplog):
    hass = _Clock()
    hass.set("sensor.hp_kwh", 4109.0)
    dev = _device(hass)
    _run(dev, 1, 10)
    hass.set("sensor.hp_kwh", 0.0)
    _run(dev, 6, 10)
    hass.set("sensor.hp_kwh", back_to)
    with caplog.at_level(logging.DEBUG, logger=_LOG):
        _run(dev, 1, 10)
    return dev


def _recovery(caplog):
    return [r for r in caplog.records if "energy counter" in r.getMessage()
            and "recovered" in r.getMessage()]


@pytest.mark.unit
def test_back_at_the_same_value_is_not_a_warning(caplog):
    dev = _dip(4109.0, caplog)
    assert dev.daily_energy_kwh == pytest.approx(0.0, abs=1e-6)
    rows = _recovery(caplog)
    assert rows and all(r.levelno == logging.DEBUG for r in rows)
    assert not any("reset" in r.getMessage() for r in rows)


@pytest.mark.unit
def test_back_higher_still_warns_and_books_the_gain(caplog):
    dev = _dip(4109.4, caplog)
    assert dev.daily_energy_kwh == pytest.approx(0.4, abs=1e-3)
    assert any(r.levelno == logging.WARNING for r in _recovery(caplog))
