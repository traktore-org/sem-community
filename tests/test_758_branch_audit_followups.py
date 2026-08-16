"""#758 — the five follow-ups from the release/1.8 branch audit.

Each one is small. What they have in common is that they were all found by
reading the branch as a whole rather than by reading a feature: a default
that changes meaning on UPGRADE, a test corpus pointed at a function that
does not ship, a measurement flag set by fiat, a byte budget computed
before the last two writers, and a kill switch one caller forgot to ask.
"""
from __future__ import annotations

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from custom_components.solar_energy_management.coordinator.demand_outcome import (
    battery_draw,
)


# ── 3. A dead sensor is not a measurement of zero ────────────────────────────

class _Power:
    def __init__(self, charge_w: float, unavailable: bool = False) -> None:
        self.battery_charge_power = charge_w
        self.battery_power_unavailable = unavailable


class TestBatteryDrawHonesty:
    """``measured=True`` was returned unconditionally.

    ``battery_charge_power`` is ``max(0, battery_power)`` (types.py), and
    ``battery_power`` is 0.0 when the sensor is offline — so a dead sensor
    produced a confident zero. Contract 1 of #755 is that silence is never
    a measurement, and the record is what the morning verdict quotes.
    """

    def test_a_live_sensor_is_measured(self) -> None:
        assert battery_draw(_Power(3300.0)) == (3300.0, True)

    def test_a_genuine_idle_battery_is_still_measured(self) -> None:
        """Zero from a LIVE sensor is a real reading and must stay trainable."""
        assert battery_draw(_Power(0.0)) == (0.0, True)

    def test_a_dead_sensor_is_not_measured(self) -> None:
        assert battery_draw(_Power(0.0, unavailable=True)) == (0.0, False)

    def test_the_flag_is_optional_on_the_reading(self) -> None:
        """Older/partial PowerReadings must not crash the recorder."""
        bare = type("P", (), {"battery_charge_power": 1200.0})()
        assert battery_draw(bare) == (1200.0, True)


# ── 4. The byte budget must cover everything that lands on the entity ────────

class TestPlanAttributeBudget:
    """The trim ran before ``tomorrow`` and ``review`` were appended.

    HA's recorder drops ALL attributes for a state above 16 KiB, so an
    over-budget payload does not truncate the plan — it erases it from
    history entirely, which is exactly the surface #755 added.
    """

    def test_the_budget_counts_the_extras(self) -> None:
        from custom_components.solar_energy_management.sensor import (
            _energy_plan_attrs, _PLAN_ATTR_BUDGET_BYTES,
        )
        base = datetime(2026, 8, 13, 22, 0)
        plan = {
            "computed_at": base.isoformat(),
            "fits": True,
            "demands": [{"id": f"load:{i}", "status": "fits"} for i in range(30)],
            "slots": [
                {"start": (base + timedelta(minutes=15 * i)).isoformat(),
                 "price": 0.21, "home_w": 800.0, "level_cheap": False}
                for i in range(48)
            ],
            "blocks": [
                {"id": f"load:{i % 5}",
                 "start": (base + timedelta(minutes=15 * i)).isoformat(),
                 "end": (base + timedelta(minutes=15 * (i + 1))).isoformat(),
                 "power_w": 2000.0}
                for i in range(48)
            ],
        }
        # A review payload big enough to matter on its own.
        review = {"demands": [
            {"demand_id": f"load:{i}", "kind": "load", "code": "on_target",
             "nights": 12, "asked_kwh": 4.2, "suggested_kwh": 3.9,
             "last_kwh": 4.0} for i in range(40)
        ]}
        attrs = _energy_plan_attrs(plan, extra={"review": review})
        assert "review" in attrs
        size = len(json.dumps(attrs, default=str))
        assert size <= _PLAN_ATTR_BUDGET_BYTES, (
            f"attrs are {size} bytes — the extras escaped the budget"
        )

    def test_a_small_plan_keeps_its_timeline(self) -> None:
        from custom_components.solar_energy_management.sensor import (
            _energy_plan_attrs,
        )
        base = datetime(2026, 8, 13, 22, 0)
        plan = {
            "computed_at": base.isoformat(),
            "fits": True,
            "demands": [{"id": "ev:c1", "status": "fits"}],
            "slots": [{"start": base.isoformat(), "price": 0.2,
                       "home_w": 500.0, "level_cheap": True}],
            "blocks": [{"id": "ev:c1", "start": base.isoformat(),
                        "end": (base + timedelta(hours=1)).isoformat(),
                        "power_w": 3000.0}],
        }
        attrs = _energy_plan_attrs(plan, extra={"review": {"demands": []}})
        assert attrs["slots"]
        assert not attrs.get("timeline_omitted")


# ── 2. The planner entry point the tests use must be the one that ships ──────

class TestNoOrphanPlannerEntry:

    def test_plan_overnight_is_gone(self) -> None:
        """The compat adapter forced ``level_cheap=True`` on every slot and a
        1e9 kWh battery, so the corpus that used it was proving things about
        a night that cannot happen."""
        from custom_components.solar_energy_management.coordinator import (
            energy_planner,
        )
        assert not hasattr(energy_planner, "plan_overnight"), (
            "plan_overnight has no production caller — the corpus must use "
            "build_night_ledger + pack_night, the pair the coordinator calls"
        )

    def test_the_orphan_guard_sees_module_functions(self) -> None:
        """#653's guard only walked class methods, which is why it never
        noticed. Public module-level functions are just as orphanable, so
        the scanner must actually FIND them — asserted by naming one it
        could not see before and one it must not lose."""
        from custom_components.solar_energy_management.tests import (
            test_653_orphan_methods as guard,
        )
        seen = guard._public_functions()
        # A real module-level function with production callers.
        assert "plan_gate" in seen, (
            "the #653 scan does not reach module-level functions — the "
            "class-body walk alone is what let plan_overnight survive"
        )
        # The class-method half must keep working alongside it.
        assert "update_schedules" in guard._public_methods()
        # And the merged verdict must not now flag a live function as dead.
        assert "plan_gate" not in guard._orphans()


# ── 5. The kill switch has to mean what it says ──────────────────────────────

class TestArbitrageHonoursTheKillSwitch:

    def test_sell_gate_is_asked_only_when_actuation_is_on(self) -> None:
        import inspect
        from custom_components.solar_energy_management.coordinator import (
            coordinator as coord_mod,
        )
        src = inspect.getsource(coord_mod)
        idx = src.find("arbitrage_sell_gate(")
        assert idx > 0
        # The 400 characters before the call must contain the gate.
        window = src[max(0, idx - 400):idx]
        assert "_energy_plan_actuation" in window, (
            "arbitrage_sell_gate runs without checking the actuation kill "
            "switch — its sibling gates (plan_gate, load windows) both check"
        )


# ── 1. Consent: night actuation must not switch itself on silently ───────────

class TestUpgradeConsent:

    @pytest.mark.asyncio
    async def test_migration_writes_the_option_and_tells_the_user(self) -> None:
        """``energy_plan_actuation`` is a brand-new entity on this branch, so
        RestoreEntity has nothing to restore and every UPGRADING install
        falls to the default — night hardware control, unannounced.

        The migration makes the value explicit (a recorded decision, not an
        implied one) and posts one notification naming the kill switch."""
        from custom_components.solar_energy_management import async_migrate_entry

        hass = MagicMock()
        hass.services.async_call = AsyncMock(return_value=None)
        updated: dict = {}

        def _update(entry, **kw):
            updated.update(kw)
            for k, v in kw.items():
                setattr(entry, k, v)
        hass.config_entries.async_update_entry = Mock(side_effect=_update)

        entry = MagicMock()
        entry.version = 16
        entry.minor_version = 1
        entry.data = {"inverter_brand": "huawei"}
        entry.options = {}

        assert await async_migrate_entry(hass, entry) is True
        # 18, not 17: the planner rename (#638) appended a migration step,
        # and the chain reports its terminal version. The consent contract
        # being pinned here — option recorded, user told — is unchanged.
        assert updated.get("version") == 18
        assert updated["options"]["energy_plan_actuation"] is True

        titles = [
            c.args[2].get("title", "")
            for c in hass.services.async_call.await_args_list
            if len(c.args) > 2 and isinstance(c.args[2], dict)
        ]
        assert any("night" in t.lower() for t in titles), (
            f"no notification about night actuation: {titles}"
        )

    @pytest.mark.asyncio
    async def test_an_explicit_off_is_never_overwritten(self) -> None:
        """A user who already turned it off keeps it off, silently."""
        from custom_components.solar_energy_management import async_migrate_entry

        hass = MagicMock()
        hass.services.async_call = AsyncMock(return_value=None)
        updated: dict = {}

        def _update(entry, **kw):
            updated.update(kw)
            for k, v in kw.items():
                setattr(entry, k, v)
        hass.config_entries.async_update_entry = Mock(side_effect=_update)

        entry = MagicMock()
        entry.version = 16
        entry.minor_version = 1
        entry.data = {}
        entry.options = {"energy_plan_actuation": False}

        assert await async_migrate_entry(hass, entry) is True
        assert updated["options"]["energy_plan_actuation"] is False
        titles = [
            c.args[2].get("title", "")
            for c in hass.services.async_call.await_args_list
            if len(c.args) > 2 and isinstance(c.args[2], dict)
        ]
        assert not any("night" in t.lower() for t in titles)
