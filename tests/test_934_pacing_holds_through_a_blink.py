"""#934 — charge pacing restored and re-engaged the inverter's charge-limit
register on every SOC blink: a ``number.set_value`` pair per modbus dropout.

``_hold_battery_soc`` holds the last accepted SOC through a dark cycle and
raises ``battery_soc_unavailable`` on EVERY such cycle. ``_run_charge_pacing``
read that flag as "no SOC": ``soc=None`` → no decision → ``cap=None`` →
``ChargePacingWriter.apply`` RESTORED the captured register value. The next
cycle the sensor was back, the pacer re-engaged and wrote the cap again.
PROD's Huawei link blinks ~250 times a day (measured 08.09: 10.8 % of wall
time), so with pacing on that is ~500 writes a day to the charge-limit
register — the #538 collision class on the single serial modbus link.

A cap is a LIMIT, not an action: holding it through a blink is safe — the
opposite of the #932 sell gate, where acting on a held SOC was the danger.
So the hold now carries its AGE (``PowerReadings.battery_soc_stale_s``,
seconds since the last accepted read), pacing decides on the held SOC while
that age is inside ``SENSOR_DARK_READ_GRACE_S`` (the grace the entity layer
already uses for dark reads), and disengages — restoring ONCE — only when
the outage is sustained past it.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from custom_components.solar_energy_management.consts.core import (
    SENSOR_DARK_READ_GRACE_S,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)


# ─── the reader: a held value carries its age ──────────────────────────────

def _state(value):
    import homeassistant.util.dt as dt_util
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": "%"}
    s.last_updated = s.last_reported = dt_util.utcnow()
    return s


def _reader(soc_state, clock):
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get = lambda eid: _state(soc_state[0]) if eid == "sensor.soc" else None
    r = SensorReader(hass, {"battery_soc_sensor": "sensor.soc"})
    r._energy_dashboard_config = None
    r._now_monotonic = lambda: clock[0]
    return r


class TestTheHoldCarriesItsAge:
    def test_the_dataclass_default_is_no_age(self):
        assert PowerReadings().battery_soc_stale_s is None

    def test_a_fresh_read_has_no_age(self):
        soc, clock = ["78"], [1000.0]
        p = _reader(soc, clock).read_power()
        assert p.battery_soc == pytest.approx(78.0)
        assert p.battery_soc_unavailable is False
        assert p.battery_soc_stale_s is None

    def test_a_held_value_is_stamped_with_seconds_since_the_last_accepted_read(self):
        soc, clock = ["78"], [1000.0]
        r = _reader(soc, clock)
        r.read_power()
        soc[0] = "unavailable"
        clock[0] = 1030.0
        p = r.read_power()
        assert p.battery_soc == pytest.approx(78.0), "the hold itself is untouched"
        assert p.battery_soc_unavailable is True
        assert p.battery_soc_known is True
        assert p.battery_soc_stale_s == 30
        clock[0] = 1000.0 + SENSOR_DARK_READ_GRACE_S + 20
        p = r.read_power()
        assert p.battery_soc_stale_s == SENSOR_DARK_READ_GRACE_S + 20, (
            "the age keeps counting from the last ACCEPTED read, not from "
            "the previous dark cycle"
        )

    def test_the_next_accepted_read_resets_the_age(self):
        soc, clock = ["78"], [1000.0]
        r = _reader(soc, clock)
        r.read_power()
        soc[0] = "unavailable"
        clock[0] = 1100.0
        assert r.read_power().battery_soc_stale_s == 100
        soc[0] = "77"
        clock[0] = 1130.0
        p = r.read_power()
        assert p.battery_soc == pytest.approx(77.0)
        assert p.battery_soc_unavailable is False
        assert p.battery_soc_stale_s is None
        soc[0] = "unavailable"
        clock[0] = 1160.0
        assert r.read_power().battery_soc_stale_s == 30, (
            "a new outage is aged from the read that ended the previous one"
        )

    def test_never_read_has_no_age_and_is_not_known(self):
        """(#875) Before the first successful read there is nothing to hold,
        so there is nothing to age either."""
        soc, clock = ["unavailable"], [1000.0]
        r = _reader(soc, clock)
        clock[0] = 5000.0
        p = r.read_power()
        assert p.battery_soc_known is False
        assert p.battery_soc_unavailable is True
        assert p.battery_soc_stale_s is None

    def test_an_implausible_step_hold_ages_the_same_way(self):
        """(#902) A rejected level is held exactly like a dark read — and the
        age counts from the last ACCEPTED read, not from the last time the
        sensor answered."""
        soc, clock = ["93"], [1000.0]
        r = _reader(soc, clock)
        r.read_power()
        soc[0] = "0.0"
        clock[0] = 1045.0
        p = r.read_power()
        assert p.battery_soc == pytest.approx(93.0)
        assert p.battery_soc_unavailable is True
        assert p.battery_soc_stale_s == 45


# ─── the pacer: a limit is held through a blink, restored only past it ─────

def _ledger(hours=8, solar_w=6800.0, home_w=800.0):
    t0 = datetime(2026, 9, 8, 8, 0)
    return [SimpleNamespace(
        start=t0 + timedelta(hours=i), end=t0 + timedelta(hours=i + 1),
        hours=1.0, soc_kwh=6.0, home_batt_kwh=0.0, solar_w=float(solar_w),
        cap_override_w=max(0.0, solar_w - home_w), grid_committed_w=0.0,
    ) for i in range(hours)]


RESTORE_VALUE = 5000.0


def _coordinator(*, observer=False):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = MagicMock(return_value=SimpleNamespace(state=str(RESTORE_VALUE)))
    cfg = {
        "battery_charge_pacing_enabled": True,
        "battery_charge_power_limit_entity": "number.batt_charge_limit",
        "battery_max_target_soc": 100.0,
        "inverter_ac_limit_w": 20000.0,
        "battery_max_charge_power_w": 10000.0,
    }
    fake = SimpleNamespace(
        hass=hass,
        config=cfg,
        data={"battery_soc": 40.0},
        battery_capacity_kwh=21.0,
        _planning_evidence={"forecast_trust_d1": 0.9},
        _observer_mode=observer,
        _charge_pacing_writer=None,
        _today_pacing_ledger=lambda: _ledger(),
    )
    return fake, hass


def _fresh(soc=40.0):
    return PowerReadings(battery_soc=soc, battery_soc_unavailable=False,
                         battery_soc_known=True, battery_soc_stale_s=None)


def _held(soc=40.0, stale_s=30):
    """The shape production makes on a dark cycle after a successful read:
    the last accepted value, the twin flag up, and the hold's age."""
    return PowerReadings(battery_soc=soc, battery_soc_unavailable=True,
                         battery_soc_known=True, battery_soc_stale_s=stale_s)


def _never_read():
    """(#875) The shape before the first successful read."""
    return PowerReadings(battery_soc=0.0, battery_soc_unavailable=True,
                         battery_soc_known=False, battery_soc_stale_s=None)


async def _engaged():
    fake, hass = _coordinator()
    await SEMCoordinator._run_charge_pacing(fake, _fresh())
    assert fake._charge_pacing_state["action"] == "wrote", (
        "the pacer had a real day to act on — if it did not engage the "
        "blink tests below prove nothing"
    )
    cap = fake._charge_pacing_state["cap_w"]
    assert cap is not None and cap > 0
    hass.services.async_call.reset_mock()
    return fake, hass, cap


@pytest.mark.asyncio
class TestPacingHoldsThroughABlink:
    async def test_one_dark_cycle_with_a_held_soc_neither_restores_nor_writes(self):
        fake, hass, cap = await _engaged()
        await SEMCoordinator._run_charge_pacing(fake, _held(stale_s=30))
        hass.services.async_call.assert_not_awaited()
        st = fake._charge_pacing_state
        assert st["action"] == "held"
        assert st["cap_w"] == pytest.approx(cap), "the cap is unchanged"
        assert fake._charge_pacing_writer.engaged is True
        assert st["soc"] == pytest.approx(40.0), "the decision ran on the held SOC"
        assert st["soc_stale_s"] == 30, "…and says so"

    async def test_a_day_of_blinks_costs_no_extra_write(self):
        """Before the fix every blink was a restore + a re-engage write."""
        fake, hass, _cap = await _engaged()
        for age in (20, 35, 60, 90, 120, 150):
            await SEMCoordinator._run_charge_pacing(fake, _held(stale_s=age))
            assert fake._charge_pacing_state["action"] == "held"
            await SEMCoordinator._run_charge_pacing(fake, _fresh())
            assert fake._charge_pacing_state["action"] == "held"
        hass.services.async_call.assert_not_awaited()
        assert fake._charge_pacing_writer.engaged is True

    async def test_the_boundary_is_the_dark_read_grace(self):
        fake, hass, cap = await _engaged()
        await SEMCoordinator._run_charge_pacing(
            fake, _held(stale_s=SENSOR_DARK_READ_GRACE_S))
        assert fake._charge_pacing_state["action"] == "held"
        hass.services.async_call.assert_not_awaited()
        await SEMCoordinator._run_charge_pacing(
            fake, _held(stale_s=SENSOR_DARK_READ_GRACE_S + 1))
        assert fake._charge_pacing_state["action"] == "restored"

    async def test_a_sustained_outage_restores_once_and_only_once(self):
        fake, hass, _cap = await _engaged()
        await SEMCoordinator._run_charge_pacing(
            fake, _held(stale_s=SENSOR_DARK_READ_GRACE_S + 1))
        st = fake._charge_pacing_state
        assert st["action"] == "restored"
        assert st["soc"] is None, "past the grace the held value is expired"
        assert st["cap_w"] is None
        assert st["reason_code"] == "soc_expired", (
            "an expired hold is not the never-read shape — the card must be "
            "able to tell a sustained outage from a restart")
        assert st["soc_stale_s"] == SENSOR_DARK_READ_GRACE_S + 1, (
            "the hold's age is published even though no cap was decided on")
        assert "expired" in st["reason"]
        reason_at_expiry = st["reason"]
        hass.services.async_call.assert_awaited_once()
        call = hass.services.async_call.await_args
        assert call.args[0] == "number" and call.args[1] == "set_value"
        assert call.args[2]["entity_id"] == "number.batt_charge_limit"
        assert call.args[2]["value"] == pytest.approx(RESTORE_VALUE)
        assert fake._charge_pacing_writer.engaged is False
        hass.services.async_call.reset_mock()
        # Still dark: nothing more to restore, nothing written.
        await SEMCoordinator._run_charge_pacing(
            fake, _held(stale_s=SENSOR_DARK_READ_GRACE_S + 31))
        assert fake._charge_pacing_state["action"] == "idle"
        hass.services.async_call.assert_not_awaited()
        assert fake._charge_pacing_state["reason"] == reason_at_expiry, (
            "the reason prose carried a live counter — the entity's "
            "attributes would churn every cycle of an outage; the age "
            "belongs in soc_stale_s")
        assert fake._charge_pacing_state["soc_stale_s"] == SENSOR_DARK_READ_GRACE_S + 31
        # The SOC comes back: the pacer re-engages — that write is the point.
        await SEMCoordinator._run_charge_pacing(fake, _fresh())
        assert fake._charge_pacing_state["action"] == "wrote"
        hass.services.async_call.assert_awaited_once()

    async def test_a_never_read_soc_still_paces_nothing(self):
        """(#875) Unknown is not permission. Before the first read there is
        no held value to decide on — and no engagement to restore."""
        fake, hass = _coordinator()
        await SEMCoordinator._run_charge_pacing(fake, _never_read())
        st = fake._charge_pacing_state
        assert st["soc"] is None
        assert st["cap_w"] is None
        assert st["action"] == "idle"
        assert st["reason_code"] == "soc_unknown", "never read is not expired"
        assert st["soc_stale_s"] is None
        hass.services.async_call.assert_not_awaited()

    async def test_a_held_zero_is_a_reading_not_a_gap(self):
        """A pack that really read 0 % and then went dark holds 0 %: the
        buffer fill, not 'unknown'. The flag pair is what separates this
        from the never-read shape above."""
        fake, hass = _coordinator()
        await SEMCoordinator._run_charge_pacing(
            fake, _held(soc=0.0, stale_s=10))
        st = fake._charge_pacing_state
        assert st["soc"] == pytest.approx(0.0)
        assert st["reason_code"] == "buffer"

    async def test_observer_publishes_the_held_decision_and_never_writes(self):
        fake, hass = _coordinator(observer=True)
        await SEMCoordinator._run_charge_pacing(fake, _fresh())
        assert fake._charge_pacing_state["action"] == "observer"
        await SEMCoordinator._run_charge_pacing(fake, _held(stale_s=30))
        st = fake._charge_pacing_state
        assert st["action"] == "observer"
        assert st["soc"] == pytest.approx(40.0)
        assert st["cap_w"] is not None
        hass.services.async_call.assert_not_awaited()
