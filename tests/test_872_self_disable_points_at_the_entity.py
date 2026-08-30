"""#872 item 1 — the self-disable blames the device for the entity's fault.

Two separate things refuse a forcible-discharge write, in the same function,
on different cycles:

* **SEM's own unit check** — ``native_power_scale`` returns None because the
  entity's unit is not W/kW *or its state is unreadable*. It warns ONCE
  (``_fd_unit_refused_logged``), returns early, and deliberately does not
  count a strike: no write was attempted, so no evidence about the device
  was gathered.
* **the device** — an exception from a write we really made. Three of those
  in a row and SEM withdraws the capability (#840).

RienduPre's log shows BOTH, for both Sessy batteries. That pair is not noise,
it is the diagnosis: an entity that is readable on some cycles and not on
others. But the withdrawal message only knows about its own counter, so it
says

    Treating battery-to-grid export as unsupported on this device

and sends him to check his firmware — while the actionable fault is an
entity that keeps going unavailable. He got there before we did ("this looks
like a misdirected entity reference rather than a real hardware limitation")
and the message argued him out of it.

The counter that would have said so was thrown away: the unit check latches a
bool for log volume and never records how often it fired.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.battery_adapters.base import (  # noqa: E501
    BatteryControlAdapter,
)


class _Adapter(BatteryControlAdapter):
    async def command_normal(self): return True
    async def command_force_charge(self, watts): return True
    async def command_limit_discharge(self, watts): return True
    async def command_stop(self): return True
    async def command_stop_force_charge(self): return True

    @property
    def supports_forced_charge(self): return True

    @property
    def max_charge_power_w(self): return 5000.0

    @property
    def max_discharge_power_w(self): return 5000.0


def _adapter():
    """An entity whose readability we can flip between cycles."""
    hass = MagicMock()
    hass.states.get.return_value = MagicMock(attributes={})

    async def _call(domain, service, data, **kw):
        raise Exception("Setting value for Power Setpoint failed: "
                        "Not supported by device")

    hass.services.async_call = AsyncMock(side_effect=_call)
    return _Adapter(hass, {"battery_force_discharge_control_entity":
                           "number.sessy_1_power_setpoint"})


def _unreadable(monkeypatch):
    """Make the unit check refuse, as an unavailable entity does."""
    import custom_components.solar_energy_management.coordinator.power_control as pc
    monkeypatch.setattr(pc, "native_power_scale", lambda *a, **k: None)


def _readable(monkeypatch):
    import custom_components.solar_energy_management.coordinator.power_control as pc
    monkeypatch.setattr(pc, "native_power_scale", lambda *a, **k: 1.0)


@pytest.mark.asyncio
class TestTheUnitCheckIsCounted:
    async def test_a_unit_refusal_is_counted_not_just_latched(self, monkeypatch):
        a = _adapter()
        _unreadable(monkeypatch)
        for w in (1000.0, 1500.0, 2000.0):
            assert await a._write_force_discharge(w) is False
        assert a._fd_unit_refusals == 3, (
            "the unit check latches a bool for log volume and forgets how "
            "often it fired — so the withdrawal cannot know it happened"
        )

    async def test_a_unit_refusal_never_spends_a_device_strike(self, monkeypatch):
        """No write was attempted, so no evidence about the device exists."""
        a = _adapter()
        _unreadable(monkeypatch)
        for w in (1000.0, 1500.0, 2000.0, 2500.0):
            await a._write_force_discharge(w)
        assert a._force_discharge_failures == 0
        assert a.supports_forced_discharge is True


@pytest.mark.asyncio
class TestTheWithdrawalNamesTheRealSuspect:
    async def test_it_points_at_the_entity_when_both_have_refused(
        self, monkeypatch, caplog,
    ):
        a = _adapter()
        _unreadable(monkeypatch)
        await a._write_force_discharge(500.0)      # entity dark this cycle
        _readable(monkeypatch)
        caplog.clear()
        for w in (1000.0, 1500.0, 2000.0):         # device refuses these
            await a._write_force_discharge(w)
        text = caplog.text
        assert "no longer attempting it" in text, "it should have withdrawn"
        assert "number.sessy_1_power_setpoint" in text
        assert "unavailable" in text.lower() or "unreadable" in text.lower(), (
            "both checks refused — an intermittently available entity "
            "produces exactly this pair, and the message must say so "
            "instead of sending the user to their firmware"
        )

    async def test_a_clean_device_refusal_still_reads_as_the_device(
        self, monkeypatch, caplog,
    ):
        """No unit refusal ever → the original #840 wording is correct."""
        a = _adapter()
        _readable(monkeypatch)
        for w in (1000.0, 1500.0, 2000.0):
            await a._write_force_discharge(w)
        text = caplog.text
        assert "no longer attempting it" in text
        assert "unavailable" not in text.lower(), (
            "invented an entity problem that never happened"
        )

    async def test_the_repair_carries_the_same_suspicion(self, monkeypatch):
        """#799 — a log line is not a surface. The Repair must not say
        'unsupported device' when the evidence says 'flaky entity'."""
        a = _adapter()
        seen = {}
        a._raise_force_discharge_repair = (
            lambda err, **kw: seen.update(error=err, **kw))
        _unreadable(monkeypatch)
        await a._write_force_discharge(500.0)
        _readable(monkeypatch)
        for w in (1000.0, 1500.0, 2000.0):
            await a._write_force_discharge(w)
        assert "error" in seen, "no repair was raised"
        assert seen.get("unstable") is True, (
            "the Repair still tells the story the log has stopped telling"
        )
        assert "unreadable" in seen["error"].lower() or \
               "unavailable" in seen["error"].lower(), seen["error"]

    async def test_a_clean_device_refusal_keeps_the_device_repair(
        self, monkeypatch,
    ):
        a = _adapter()
        seen = {}
        a._raise_force_discharge_repair = (
            lambda err, **kw: seen.update(error=err, **kw))
        _readable(monkeypatch)
        for w in (1000.0, 1500.0, 2000.0):
            await a._write_force_discharge(w)
        assert seen.get("unstable") is False


class TestBothStoriesAreTranslated:
    """One repair was covering two faults, and its text asserted the wrong
    one outright: *'the inverter's firmware simply does not implement
    writing that register'*. That is a verdict, not a description, and in
    Rien's case it was false. The second story needs its own text — in
    every language, or the users who need it most read English."""

    def test_every_language_carries_the_unstable_entity_repair(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        files = [root / "strings.json"] + sorted(
            (root / "translations").glob("*.json"))
        assert len(files) >= 17, f"only found {len(files)} translation files"
        missing = []
        for f in files:
            issues = json.loads(f.read_text()).get("issues", {})
            entry = issues.get("battery_force_discharge_entity_unstable")
            if not entry or not entry.get("title") or not entry.get(
                    "description"):
                missing.append(f.name)
                continue
            # The placeholders the raiser actually supplies — a missing one
            # renders as literal braces on the Repairs page.
            for field in ("title", "description"):
                assert "{entity_id}" in entry[field] or field == "description"
            assert "{error}" in entry["description"], f.name
        assert not missing, f"no unstable-entity repair text in: {missing}"
