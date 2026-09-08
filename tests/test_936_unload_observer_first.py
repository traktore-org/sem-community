"""#936 — unloading SEM must not command a battery SEM never commanded.

08.09.2026, test rig .46, observer mode ON: the clean-install routine deleted
the SEM entry, ``async_unload_entry`` ran ``command_normal()`` on both battery
adapters, and the rig's history shows the SHARED Huawei discharge-limit
register going 750 → 5000 W at that second — while PROD was holding it at
750. An observer rig, which by definition commands nothing, wrote PROD's
battery on its way out.

Guido's rule (08.09.2026): *"on uninstall SEM should go to observation mode
on and then uninstall."* Together with #908 (release what SEM started, leave
the rest): flip observer on first, then hand back ONLY what SEM itself
commanded in this lifetime.

The rule is a pure function on the adapter's own bookkeeping, so it is
tested with stand-ins that carry exactly the attributes the rule reads — a
real adapter would need a hass and a Modbus link, and the whole bug is in
WHEN the command is issued, not in what the command does.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    async_release_batteries_on_unload,
    unload_release_reason,
)


def _adapter(**state):
    """A battery adapter as the rule sees it: only the bookkeeping fields."""
    defaults = dict(_forcible_charging=False, _forcible_discharging=False,
                    _charge_adapter=None, _last_discharge_limit_w=-1.0)
    defaults.update(state)
    a = SimpleNamespace(**defaults)
    a.command_normal = AsyncMock()
    return a


class TestTheRule:
    def test_observer_mode_never_commands_even_with_a_limit_on_record(self):
        # The .46 shape: observer on, and whatever the bookkeeping says, nothing goes out.
        a = _adapter(_last_discharge_limit_w=750.0, _forcible_charging=True)
        assert unload_release_reason(a, was_observer=True) is None

    def test_a_battery_sem_never_commanded_is_left_as_found(self):
        assert unload_release_reason(_adapter(), was_observer=False) is None

    def test_a_discharge_limit_sem_wrote_is_handed_back(self):
        why = unload_release_reason(_adapter(_last_discharge_limit_w=750.0), was_observer=False)
        assert why and "750" in why

    def test_a_limit_of_zero_counts_as_written(self):
        # 0 W is a real limit SEM may have set (full discharge stop); -1 is "never".
        assert unload_release_reason(_adapter(_last_discharge_limit_w=0.0), was_observer=False)

    def test_a_forcible_operation_sem_started_is_stopped(self):
        assert unload_release_reason(_adapter(_forcible_charging=True), was_observer=False)
        assert unload_release_reason(_adapter(_forcible_discharging=True), was_observer=False)

    def test_an_active_forced_charge_on_the_charge_adapter_is_stopped(self):
        a = _adapter(_charge_adapter=SimpleNamespace(is_active=True))
        assert unload_release_reason(a, was_observer=False)

    def test_an_idle_charge_adapter_is_not_a_reason(self):
        a = _adapter(_charge_adapter=SimpleNamespace(is_active=False))
        assert unload_release_reason(a, was_observer=False) is None

    def test_garbage_bookkeeping_reads_as_never_written(self):
        a = _adapter(_last_discharge_limit_w="n/a")
        assert unload_release_reason(a, was_observer=False) is None


class TestTheUnloadHelper:
    @pytest.mark.asyncio
    async def test_observer_is_switched_on_first_and_nothing_is_written(self):
        b1, b2 = _adapter(_last_discharge_limit_w=750.0), _adapter(_forcible_charging=True)
        coord = SimpleNamespace(_observer_mode=True, _battery_adapters={"b1": b1, "b2": b2})
        outcome = await async_release_batteries_on_unload(coord)
        assert coord._observer_mode is True
        b1.command_normal.assert_not_called()
        b2.command_normal.assert_not_called()
        assert all("observer" in v for v in outcome.values())

    @pytest.mark.asyncio
    async def test_active_install_releases_only_what_it_commanded(self):
        wrote = _adapter(_last_discharge_limit_w=750.0)
        untouched = _adapter()
        forcing = _adapter(_forcible_discharging=True)
        coord = SimpleNamespace(_observer_mode=False,
                                _battery_adapters={"wrote": wrote, "untouched": untouched, "forcing": forcing})
        outcome = await async_release_batteries_on_unload(coord)
        wrote.command_normal.assert_awaited_once()
        forcing.command_normal.assert_awaited_once()
        untouched.command_normal.assert_not_called()
        assert outcome["untouched"].startswith("nothing commanded")
        assert outcome["wrote"].startswith("released")
        # and the coordinator is in observer mode from here on
        assert coord._observer_mode is True

    @pytest.mark.asyncio
    async def test_a_failing_release_never_raises(self):
        bad = _adapter(_last_discharge_limit_w=750.0)
        bad.command_normal = AsyncMock(side_effect=RuntimeError("modbus timeout"))
        coord = SimpleNamespace(_observer_mode=False, _battery_adapters={"b1": bad})
        outcome = await async_release_batteries_on_unload(coord)
        assert "failed" in outcome["b1"]

    @pytest.mark.asyncio
    async def test_no_adapters_is_a_quiet_no_op(self):
        coord = SimpleNamespace(_observer_mode=False, _battery_adapters={})
        assert await async_release_batteries_on_unload(coord) == {}
        assert coord._observer_mode is True
