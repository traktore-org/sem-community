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

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

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


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict | None,
) -> RepairsFlow:
    """HA's entry point — every SEM fixable issue routes here."""
    return SEMContextCopyFlow(data)
