"""Per-charger notification flap suppression + name prefix (v1.6.9).

Tests the multi-charger surface added to ``NotificationManager``:

1. ``notify_state_change`` accepts optional ``charger_id`` + ``charger_name``
   keyword arguments.
2. Flap suppression is keyed per-charger: a state change on charger A
   does not block one on charger B.
3. Mobile messages get prefixed with ``[Wallbox Left]`` (etc.) when
   ``charger_name`` is provided. Single-charger callers (no name) see
   the legacy unprefixed message.
4. The ``{DOMAIN}_notification`` HA event payload now carries
   ``charger_id`` and ``charger_name`` keys (``None`` for fleet calls).

Back-compat for v1.6.8 callers is covered by the existing 30-test
suite in ``test_notifications.py``, which exercises the property
shims (``_last_notified_state``, ``_pending_state``,
``_pending_state_since``) — those continue to target the fleet
sentinel slot transparently.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.consts.states import ChargingState
from custom_components.solar_energy_management.coordinator.notifications import (
    NotificationManager,
    _FLAP_STABILITY_SECONDS,
)


@pytest.fixture
def hass():
    h = MagicMock()
    h.services = MagicMock()
    h.services.async_call = AsyncMock()
    h.services.has_service = MagicMock(return_value=True)
    h.bus = MagicMock()
    h.bus.async_fire = MagicMock()
    return h


@pytest.fixture
def config():
    return {
        "enable_charger_notifications": True,
        "enable_mobile_notifications": True,
        "mobile_notification_service": "notify.mobile_app_phone",
    }


@pytest.fixture
def nm(hass, config):
    n = NotificationManager(hass, config)
    # Skip service validation in tests.
    n._charger_notify_checked = True
    n._charger_notify_available = True
    n._charger_notify_service = "keba_display"
    n._mobile_service_checked = True
    n._mobile_service_available = True
    n._mobile_service_name = "mobile_app_phone"
    return n


def _bypass_flap(nm, state, key="_fleet"):
    """Pre-set per-charger flap state so a cooldown call is accepted."""
    nm._pending_state_per_charger[key] = state
    nm._pending_state_since_per_charger[key] = (
        time.monotonic() - _FLAP_STABILITY_SECONDS - 1
    )


SAMPLE_DATA = {
    "battery_soc": 65,
    "calculated_current": 10,
    "available_power": 3000,
    "daily_ev_energy": 7.5,
    "discharge_limit": 800,
}


class TestPerChargerFlapSuppression:
    """A state change on charger A must not block one on charger B,
    even when both reach the same state in quick succession."""

    @pytest.mark.asyncio
    async def test_two_chargers_each_notify_independently(self, nm):
        """Charger A and charger B both transition to SOLAR_CHARGING_ACTIVE.
        Pre-fix the fleet ``_last_notified_state`` would suppress the
        second one; post-fix each keys off its own ``charger_id``."""
        _bypass_flap(nm, ChargingState.SOLAR_CHARGING_ACTIVE, key="A")
        _bypass_flap(nm, ChargingState.SOLAR_CHARGING_ACTIVE, key="B")

        await nm.notify_state_change(
            ChargingState.SOLAR_CHARGING_ACTIVE, SAMPLE_DATA,
            charger_id="A", charger_name="Wallbox Left",
        )
        await nm.notify_state_change(
            ChargingState.SOLAR_CHARGING_ACTIVE, SAMPLE_DATA,
            charger_id="B", charger_name="Wallbox Right",
        )

        # Per-charger ``_last_notified_state`` set for both — the
        # load-bearing assertion: pre-fix the fleet ``_last_notified_state``
        # would track only one of them and suppress the other.
        assert nm._last_notified_state_per_charger["A"] == ChargingState.SOLAR_CHARGING_ACTIVE
        assert nm._last_notified_state_per_charger["B"] == ChargingState.SOLAR_CHARGING_ACTIVE
        # 3 service calls expected: KEBA notification for both chargers
        # (2 calls) plus one mobile notification — the second mobile
        # gets suppressed by the global ``_last_mobile_time`` cooldown
        # which is intentionally fleet-level (the user wants a quiet
        # phone, not "one notification per charger"). The per-charger
        # state-machine isolation is what this test pins; the mobile
        # cooldown stays fleet-wide.
        assert nm.hass.services.async_call.call_count == 3
        # Of the 3 calls, 2 are to the KEBA service (per-charger), 1
        # to the mobile service.
        keba_calls = sum(
            1 for c in nm.hass.services.async_call.call_args_list
            if "keba" in str(c).lower()
        )
        assert keba_calls == 2

    @pytest.mark.asyncio
    async def test_same_charger_twice_suppressed(self, nm):
        """Calling twice with the same charger_id and same state — the
        second call is the duplicate-state early-return."""
        _bypass_flap(nm, ChargingState.SOLAR_CHARGING_ACTIVE, key="A")
        await nm.notify_state_change(
            ChargingState.SOLAR_CHARGING_ACTIVE, SAMPLE_DATA,
            charger_id="A",
        )
        first_count = nm.hass.services.async_call.call_count
        await nm.notify_state_change(
            ChargingState.SOLAR_CHARGING_ACTIVE, SAMPLE_DATA,
            charger_id="A",
        )
        # No new calls.
        assert nm.hass.services.async_call.call_count == first_count


class TestChargerNamePrefix:
    """Mobile messages get the ``[Name]`` prefix when ``charger_name``
    is provided. The KEBA-display message is unprefixed (the charger
    already knows it's itself)."""

    @pytest.mark.asyncio
    async def test_mobile_message_is_prefixed(self, nm):
        _bypass_flap(nm, ChargingState.SOLAR_CHARGING_ACTIVE, key="A")
        await nm.notify_state_change(
            ChargingState.SOLAR_CHARGING_ACTIVE, SAMPLE_DATA,
            charger_id="A", charger_name="Wallbox Left",
        )
        # The bus event carries the (possibly-prefixed) mobile message
        # — assert against the event payload as the source of truth.
        evt_kwargs = nm.hass.bus.async_fire.call_args
        evt_data = evt_kwargs.args[1] if evt_kwargs.args else evt_kwargs.kwargs.get("event_data") or {}
        message = evt_data.get("message", "")
        assert message.startswith("[Wallbox Left] ")

    @pytest.mark.asyncio
    async def test_no_name_no_prefix(self, nm):
        _bypass_flap(nm, ChargingState.SOLAR_CHARGING_ACTIVE)
        await nm.notify_state_change(
            ChargingState.SOLAR_CHARGING_ACTIVE, SAMPLE_DATA,
        )
        evt_kwargs = nm.hass.bus.async_fire.call_args
        evt_data = evt_kwargs.args[1] if evt_kwargs.args else evt_kwargs.kwargs.get("event_data") or {}
        message = evt_data.get("message", "")
        assert not message.startswith("[")


class TestEventPayload:
    """The ``solar_energy_management_notification`` HA event now carries
    ``charger_id`` and ``charger_name`` keys so automations can
    distinguish per-charger events. ``None`` values stay in the dict for
    consistency rather than being dropped."""

    @pytest.mark.asyncio
    async def test_charger_keys_in_event(self, nm):
        _bypass_flap(nm, ChargingState.SOLAR_CHARGING_ACTIVE, key="A")
        await nm.notify_state_change(
            ChargingState.SOLAR_CHARGING_ACTIVE, SAMPLE_DATA,
            charger_id="A", charger_name="Wallbox Left",
        )
        evt_kwargs = nm.hass.bus.async_fire.call_args
        evt_data = evt_kwargs.args[1] if evt_kwargs.args else evt_kwargs.kwargs.get("event_data") or {}
        assert evt_data.get("charger_id") == "A"
        assert evt_data.get("charger_name") == "Wallbox Left"

    @pytest.mark.asyncio
    async def test_fleet_call_has_none_charger_keys(self, nm):
        _bypass_flap(nm, ChargingState.SOLAR_CHARGING_ACTIVE)
        await nm.notify_state_change(
            ChargingState.SOLAR_CHARGING_ACTIVE, SAMPLE_DATA,
        )
        evt_kwargs = nm.hass.bus.async_fire.call_args
        evt_data = evt_kwargs.args[1] if evt_kwargs.args else evt_kwargs.kwargs.get("event_data") or {}
        assert "charger_id" in evt_data and evt_data["charger_id"] is None
        assert "charger_name" in evt_data and evt_data["charger_name"] is None


class TestBackCompatShims:
    """Existing tests + external callers can still read/write
    ``_last_notified_state``, ``_pending_state``, ``_pending_state_since``
    as scalars. The shims target the fleet sentinel slot."""

    def test_set_and_get_scalar(self, nm):
        nm._last_notified_state = "TEST_STATE"
        assert nm._last_notified_state == "TEST_STATE"
        # Stored under the fleet sentinel.
        assert nm._last_notified_state_per_charger["_fleet"] == "TEST_STATE"

    def test_set_none_clears(self, nm):
        nm._last_notified_state = "TEST_STATE"
        nm._last_notified_state = None
        # Removed from the dict (rather than left as None) so the
        # ``in`` check on the dict is meaningful.
        assert "_fleet" not in nm._last_notified_state_per_charger

    def test_pending_state_since_default(self, nm):
        # Default value when unset is 0.0 — matches the legacy
        # scalar default (``self._pending_state_since: float = 0.0``).
        assert nm._pending_state_since == 0.0
