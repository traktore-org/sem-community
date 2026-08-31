"""#883 — opening the SEM options flow must not overwrite the primary
charger's per-charger tunables with a stale flat mirror.

Live report (ab-elco-clal, 2.1.0-beta.1, two chargers): merely opening
*Settings → Devices & services → Integrations → SEM* and browsing past the
EV-charger page reset Charger 1 (Carport)'s "Minimum" charge target from
50% to 100% ("Up to Full"), while Charger 2 (Indkorsel) was untouched.

Class 19 (dual storage aligned only by coincidence of defaults): the EV
card's Min/Max sliders persist PER-CHARGER via ``persist_per_charger_option``
(``ev_chargers[0][key]``) and never touch the flat ``ev_target_soc`` mirror,
so the two diverge the moment a user drags a slider. The primary
``async_step_ev_charger`` options step both READS its form defaults from the
flat mirror (``current_config``) and, on submit, WRITES them back into
``ev_chargers[0]`` — so the stale flat value silently overwrote the slider
value. Only charger 0 was hit because chargers 2+ are edited by
``async_step_ev_charger_edit``, which reads the charger dict directly.
"""
import pytest
from unittest.mock import MagicMock, patch

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry

from custom_components.solar_energy_management.config_flow import (
    OptionsFlowHandler,
)


def _schema_default(schema, key):
    """Return the default a shown form offers for ``key`` (None if unset)."""
    for marker in schema.schema:
        if str(marker) == key:
            d = getattr(marker, "default", vol.UNDEFINED)
            if d is vol.UNDEFINED:
                return None
            return d() if callable(d) else d
    return "MISSING"


def _all_defaults(schema):
    """Every field the form would submit unchanged (the 'just browse' POST)."""
    out = {}
    for marker in schema.schema:
        d = getattr(marker, "default", vol.UNDEFINED)
        if d is not vol.UNDEFINED:
            out[str(marker)] = d() if callable(d) else d
    return out


def _entry():
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "e883"
    entry.data = {}
    # Flat mirror is STALE — left at the install/legacy default while the user
    # dragged every per-charger slider down. The dashboard writes per-charger
    # only, so the flat copy never followed.
    entry.options = {
        "ev_target_soc": 100,
        "ev_target_soc_max": 100,
        "daily_ev_target_max": 100,
        "ev_kwh_per_100km": 18,
        "ev_battery_capacity_kwh": 40,
        "ev_chargers": [
            {
                "id": "ev_charger", "name": "Carport",
                "ev_connected_sensor": "binary_sensor.carport_connected",
                "ev_charging_sensor": "binary_sensor.carport_charging",
                "ev_charging_power_sensor": "sensor.carport_power",
                # the user's real, per-charger choices
                "ev_target_soc": 50,
                "ev_target_soc_max": 80,
                "daily_ev_target_max": 60,
                "ev_kwh_per_100km": 22,
                "ev_battery_capacity_kwh": 77,
            },
            {
                "id": "charger2", "name": "Indkorsel",
                "ev_connected_sensor": "binary_sensor.drive_connected",
                "ev_charging_sensor": "binary_sensor.drive_charging",
                "ev_charging_power_sensor": "sensor.drive_power",
                "ev_target_soc": 50,
            },
        ],
    }
    return entry


# The per-charger fields the primary EV-charger options form offers, and the
# authoritative value each carries in ev_chargers[0] above.
_PER_CHARGER_FIELDS = {
    "ev_target_soc": 50,
    "ev_target_soc_max": 80,
    "daily_ev_target_max": 60,
    "ev_kwh_per_100km": 22,
    "ev_battery_capacity_kwh": 77,
}


async def _show_form(entry, mock_hass):
    flow = OptionsFlowHandler(entry)
    flow.hass = mock_hass
    with patch.object(
        type(flow), "config_entry",
        new_callable=lambda: property(lambda self: entry),
    ):
        result = await flow.async_step_ev_charger()
    return flow, result


@pytest.mark.asyncio
async def test_form_defaults_come_from_the_charger_not_the_flat_mirror(mock_hass):
    """The Min charge target (and its siblings) must default to the stored
    per-charger value, not the stale flat mirror."""
    _, result = await _show_form(_entry(), mock_hass)
    schema = result["data_schema"]
    for key, want in _PER_CHARGER_FIELDS.items():
        got = _schema_default(schema, key)
        assert got == want, (
            f"{key}: form defaulted to {got} (the flat mirror) instead of the "
            f"per-charger {want} — browsing past the page would overwrite it")


@pytest.mark.asyncio
async def test_browsing_past_the_page_preserves_charger0_and_charger2(mock_hass):
    """The reported action end-to-end: open options, submit the EV page
    unchanged. Charger 0's slider values survive; charger 2 is never touched."""
    import copy
    entry = _entry()
    # Snapshot charger 2 BEFORE the submit (the flow mutates the list in place,
    # so we need an independent copy to prove charger 2 was never touched).
    charger2_before = copy.deepcopy(entry.options["ev_chargers"][1])
    flow, result = await _show_form(entry, mock_hass)
    # cur_step drives _merge_form_input's cleared-field detection; set it to
    # the form just shown so the submit behaves like the real framework.
    flow.cur_step = result
    submit = _all_defaults(result["data_schema"])
    with patch.object(
        type(flow), "config_entry",
        new_callable=lambda: property(lambda self: entry),
    ):
        await flow.async_step_ev_charger(submit)

    chargers = {c["id"]: c for c in flow._data["ev_chargers"]}
    for key, want in _PER_CHARGER_FIELDS.items():
        assert chargers["ev_charger"][key] == want, (
            f"charger 0 {key} was overwritten to "
            f"{chargers['ev_charger'][key]} (wanted {want})")
    # Charger 2 must be byte-for-byte what it was before the submit.
    assert chargers["charger2"] == charger2_before
