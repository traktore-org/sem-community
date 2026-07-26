"""#644 — ONE anti-cycle mechanism: unified clock, rebuild-proof."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    SwitchDevice, ClimateDevice,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)


def _switch(**kw):
    h = MagicMock()
    h.services.async_call = AsyncMock()
    d = SwitchDevice(hass=h, device_id=kw.get("device_id", "d"), name="D",
                     priority=5, rated_power=1000.0,
                     entity_id="switch.d",
                     min_on_time=kw.get("min_on", 300),
                     min_off_time=kw.get("min_off", 60))
    return d


class TestUnifiedKnobs644:
    def test_switch_knobs_map_to_unified_fields(self):
        d = _switch(min_on=240, min_off=90)
        assert d.min_on_seconds == 240 and d.min_off_seconds == 90
        assert d.min_on_time == 240 and d.min_off_time == 90     # alias reads
        d.min_off_time = 120                                      # alias writes
        assert d.min_off_seconds == 120

    def test_climate_knobs_map_to_unified_fields(self):
        h = MagicMock(); h.services.async_call = AsyncMock()
        c = ClimateDevice(hass=h, device_id="ac", name="AC", priority=5,
                          rated_power=1500.0, entity_id="climate.ac",
                          min_on_time=200, min_off_time=80)
        assert c.min_on_seconds == 200 and c.min_off_seconds == 80


@pytest.mark.asyncio
class TestRebuildProofMinOff644:
    async def test_min_off_survives_a_device_rebuild(self):
        """The audit scenario: deactivated at T+0, rediscovery rebuilds at
        T+20s — the fresh object must STILL refuse to re-activate inside the
        min-off window (pre-#644 the subclass clock lived on _status and was
        wiped by the rebuild → compressor short-cycling)."""
        sc = SurplusController(MagicMock())
        old = _switch(min_off=60)
        old.record_deactivated()                       # unified epoch stamped
        sc.register_device(old)
        fresh = _switch(min_off=60)                    # the rebuild
        sc.register_device(fresh)                      # transplant carries the epoch
        assert fresh._last_deactivated is not None
        assert fresh.can_activate() is False           # base gate holds
        consumed = await fresh.activate(1000.0)        # inline guard holds too
        assert consumed == 0.0
        fresh.hass.services.async_call.assert_not_awaited()

    async def test_min_off_expires_normally(self):
        d = _switch(min_off=60)
        d._last_deactivated = datetime.now() - timedelta(seconds=120)
        assert d.can_activate() is True
        await d.activate(1000.0)
        d.hass.services.async_call.assert_awaited()

    async def test_min_on_blocks_early_deactivate_unified(self):
        d = _switch(min_on=300)
        await d.activate(1000.0)                       # stamps unified clock
        await d.deactivate()                           # inside min_on → held
        calls = [c.args[1] for c in d.hass.services.async_call.await_args_list]
        assert "turn_off" not in calls


def test_no_status_clock_used_as_gate():
    """Grep lint (the audit's closure guard): _status.last_* must never be
    read as an anti-cycle gate again — the unified epochs are the clock."""
    import pathlib, re
    src = (pathlib.Path(__file__).resolve().parents[1] / "devices" / "base.py").read_text()
    gates = re.findall(r'if self\._status\.last_(?:de)?activated:\n\s+elapsed', src)
    assert not gates, "a _status-clock anti-cycle gate returned (#644)"
