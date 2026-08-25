"""Single-instance config flow for the simulator."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow

from .const import DEFAULT_PREFIX, DOMAIN


class ZaptecSimConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Zaptec (simulated)", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Optional("device_prefix", default=DEFAULT_PREFIX): str,
                # (#804) The open question on the reporter's install: he named
                # only INSTALLATION-level numbers. If his integration build
                # exposes no charger-level current, SEM has no legitimate
                # throttle at all — and must say so rather than reach for the
                # installation's grid guard. Turn this off to simulate that.
                vol.Optional("expose_charger_current", default=True): bool,
            }),
        )
