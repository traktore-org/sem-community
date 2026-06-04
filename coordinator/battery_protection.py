"""Battery discharge protection mixin retained for startup-restore only.

The active per-cycle protection path was retired in v1.7.0 — battery
discharge limits are now driven by ``decide_battery`` →
``actuate_battery`` through the ``BatteryControlAdapter`` (see
``coordinator._run_battery_pipeline``). Only the startup-restore hook
remains here; it will move into the adapter ``init`` in v1.7.1
(planned PR H) and this mixin will be deleted then.
"""
from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)


class BatteryProtectionMixin:
    """Startup-only battery discharge restore.

    Expects the coordinator to have these attributes:
    - config, hass
    """

    async def _restore_battery_discharge_limit_on_startup(self) -> None:
        """Restore battery discharge limit to max on startup.

        After a restart the adapter's ``last_discharge_limit_w``
        hysteresis is empty, so a stale limit left behind by a previous
        run could leak past ``decide_battery``'s NORMAL intent. This
        unconditionally pushes the configured max on startup.
        """
        control_entity = self.config.get("battery_discharge_control_entity", "")
        max_discharge = self.config.get("battery_max_discharge_power", 5000)

        if not control_entity:
            return

        current_state = self.hass.states.get(control_entity)
        if current_state is None:
            return

        try:
            current_limit = float(current_state.state)
        except (ValueError, TypeError):
            return

        if current_limit < max_discharge:
            await self.hass.services.async_call(
                "number", "set_value",
                {"entity_id": control_entity, "value": max_discharge},
                blocking=True,
            )
            _LOGGER.info(
                "Startup: restored battery discharge limit from %dW to %dW",
                int(current_limit), max_discharge,
            )
