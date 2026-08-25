"""#827 — Deye's System Work Mode becomes configurable, and with it the brand
gets its FIRST discharge surface.

@ab-elco-clal: SEM has no field for the selector between **Selling First**,
**Zero Export To Load** and **Zero Export To CT** — a different register from
the Battery-First/Load-First `deye_work_mode_entity`, and "a prerequisite for
various battery-selling strategies": without Selling First the inverter will
not sell from the battery, so #778's spend half has nothing to actuate on a
Deye.

Design facts this file pins:

* the existing work-mode dict is hardcoded to TWO options and validated as
  "exactly two, distinct" — this sibling gets its OWN 3-option dict and its
  own validator, never a widening of that one;
* the write mechanism is the existing ``_write_and_verify(..., "select")``
  (read-back + rollback), behind the same ``_observer_mode`` /
  ``_actuation_enabled`` gates as every Deye write;
* the prior mode is captured in the control snapshot and RESTORED on stop —
  a Deye left in Selling First past the spend window sells the whole pack;
* **watts is not controllable on this brand** — Selling First sells at the
  inverter's own rate. The capability caveat says so; pretending otherwise
  would be the #462 lie in power form.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.coordinator.battery_adapters.deye import (
    DeyeBatteryAdapter,
)


def _hass_with_select(options, current="Zero Export To Load"):
    hass = MagicMock()
    st = MagicMock()
    st.state = current
    st.attributes = {"options": list(options)}
    hass.states.get.return_value = st
    hass.services.async_call = AsyncMock()
    return hass


def _cfg(**over):
    cfg = {
        "battery_platform": "deye",
        "deye_system_work_mode_control": True,
        "deye_system_work_mode_entity": "select.deye_system_work_mode",
        "deye_system_work_mode_selling_option": "Selling First",
        "deye_system_work_mode_zero_load_option": "Zero Export To Load",
        "deye_system_work_mode_zero_ct_option": "Zero Export To CT",
    }
    cfg.update(over)
    return cfg


OPTIONS = ["Selling First", "Zero Export To Load", "Zero Export To CT"]


def _adapter(hass=None, cfg=None):
    a = DeyeBatteryAdapter(
        hass or _hass_with_select(OPTIONS), cfg or _cfg())
    a._observer_mode = False
    a._actuation_enabled = True
    return a


class TestValidation:
    def test_all_three_labels_must_be_offered_by_the_entity(self):
        hass = _hass_with_select(["Selling First", "Zero Export To Load"])
        a = _adapter(hass=hass)
        err = a._validate_system_work_mode()
        assert err and "Zero Export To CT" in err

    def test_labels_must_be_distinct(self):
        a = _adapter(cfg=_cfg(
            deye_system_work_mode_zero_ct_option="Zero Export To Load"))
        assert a._validate_system_work_mode()

    def test_control_off_validates_clean(self):
        a = _adapter(cfg=_cfg(deye_system_work_mode_control=False))
        assert a._validate_system_work_mode() == ""


class TestTheDischargeSurface:
    def test_force_discharge_writes_selling_first(self):
        hass = _hass_with_select(OPTIONS, current="Zero Export To CT")
        a = _adapter(hass=hass)
        a._write_and_verify = AsyncMock(return_value=True)
        ok = asyncio.run(a.command_force_discharge(3000.0, floor_soc=20.0))
        assert ok
        call = a._write_and_verify.await_args_list[0]
        assert call.args[0] == "select.deye_system_work_mode"
        assert call.args[1] == "Selling First"
        assert call.args[2] == "select"

    def test_stop_restores_the_prior_mode(self):
        hass = _hass_with_select(OPTIONS, current="Zero Export To CT")
        a = _adapter(hass=hass)
        a._write_and_verify = AsyncMock(return_value=True)
        asyncio.run(a.command_force_discharge(3000.0, floor_soc=20.0))
        asyncio.run(a.command_stop_force_discharge())
        last = a._write_and_verify.await_args_list[-1]
        assert last.args[1] == "Zero Export To CT", (
            "a Deye left in Selling First past the window sells the pack"
        )

    def test_observer_mode_writes_nothing(self):
        a = _adapter()
        a._observer_mode = True
        a._write_and_verify = AsyncMock(return_value=True)
        ok = asyncio.run(a.command_force_discharge(3000.0, floor_soc=20.0))
        assert not ok
        a._write_and_verify.assert_not_awaited()

    def test_without_the_control_the_brand_still_has_no_discharge(self):
        a = _adapter(cfg=_cfg(deye_system_work_mode_control=False))
        a._write_and_verify = AsyncMock(return_value=True)
        ok = asyncio.run(a.command_force_discharge(3000.0, floor_soc=20.0))
        assert not ok
        a._write_and_verify.assert_not_awaited()

    def test_capability_carries_the_rate_caveat(self):
        a = _adapter()
        caveat = a.discharge_rate_caveat()
        assert caveat and "inverter" in caveat.lower()
