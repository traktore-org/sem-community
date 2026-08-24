"""#830 — when detection answers the question, stop asking it.

Step 5 measured what a new user actually faces: **4 steps, 13 fields**. Eight
of the thirteen are EV charger entity pickers, and SEM already looks all eight
up — registry discovery first, pattern matching as a fallback, then the Energy
Dashboard. They arrive pre-filled and the user is still made to walk past every
one of them.

*Every option is a decision SEM could not make for itself.* When detection
found the three REQUIRED entities, SEM made the decision, and eight pickers
collapse into one sentence: here is the charger I found, is that right?

Three properties matter more than the saving:

* **The escape must be free.** Detection is a guess, and a wrong guess that
  cannot be corrected is far worse than a form. Declining review is one
  unchecked box; asking for it shows the same form as before with everything
  pre-filled.
* **Partial detection shows the form.** Confirming two of three found entities
  while silently leaving the third blank would be worse than asking — the user
  would believe setup succeeded.
* **Nothing is skipped, only unasked.** The suggestions still become the stored
  config, so an install that confirms is identical to one that pressed Next
  through the form.
"""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solar_energy_management.config_flow import (
    SolarEnergyManagementConfigFlow,
)

DETECTED = {
    "ev_connected_sensor": "binary_sensor.keba_plug",
    "ev_charging_sensor": "binary_sensor.keba_charging",
    "ev_charging_power_sensor": "sensor.keba_power",
    "ev_total_energy_sensor": "sensor.keba_energy",
}


def _flow(hass=None):
    flow = SolarEnergyManagementConfigFlow()
    flow.hass = hass or MagicMock()
    flow._data = {}
    flow._energy_dashboard_config = None
    flow._detector = MagicMock()
    flow._detector.get_suggested_ev_defaults.return_value = {}
    flow._detector.validate_ev_configuration.return_value = {}
    return flow


def _with_discovery(found):
    return patch(
        "custom_components.solar_energy_management.config_flow."
        "discover_ev_charger_from_registry", return_value=dict(found))


class TestFullDetectionAsksOnce:
    @pytest.mark.asyncio
    async def test_it_offers_a_confirmation_instead_of_the_pickers(self):
        flow = _flow()
        with _with_discovery(DETECTED):
            result = await flow.async_step_ev_charger(user_input=None)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "ev_charger_confirm", (
            "detection answered every required question and the user was still "
            "shown the pickers")

    @pytest.mark.asyncio
    async def test_the_confirmation_names_what_was_found(self):
        """A confirmation that does not say what it found is a blind Next."""
        flow = _flow()
        with _with_discovery(DETECTED):
            result = await flow.async_step_ev_charger(user_input=None)
        blob = " ".join(str(v) for v in
                        (result.get("description_placeholders") or {}).values())
        assert "binary_sensor.keba_plug" in blob
        assert "sensor.keba_power" in blob

    @pytest.mark.asyncio
    async def test_accepting_stores_exactly_what_the_form_would_have(self):
        flow = _flow()
        with _with_discovery(DETECTED):
            await flow.async_step_ev_charger(user_input=None)
            with patch.object(flow, "async_step_hardware",
                              return_value={"type": FlowResultType.FORM,
                                            "step_id": "hardware"}) as nxt:
                result = await flow.async_step_ev_charger_confirm(
                    user_input={"review_details": False})
        assert nxt.called, "confirming did not continue to the next step"
        for key, value in DETECTED.items():
            assert flow._data.get(key) == value, (
                f"{key} was not stored — a confirmed install must be identical "
                f"to one that pressed Next through the form")
        assert result["step_id"] == "hardware"

    @pytest.mark.asyncio
    async def test_asking_to_review_shows_the_full_form(self):
        """The escape hatch. Detection is a guess; a guess the user cannot
        correct is worse than a form."""
        flow = _flow()
        with _with_discovery(DETECTED):
            await flow.async_step_ev_charger(user_input=None)
            result = await flow.async_step_ev_charger_confirm(
                user_input={"review_details": True})
        assert result["step_id"] == "ev_charger"
        keys = {str(k) for k in result["data_schema"].schema}
        assert "ev_connected_sensor" in keys
        assert "ev_charging_power_sensor" in keys


class TestPartialDetectionStillAsks:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("missing", [
        "ev_connected_sensor", "ev_charging_sensor", "ev_charging_power_sensor"])
    async def test_one_missing_required_entity_shows_the_form(self, missing):
        partial = {k: v for k, v in DETECTED.items() if k != missing}
        flow = _flow()
        with _with_discovery(partial):
            result = await flow.async_step_ev_charger(user_input=None)
        assert result["step_id"] == "ev_charger", (
            f"{missing} was never detected, and confirming would have told the "
            f"user setup succeeded with it blank")

    @pytest.mark.asyncio
    async def test_no_detection_at_all_shows_the_form(self):
        flow = _flow()
        with _with_discovery({}):
            result = await flow.async_step_ev_charger(user_input=None)
        assert result["step_id"] == "ev_charger"

    @pytest.mark.asyncio
    async def test_optional_entities_do_not_gate_the_confirmation(self):
        """Only the three REQUIRED entities decide. Waiting for the optional
        five would mean the confirmation almost never appears."""
        required_only = {k: v for k, v in DETECTED.items()
                         if k != "ev_total_energy_sensor"}
        flow = _flow()
        with _with_discovery(required_only):
            result = await flow.async_step_ev_charger(user_input=None)
        assert result["step_id"] == "ev_charger_confirm"


class TestSubmittingTheFormIsUnchanged:
    @pytest.mark.asyncio
    async def test_a_filled_form_still_proceeds(self):
        """The existing path must not move: this whole change is a shortcut in
        front of it, never a replacement."""
        flow = _flow()
        with _with_discovery({}):
            with patch.object(flow, "async_step_hardware",
                              return_value={"type": FlowResultType.FORM,
                                            "step_id": "hardware"}):
                result = await flow.async_step_ev_charger(user_input={
                    "ev_connected_sensor": "binary_sensor.x",
                    "ev_charging_sensor": "binary_sensor.y",
                    "ev_charging_power_sensor": "sensor.z",
                })
        assert result["step_id"] == "hardware"
        assert flow._data["ev_connected_sensor"] == "binary_sensor.x"
