"""#831 — the "or the user can just copy them in" half.

The three SEM-fault repairs are ``is_fixable=True`` and their fix flow is a
single confirm step whose description carries the same context the prefilled
bug-report URL does — versions, repair key, reason — as selectable text. It
works for users without a GitHub account, and it sends NOTHING anywhere:
confirming just dismisses the notice, exactly like a non-fixable repair's
ignore. The context travels through the issue's ``data`` dict, placed there
by the raiser.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from .const import DOMAIN
from .coordinator.battery_controls import rename_battery_unit
from .coordinator.battery_sensor_check import apply_replacements, candidates

# The three report-side keys (#831's split). Everything else keeps the plain
# ignore flow HA gives non-fixable issues.
_COPYABLE = (
    "charger_actuation_failed",
    "charger_stop_unenforceable",
    "soc_cap_unenforceable",
)


class SEMContextCopyFlow(RepairsFlow):
    """One step: show the context, confirm to dismiss."""

    def __init__(self, data: dict | None) -> None:
        self._data = dict(data or {})

    async def async_step_init(self, user_input=None) -> data_entry_flow.FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None) -> data_entry_flow.FlowResult:
        if user_input is not None:
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                # The step renders the issue's diagnosis followed by the
                # copyable context, so it needs the issue's own placeholders
                # too — Hassfest rejects an issue that declares both a
                # `description` and a `fix_flow`, so the text lives here now.
                # Missing keys render as empty rather than raising: a repair
                # that cannot be displayed is worse than one missing a word.
                **{k: ("" if v is None else str(v))
                   for k, v in (self._data.get("placeholders") or {}).items()},
                "context": self._data.get("copy_context", ""),
            },
        )


class SEMBatteryFixFlow(RepairsFlow):
    """(#1256) Pick a replacement for each battery entity that is gone.

    One step per entity SEM can re-point, with only entities of the right
    role to choose from. Leaving a step empty keeps that entity as it is.
    The pick is written to SEM's options, and the battery's saved settings
    follow its power sensor to the new one.
    """

    def __init__(self, data: dict | None) -> None:
        data = dict(data or {})
        self._rows = [r for r in data.get("rows") or [] if r.get("editable")]
        self._missing = str((data.get("placeholders") or {}).get("missing", ""))
        self._chosen: dict[str, str] = {}
        self._at = 0

    async def async_step_init(self, user_input=None) -> data_entry_flow.FlowResult:
        return await self.async_step_pick()

    async def async_step_pick(self, user_input=None) -> data_entry_flow.FlowResult:
        if user_input is not None:
            new = str(user_input.get("replacement") or "").strip()
            if new:
                self._chosen[self._rows[self._at]["entity"]] = new
            self._at += 1
        if self._at >= len(self._rows):
            return self._finish()
        row = self._rows[self._at]
        taken = [e for e in self._chosen.values()]
        fits = candidates(self.hass, row, taken=taken)
        domain = str(row["entity"]).split(".", 1)[0] if row["entity"] else "sensor"
        config = (selector.EntitySelectorConfig(include_entities=fits) if fits
                  else selector.EntitySelectorConfig(domain=domain))
        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema({
                vol.Optional("replacement"): selector.EntitySelector(config)}),
            description_placeholders={
                "old": str(row["entity"] or row.get("label") or ""),
                "missing": self._missing,
                "position": f"{self._at + 1}/{len(self._rows)}",
            },
        )

    def _finish(self) -> data_entry_flow.FlowResult:
        entries = self.hass.config_entries.async_entries(DOMAIN)
        if not self._chosen or not entries:
            return self.async_abort(reason="nothing_chosen")
        entry = entries[0]
        merged = {**dict(entry.data), **dict(entry.options)}
        changes = apply_replacements(merged, self._chosen, self._rows)
        for row in self._rows:
            new = self._chosen.get(row["entity"])
            if new and row.get("role") == "power":
                changes.update(rename_battery_unit(merged, row["entity"], new))
        self.hass.config_entries.async_update_entry(
            entry, options={**dict(entry.options), **changes})
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict | None,
) -> RepairsFlow:
    """HA's entry point — every SEM fixable issue routes here."""
    if issue_id.startswith("power_sensor_not_found_"):
        return SEMBatteryFixFlow(data)
    return SEMContextCopyFlow(data)
