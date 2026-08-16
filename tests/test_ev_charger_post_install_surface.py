"""Two holes in the post-install charger surface — #627's other half.

**Bug class 30** — *backend-honoured config key with no editable surface.*
#627 gave every per-charger entity key a form field. A field you can type
into is not yet a surface you can *correct*: both remaining holes are about
what the form does with the value you did NOT type.

1. **Add** pre-fills the new charger from a discovery that is already
   registered. The dedup key is ``_device_id``, which ``async_step_ev_charger_add``
   never writes onto the charger it stores — so ``existing_ids`` is always
   empty, every discovery always looks new, and the suggestion offered for
   charger #2 is charger #1's own config: its entities and, worst,
   ``ev_charger_service``. Accept the defaults and SEM drives the first box
   twice while the second one never moves.

2. **Edit** cannot clear an optional entity. HA omits a cleared optional
   field from ``user_input`` entirely, and ``charger.update(user_input)``
   leaves the old value standing. So a wrong ``ev_start_stop_entity`` guess
   — the exact #627 symptom — can be pointed at a different entity but never
   removed. "Editable" has to include "erasable" or the auto-detect is still
   the last word.

Hole 2 is not a charger bug. Every step that merges a submitted form with
``.update(user_input)`` has it, and the flow has **41 fields across 8 steps**
that a user can empty and SEM will keep: the twelve ``phase_guard_*`` current
/power/voltage entities, the tariff entities, the heat-pump relays, the
battery discharge control entity. Mis-pick any of them at setup and the only
recorded way out is deleting the integration. So the fix is one merge helper
used by every step, plus a guard that no step goes back to a bare ``update``.

Both are the same shape as #627 itself: the runtime honours a key the user
cannot actually take back.
"""
import ast
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.solar_energy_management import config_flow as cf
from custom_components.solar_energy_management.config_flow import (
    OptionsFlowHandler,
)

_DISCOVERY_PATH = (
    "custom_components.solar_energy_management.hardware_detection"
    ".discover_all_ev_chargers_from_registry"
)

# The already-installed KEBA, as it actually sits in ``ev_chargers`` after a
# v2→v3 migration: no ``_device_id`` anywhere, because nothing ever stores it.
_KEBA = {
    "id": "ev_charger",
    "name": "KEBA P30",
    "ev_connected_sensor": "binary_sensor.keba_connected",
    "ev_charging_sensor": "binary_sensor.keba_charging",
    "ev_charging_power_sensor": "sensor.keba_power",
    "ev_charger_service": "keba.set_current",
    "ev_start_stop_entity": "switch.keba_wrong_guess",
    "ev_current_control_entity": "number.keba_current",
}

# What ``discover_all_ev_chargers_from_registry`` reports on the next run:
# the same physical box, since it is still in the entity registry.
_KEBA_DISCOVERED = {
    "name": "KEBA P30",
    "_device_id": "dev_keba",
    "ev_connected_sensor": "binary_sensor.keba_connected",
    "ev_charging_sensor": "binary_sensor.keba_charging",
    "ev_charging_power_sensor": "sensor.keba_power",
    "ev_charger_service": "keba.set_current",
    "ev_start_stop_entity": "switch.keba_wrong_guess",
}


def _flow(chargers):
    """An OptionsFlowHandler with just enough machinery to show a form."""
    flow = OptionsFlowHandler.__new__(OptionsFlowHandler)
    flow.hass = MagicMock()
    flow.flow_id = "test-flow"
    flow.handler = "solar_energy_management"
    flow.context = {}
    flow.cur_step = None
    flow._data = {"ev_chargers": [dict(c) for c in chargers]}
    return flow


async def _submit(flow, step, raw: dict):
    """Drive a step the way the framework does: show, validate, submit.

    Two details matter and neither survives calling the handler directly.
    HA stores the form it just showed on ``flow.cur_step`` — that is the
    only record of *which fields this page offered* — and it runs the raw
    input through that schema before dispatching, which fills every
    ``vol.Optional`` that carries a ``default``. What is left MISSING after
    that is exactly what the user cleared.
    """
    form = await getattr(flow, f"async_step_{step}")()
    flow.cur_step = form
    return await getattr(flow, f"async_step_{step}")(form["data_schema"](raw))


def _prefills(schema: vol.Schema) -> dict:
    """What the form hands the user before they touch anything."""
    out = {}
    for marker in schema.schema:
        key = str(marker.schema)
        default = getattr(marker, "default", vol.UNDEFINED)
        if default is not vol.UNDEFINED:
            out[key] = default()
        desc = getattr(marker, "description", None)
        if isinstance(desc, dict) and desc.get("suggested_value") is not None:
            out[key] = desc["suggested_value"]
    return out


@pytest.mark.unit
class TestAddDoesNotCloneAnInstalledCharger:
    """A second charger must not be born as a copy of the first."""

    @pytest.mark.asyncio
    async def test_a_registered_charger_is_not_offered_again(self):
        """The reported shape: the only discovery IS the installed box, so
        there is nothing new to suggest and the form must come up blank."""
        flow = _flow([_KEBA])
        with patch(_DISCOVERY_PATH, return_value=[dict(_KEBA_DISCOVERED)]):
            result = await flow.async_step_ev_charger_add()

        pre = _prefills(result["data_schema"])
        assert not pre.get("ev_charger_service"), (
            "charger #2 was pre-filled with charger #1's control method "
            f"({pre.get('ev_charger_service')!r}) — accepting the defaults "
            "drives the first box twice"
        )
        for key in ("ev_connected_sensor", "ev_charging_sensor",
                    "ev_charging_power_sensor", "ev_start_stop_entity"):
            assert not pre.get(key), f"{key} was inherited from charger #1"

    @pytest.mark.asyncio
    async def test_a_genuinely_new_charger_is_still_suggested(self):
        """The dedup must not swallow the feature it guards: a second,
        different box still pre-fills, which is the whole point of
        auto-discovery on the add step."""
        wallbox = {
            "name": "Wallbox Pulsar",
            "_device_id": "dev_wallbox",
            "ev_connected_sensor": "binary_sensor.wallbox_connected",
            "ev_charging_sensor": "binary_sensor.wallbox_charging",
            "ev_charging_power_sensor": "sensor.wallbox_power",
            "ev_current_control_entity": "number.wallbox_current",
        }
        flow = _flow([_KEBA])
        with patch(_DISCOVERY_PATH,
                   return_value=[dict(_KEBA_DISCOVERED), dict(wallbox)]):
            result = await flow.async_step_ev_charger_add()

        pre = _prefills(result["data_schema"])
        assert pre.get("ev_connected_sensor") == "binary_sensor.wallbox_connected"
        assert pre.get("ev_current_control_entity") == "number.wallbox_current"

    def test_the_fingerprint_covers_every_entity_discovery_reports(self):
        """The ratchet under the dedup.

        The comparison is only as good as the key set it compares. A brand
        that starts reporting a new entity — a new ``result["ev_…"] = eid``
        in ``hardware_detection`` — must be classified deliberately, or it
        silently stops counting towards "same box" and the clone comes
        back for exactly the chargers that key belongs to.

        Values assigned from a literal (``ev_charger_service``,
        ``ev_charge_mode_start``) are not entities and are correctly absent:
        two KEBAs share ``keba.set_current``, so a service names a protocol,
        not a box.
        """
        from custom_components.solar_energy_management import hardware_detection

        src = Path(inspect.getfile(hardware_detection)).read_text()
        reported = set()
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Assign):
                continue
            if not (isinstance(node.value, ast.Name)
                    and node.value.id in ("eid", "target")):
                continue
            for tgt in node.targets:
                if (isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "result"
                        and isinstance(tgt.slice, ast.Constant)):
                    reported.add(tgt.slice.value)

        assert reported, "the scan found no entity assignments — it has rotted"
        assert reported <= set(cf._CHARGER_ENTITY_KEYS), (
            "discovery reports entities the charger fingerprint does not "
            f"know about: {sorted(reported - set(cf._CHARGER_ENTITY_KEYS))}"
        )

    @pytest.mark.asyncio
    async def test_the_first_charger_on_a_bare_entry_still_suggests(self):
        """Nothing registered yet — every discovery is new."""
        flow = _flow([])
        with patch(_DISCOVERY_PATH, return_value=[dict(_KEBA_DISCOVERED)]):
            result = await flow.async_step_ev_charger_add()

        assert _prefills(result["data_schema"]).get("ev_charger_service") == (
            "keba.set_current"
        )


@pytest.mark.unit
class TestEditCanTakeAValueBack:
    """An auto-detect the user cannot erase is an auto-detect that wins."""

    @pytest.mark.asyncio
    async def test_clearing_an_optional_entity_clears_it(self):
        """#627's symptom, one turn later: the wrong ``ev_start_stop_entity``
        can now be typed over — but the box may simply not HAVE a start/stop
        entity, and the only correct answer is "none"."""
        flow = _flow([_KEBA])
        flow._edit_charger_id = "ev_charger"
        # Every optional entity left empty — HA drops them from user_input.
        await _submit(flow, "ev_charger_edit", {
            "charger_name": "KEBA P30",
            "ev_connected_sensor": "binary_sensor.keba_connected",
            "ev_charging_sensor": "binary_sensor.keba_charging",
            "ev_charging_power_sensor": "sensor.keba_power",
            "ev_charger_service": "keba.set_current",
        })

        charger = flow._data["ev_chargers"][0]
        assert not charger.get("ev_start_stop_entity"), (
            "the wrong auto-detected start/stop entity survived being "
            "cleared — the user cannot correct a bad guess to 'none'"
        )
        assert not charger.get("ev_current_control_entity")

    @pytest.mark.asyncio
    async def test_an_untouched_optional_entity_survives(self):
        """Clearing means clearing; submitting the same value means keeping
        it. Erasing on every save would be the opposite bug."""
        flow = _flow([_KEBA])
        flow._edit_charger_id = "ev_charger"
        await _submit(flow, "ev_charger_edit", {
            "charger_name": "KEBA P30",
            "ev_connected_sensor": "binary_sensor.keba_connected",
            "ev_charging_sensor": "binary_sensor.keba_charging",
            "ev_charging_power_sensor": "sensor.keba_power",
            "ev_charger_service": "keba.set_current",
            "ev_start_stop_entity": "switch.keba_enable",
            "ev_current_control_entity": "number.keba_current",
        })

        charger = flow._data["ev_chargers"][0]
        assert charger["ev_start_stop_entity"] == "switch.keba_enable"
        assert charger["ev_current_control_entity"] == "number.keba_current"

    @pytest.mark.asyncio
    async def test_clearing_does_not_touch_the_charger_identity(self):
        """Only fields the form actually offers are clearable — id, name and
        anything the step never showed must survive untouched."""
        charger_in = dict(_KEBA, ev_charge_mode_entity="select.keba_mode",
                          _internal_marker="keep me")
        flow = _flow([charger_in])
        flow._edit_charger_id = "ev_charger"
        await _submit(flow, "ev_charger_edit", {
            "charger_name": "Renamed",
            "ev_connected_sensor": "binary_sensor.keba_connected",
            "ev_charging_sensor": "binary_sensor.keba_charging",
            "ev_charging_power_sensor": "sensor.keba_power",
        })

        charger = flow._data["ev_chargers"][0]
        assert charger["id"] == "ev_charger"
        assert charger["name"] == "Renamed"
        assert charger["_internal_marker"] == "keep me"
        assert not charger.get("ev_charge_mode_entity")


@pytest.mark.unit
class TestClearingIsTheWholeClass:
    """41 fields across 8 steps, not two charger fields."""

    def test_the_merge_records_a_cleared_field_as_empty(self):
        """Not ``pop`` — ``None``.

        The runtime config is ``{**entry.data, **entry.options}`` and the
        options flow REPLACES options wholesale (#690). Deleting the key
        from the options therefore un-covers whatever the initial setup
        wrote into ``entry.data`` and the "cleared" value comes straight
        back. An explicit ``None`` is what actually overrides it — and it
        is already the house spelling of "not set" (the v8→v9 migration
        seeds ``vehicle_min_current: None``).
        """
        schema = vol.Schema({
            vol.Optional("clearable", description={"suggested_value": "x"}): str,
            vol.Optional("has_a_default", default=5): int,
            vol.Required("required"): str,
        })
        flow = _flow([])
        flow.cur_step = {"data_schema": schema}
        target = {"clearable": "switch.old", "untouched": "keep"}

        cf._merge_form_input(flow, target, {"required": "r", "has_a_default": 5})

        assert target["clearable"] is None
        assert target["untouched"] == "keep"
        assert target["required"] == "r"

    def test_a_field_the_page_never_showed_is_not_cleared(self):
        """The shown schema is the authority on what the user could empty.
        Anything else the target carries is somebody else's key."""
        flow = _flow([])
        flow.cur_step = {"data_schema": vol.Schema(
            {vol.Optional("mine", description={"suggested_value": None}): str}
        )}
        target = {"mine": "a", "theirs": "b"}

        cf._merge_form_input(flow, target, {})

        assert target["mine"] is None
        assert target["theirs"] == "b"

    def test_no_step_merges_a_form_by_hand(self):
        """The ratchet. A bare ``update(user_input)`` is the bug — it cannot
        see which fields the page offered, so it cannot tell "unchanged"
        from "emptied". Adding one back must fail here, not in a report a
        year later about a heat-pump relay that will not let go."""
        src = Path(inspect.getfile(cf)).read_text()
        offenders = []
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("async_step_"):
                continue
            for call in ast.walk(node):
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "update"
                        and any(isinstance(a, ast.Name) and a.id == "user_input"
                                for a in call.args)):
                    offenders.append(f"{node.name}:{call.lineno}")

        assert not offenders, (
            "these steps merge the submitted form by hand and so cannot "
            f"clear a field: {offenders} — use _merge_form_input(self, …)"
        )
