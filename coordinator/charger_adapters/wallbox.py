"""WallboxAdapter — explicit ``pause_resume`` switch handling (#357).

Wallbox Pulsar (and the rest of the Wallbox firmware family) does
accept ``number.set_value(0)`` as a stop signal — but the actual
contactor open is gated on the ``switch.wallbox_*_pause_resume``
control. When SEM sets the current entity to 0 without also turning
the pause switch off, some firmware revisions latch the last
non-zero setpoint internally and keep drawing handshake-level power
indefinitely.

The reporter for #357 hit exactly this on v1.6.17 (mode=off → charger
keeps charging). The bug class was supposed to be retired by the
v1.7.0 ``decide`` → ``adapter.command_disable`` flow, but the
generic adapter still relies on ``_set_current(0) + stop_session()``
without knowing the pause switch exists. This dedicated adapter
auto-discovers the pause switch from the HA entity registry and
toggles it explicitly on ``command_idle`` / ``command_disable``.

Discovery: look in the HA registry for a ``switch.*pause_resume``
entity that shares a device with the configured number entity. If
none exists, fall back to the generic behaviour (the Wallbox HA
integration changed entity ids across versions and not every
revision exposes a pause switch).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from homeassistant.helpers import entity_registry as er

from .generic import GenericAdapter

if TYPE_CHECKING:  # pragma: no cover
    from ...devices.base import CurrentControlDevice

_LOGGER = logging.getLogger(__name__)

# #548 — the Wallbox status enum (HA core ``wallbox/const.py``
# ChargerStatus) is now part of the shared cross-brand classifier in
# ``status_enum.py``, read by ``GenericAdapter`` (which this adapter
# extends). WallboxAdapter therefore inherits the status-enum-authoritative
# ``actual_charging`` / ``enable_state`` for free — it only adds the
# brand-specific pause-resume switch handling below. The evcc-connector
# concept (status enum > cloud-lagged power) is the same; it just lives in
# one place now so every brand benefits.


def _looks_like_wallbox(device: "CurrentControlDevice") -> bool:
    """Heuristic: does this device look like a Wallbox charger?

    Matches on either the integration domain (``charger_service``
    starts with ``wallbox.``) or the configured entity id containing
    ``wallbox`` somewhere — Wallbox HA integration entities are
    consistently namespaced ``*_wallbox_*``.
    """
    service = (getattr(device, "charger_service", "") or "").lower()
    if service.startswith("wallbox.") or service.startswith("wallbox_"):
        return True
    for attr in (
        "charger_service_entity_id",
        "charger_current_entity",
        "start_stop_entity",
    ):
        value = (getattr(device, attr, "") or "").lower()
        if "wallbox" in value:
            return True
    return False


class WallboxAdapter(GenericAdapter):
    """Wallbox-specific adapter — explicit pause switch handling.

    Reuses ``GenericAdapter`` for ``command_current`` /
    ``command_max`` / capability properties. Overrides only the
    idle/disable paths to also toggle the pause-resume switch when
    one is discoverable.
    """

    def __init__(self, device: "CurrentControlDevice") -> None:
        super().__init__(device)
        self._pause_switch_entity: Optional[str] = None
        self._pause_switch_searched = False

    def _discover_pause_switch(self) -> Optional[str]:
        """Find a ``switch.*pause_resume*`` entity for this Wallbox.

        Cached after the first successful (or unsuccessful) call.
        Lookup uses HA's entity registry to scope to the same device
        as the configured current-control number, so multi-Wallbox
        installs don't cross-trigger the wrong charger.
        """
        if self._pause_switch_searched:
            return self._pause_switch_entity
        self._pause_switch_searched = True

        # #487/#475: an explicitly configured switch wins — the WARNING
        # below has been telling users to set ev_start_stop_entity as
        # the workaround, but the adapter never actually read it
        # (RienduPre's "#462: adapter ignores ev_start_stop_entity").
        configured = getattr(self._device, "start_stop_entity", None) or ""
        if str(configured).startswith("switch."):
            self._pause_switch_entity = str(configured)
            _LOGGER.info(
                "Wallbox %s: using configured ev_start_stop_entity %s "
                "as the pause/resume switch",
                self._device.name, configured,
            )
            return self._pause_switch_entity

        hass = getattr(self._device, "hass", None)
        if hass is None:
            return None

        try:
            registry = er.async_get(hass)
        except Exception:  # noqa: BLE001 — registry unavailable in tests
            return None

        # Locate the device id from any of the configured entity ids.
        device_id: Optional[str] = None
        for attr in (
            "charger_service_entity_id",
            "charger_current_entity",
            "start_stop_entity",
        ):
            eid = getattr(self._device, attr, None)
            if not eid:
                continue
            entry = registry.async_get(eid)
            if entry and entry.device_id:
                device_id = entry.device_id
                break

        if device_id is None:
            return None

        # Find a switch in the same device with "pause" or "resume" in the id.
        for entry in registry.entities.values():
            if entry.device_id != device_id:
                continue
            if not entry.entity_id.startswith("switch."):
                continue
            eid_lower = entry.entity_id.lower()
            if "pause" in eid_lower or "resume" in eid_lower:
                self._pause_switch_entity = entry.entity_id
                _LOGGER.info(
                    "Wallbox pause switch discovered for %s: %s",
                    self._device.name, entry.entity_id,
                )
                return entry.entity_id

        # No pause switch found — command_disable falls back to generic
        # set_current(0) + stop_session, which some Wallbox firmware
        # latches at the last non-zero setpoint (#357). Silent failure
        # pre-#462 makes the user think their off-mode setting is
        # ignored. Logging at WARNING surfaces the gap in any
        # diagnostics dump. Workaround: pass the pause switch id
        # manually as ``ev_start_stop_entity``.
        _LOGGER.warning(
            "Wallbox %s: no pause_resume switch discovered on device %s "
            "— SEM will fall back to generic set_current(0), which some "
            "Wallbox firmware latches at the last setpoint. If off mode "
            "does not actually stop charging, the Wallbox HA integration "
            "may have renamed the switch in a recent version. Search HA "
            "for switch.wallbox_*_pause_resume and set it as "
            "ev_start_stop_entity in this charger's config. (#462)",
            self._device.name, device_id,
        )
        return None

    async def _toggle_pause_switch(self, turn_on: bool) -> None:
        """Turn the pause/resume switch on (resume) or off (pause).

        Silent no-op when no switch is discoverable. Errors are
        logged but don't abort the rest of the disable path — the
        generic ``set_current(0)`` is still the primary stop signal.
        """
        eid = self._discover_pause_switch()
        if not eid:
            return
        hass = getattr(self._device, "hass", None)
        if hass is None:
            return
        service = "turn_on" if turn_on else "turn_off"
        try:
            await hass.services.async_call(
                "switch", service, {"entity_id": eid}, blocking=True,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Wallbox %s switch.%s failed: %s",
                self._device.name, service, exc,
            )

    async def command_current(self, amps: int) -> None:
        """Set charging current — turn pause switch ON first.

        The Wallbox ``pause_resume`` switch is latching: once toggled
        off (by a previous ``command_idle`` / ``command_disable``),
        any subsequent setpoint write is accepted by the number
        entity but the contactor stays open. SEM sees the setpoint
        change but no power flows — the silent stall the H1 reviewer
        flagged on the beta.3 batch. Toggle the switch back on before
        writing the setpoint so the contactor closes and current
        starts flowing.
        """
        await self._toggle_pause_switch(turn_on=True)
        await super().command_current(amps)

    async def command_max(self) -> None:
        """Set max charging — turn pause switch ON first."""
        await self._toggle_pause_switch(turn_on=True)
        await super().command_max()

    async def command_idle(self) -> None:
        """Stop charging — set current to 0 AND pause the switch.

        ``super().command_idle()`` sets ``_last_intent``; we do not
        re-assign it (M2 reviewer note) so future intent extensions
        can't be overwritten here.
        """
        await super().command_idle()
        await self._toggle_pause_switch(turn_on=False)

    async def command_disable(self) -> None:
        """User-explicit OFF — set current to 0 AND pause the switch."""
        await super().command_disable()
        await self._toggle_pause_switch(turn_on=False)
