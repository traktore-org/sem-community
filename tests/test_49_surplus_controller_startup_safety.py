"""Regression guard for #49 — surplus controller mass-activation on restart.

The original bug (April 2026 PROD):

> After HA restart, the surplus controller immediately activates all
> registered switch devices because:
>   1. Device state starts as ``is_active = False`` (not persisted)
>   2. Surplus power is immediately available (midday solar)
>   3. Controller sees "surplus + device not active" → activates
>      everything
>
> Towel heaters and garage lights turn on unexpectedly.

Fix history:
* `cbd8b34` — Added `STARTUP_GRACE_SECONDS = 120` to suppress
  activation for 2 minutes post-init.
* `7c45515` — **Superseded** the grace period with a stronger
  structural fix: per-device ``control_mode`` defaulting to
  ``PEAK_ONLY``. SEM only proactively activates devices that the
  user explicitly opted into ``control_mode = SURPLUS``.

The current safety relies on the DEFAULT being ``PEAK_ONLY``. If a
future refactor changes the default — or if a new device type ships
with the wrong default — the #49 regression returns. This file pins
the default structurally.

Complement to ``tests/test_307_surplus_device_pool_heatpump.py``
which covers the ``control_mode`` *behaviour* (PEAK_ONLY ignores
proactive activation, SURPLUS responds, OFF never). This file
covers the *default selection*.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    ControllableDevice,
    DeviceControlMode,
    SwitchDevice,
)


# ---------------------------------------------------------------------------
# The default — must be PEAK_ONLY for any new device subclass
# ---------------------------------------------------------------------------


class Test49ControlModeDefault:
    """The structural safety net for #49: any newly-instantiated
    ``ControllableDevice`` subclass must default to
    ``DeviceControlMode.PEAK_ONLY``. That means no proactive
    activation without explicit user opt-in.
    """

    def test_switch_device_defaults_to_peak_only(self) -> None:
        """Most common case: a hot-water relay, garage light, towel
        heater. Default must be PEAK_ONLY so SEM won't turn it on
        proactively after a restart."""
        device = SwitchDevice(
            hass=MagicMock(),
            device_id="towel_heater",
            name="Towel Heater",
            rated_power=600,
            entity_id="switch.towel_heater",
        )
        assert device.control_mode is DeviceControlMode.PEAK_ONLY

    def test_default_after_restart_simulation(self) -> None:
        """The #49 PROD trace: SEM registers a switch, surplus is
        available immediately (midday solar restart), and the device
        must NOT activate just because surplus exists. The PEAK_ONLY
        default is what prevents it."""
        device = SwitchDevice(
            hass=MagicMock(),
            device_id="garage_light",
            name="Garage Light",
            rated_power=200,
            entity_id="switch.garage_light",
        )
        # Fresh registration → default PEAK_ONLY → SEM will never
        # call activate() on this device just because surplus exists.
        # User must explicitly switch to SURPLUS to opt in.
        assert device.control_mode is DeviceControlMode.PEAK_ONLY
        # Sanity: is_active starts False (the trigger condition).
        assert device.is_active is False


# ---------------------------------------------------------------------------
# Control-mode hierarchy — the documented contract
# ---------------------------------------------------------------------------


class Test49ControlModeHierarchy:
    """Pin the documented hierarchy: ``off < peak_only < surplus``.
    Catches a refactor that accidentally changes enum values or order.
    """

    def test_all_three_modes_exist(self) -> None:
        assert DeviceControlMode.OFF
        assert DeviceControlMode.PEAK_ONLY
        assert DeviceControlMode.SURPLUS

    def test_modes_have_documented_values(self) -> None:
        """The enum values are persisted in storage and referenced by
        services and dashboards — they must not be silently renamed."""
        assert DeviceControlMode.OFF.value == "off"
        assert DeviceControlMode.PEAK_ONLY.value == "peak_only"
        assert DeviceControlMode.SURPLUS.value == "surplus"


# ---------------------------------------------------------------------------
# Storage persistence — the secondary safety check
# ---------------------------------------------------------------------------


class Test49PersistenceContract:
    """A device that the user explicitly set to SURPLUS must STAY in
    SURPLUS across restarts. The persistence layer is the
    ``UnifiedDeviceRegistry``; this test pins that the
    ``control_mode`` field is settable + readable on the device
    (so persistence has something to round-trip)."""

    def test_control_mode_is_settable_after_init(self) -> None:
        device = SwitchDevice(
            hass=MagicMock(),
            device_id="dishwasher",
            name="Dishwasher",
            rated_power=1800,
            entity_id="switch.dishwasher",
        )
        assert device.control_mode is DeviceControlMode.PEAK_ONLY

        # User opts in via service call → registry persists →
        # restored on next restart.
        device.control_mode = DeviceControlMode.SURPLUS
        assert device.control_mode is DeviceControlMode.SURPLUS

        # User opts out → goes back to PEAK_ONLY (or OFF).
        device.control_mode = DeviceControlMode.OFF
        assert device.control_mode is DeviceControlMode.OFF
