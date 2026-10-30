"""#1214 — a charger service the user empties comes back after Submit.

@bekovan moved an ABB Terra to his own integration and emptied "EV Charger
Service" (``number.abb_terra_ac_…_current_limit``) on the Reconfigure page.
After Submit it was there again.

Home Assistant's frontend does not send an emptied field, and voluptuous
fills a missing ``vol.Optional`` with its ``default``. The field's default
was the saved value, so the saved value came straight back: on all five
pages that ask for the service, for the notification service ("None" is the
empty value) and for a PV string name. A saved value is a
``suggested_value``: it shows the same, and an emptied field stays empty.

The Reconfigure page had two more holes: it saved ``user_input`` as it came,
so an emptied field was never written, and it wrote ``entry.data`` only,
while the page shows ``{**data, **options}`` — an options copy won.

Bug class 30 (a key the user can set but not take back).
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solar_energy_management import config_flow as cf

from .test_990_no_charger_dialog import (
    _browser_submit,
    _entry,
    _installed_data,
    _walk,
)
from .test_ev_charger_post_install_surface import _KEBA, _flow, _submit

OLD = "number.abb_terra_ac_192_168_3_71_abb_terra_ac_current_limit"
TRIO = {"ev_connected_sensor": "binary_sensor.abb_plugged_in",
        "ev_charging_sensor": "binary_sensor.abb_charging",
        "ev_charging_power_sensor": "sensor.abb_active_power"}


def _states(hass):
    hass.states.async_set("binary_sensor.abb_plugged_in", "off")
    hass.states.async_set("binary_sensor.abb_charging", "off")
    hass.states.async_set("sensor.abb_active_power", "0",
                          {"unit_of_measurement": "W", "device_class": "power"})
    hass.states.async_set("sensor.abb_total", "1",
                          {"unit_of_measurement": "kWh", "device_class": "energy"})


async def _reconfigure(hass, entry, typed):
    entry.add_to_hass(hass)
    form = await entry.start_reconfigure_flow(hass)
    assert form["step_id"] == "reconfigure"
    with patch.object(hass.config_entries, "async_schedule_reload"):
        done = await hass.config_entries.flow.async_configure(
            form["flow_id"], user_input=_browser_submit(form, typed))
    assert done["type"] == FlowResultType.ABORT, done.get("errors")
    return {**entry.data, **entry.options}


# ── the Reconfigure page (the reported one) ───────────────────────────────

@pytest.mark.asyncio
async def test_reconfigure_empties_the_service(sem_real_hass):
    _states(sem_real_hass)
    entry = _entry(_installed_data(**TRIO, ev_charger_service=OLD))
    saved = await _reconfigure(sem_real_hass, entry, {"ev_charger_service": ""})
    assert not saved.get("ev_charger_service")


@pytest.mark.asyncio
async def test_reconfigure_empties_a_service_the_options_hold(sem_real_hass):
    """A Configure-dialog save wrote the same key into the options, which
    win the merge the page shows and SEM reads."""
    _states(sem_real_hass)
    entry = _entry(_installed_data(**TRIO, ev_charger_service=OLD),
                   {"ev_charger_service": OLD, "enable_charger_notifications": True})
    saved = await _reconfigure(sem_real_hass, entry, {"ev_charger_service": ""})
    assert not saved.get("ev_charger_service")
    assert entry.options["enable_charger_notifications"] is True


@pytest.mark.asyncio
async def test_reconfigure_keeps_what_was_not_touched(sem_real_hass):
    _states(sem_real_hass)
    entry = _entry(_installed_data(**TRIO, ev_charger_service=OLD,
                                   ev_total_energy_sensor="sensor.abb_total"),
                   {"ev_charger_service": OLD})
    saved = await _reconfigure(sem_real_hass, entry, None)
    assert saved["ev_charger_service"] == OLD
    assert saved["ev_total_energy_sensor"] == "sensor.abb_total"
    assert entry.options["ev_charger_service"] == OLD


@pytest.mark.asyncio
async def test_reconfigure_sets_a_new_service_where_the_options_hold_one(sem_real_hass):
    _states(sem_real_hass)
    entry = _entry(_installed_data(**TRIO, ev_charger_service=OLD),
                   {"ev_charger_service": OLD})
    saved = await _reconfigure(sem_real_hass, entry,
                               {"ev_charger_service": "keba.set_current"})
    assert saved["ev_charger_service"] == "keba.set_current"


@pytest.mark.asyncio
async def test_reconfigure_picks_no_notification_service(sem_real_hass):
    _states(sem_real_hass)
    entry = _entry(_installed_data(**TRIO, enable_mobile_notifications=True,
                                   mobile_notification_service="mobile_app_old"))
    saved = await _reconfigure(sem_real_hass, entry,
                               {"mobile_notification_service": ""})
    assert not saved.get("mobile_notification_service")


# ── the Configure dialog ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_configure_empties_the_first_chargers_service(sem_real_hass, _quiet):
    """The first charger's page writes the flat key and the charger's own
    copy; both must end up empty."""
    card = {"id": "ev_charger", "name": "EV Charger", **TRIO,
            "ev_charger_service": OLD,
            "ev_current_control_entity": "number.abb_current"}
    entry = _entry(_installed_data(**TRIO, ev_charger_service=OLD),
                   {"ev_chargers": [card], "ev_charger_service": OLD})
    seen, done = await _walk(sem_real_hass, entry,
                             {"ev_charger": [{"ev_charger_service": ""}]})
    assert seen[0] == "ev_charger"
    assert done["type"] == FlowResultType.CREATE_ENTRY
    saved = {**entry.data, **entry.options}
    assert not saved.get("ev_charger_service")
    assert not entry.options["ev_chargers"][0].get("ev_charger_service")
    assert entry.options["ev_chargers"][0]["ev_current_control_entity"] == "number.abb_current"


@pytest.fixture
def _quiet():
    with patch(
        "custom_components.solar_energy_management.hardware_detection."
        "discover_all_ev_chargers_from_registry", return_value=[],
    ):
        yield


@pytest.mark.asyncio
async def test_edit_empties_the_service_and_keeps_the_box_name():
    """A second charger's page. The box name stays: an Easee's start and
    stop services are sent to it too (review)."""
    flow = _flow([dict(_KEBA, ev_service_param_name="current",
                       ev_service_device_id="dev_keba")])
    flow._edit_charger_id = "ev_charger"
    # the browser drops the emptied service; the schema then runs
    await _submit(flow, "ev_charger_edit", {
        "charger_name": "KEBA P30",
        "ev_connected_sensor": "binary_sensor.keba_connected",
        "ev_charging_sensor": "binary_sensor.keba_charging",
        "ev_charging_power_sensor": "sensor.keba_power",
    })
    charger = flow._data["ev_chargers"][0]
    assert not charger.get("ev_charger_service")
    assert charger["ev_service_device_id"] == "dev_keba"


@pytest.mark.asyncio
async def test_edit_keeps_a_service_left_alone():
    flow = _flow([dict(_KEBA, ev_service_param_name="current")])
    flow._edit_charger_id = "ev_charger"
    await _submit(flow, "ev_charger_edit", {
        "charger_name": "KEBA P30",
        "ev_connected_sensor": "binary_sensor.keba_connected",
        "ev_charging_sensor": "binary_sensor.keba_charging",
        "ev_charging_power_sensor": "sensor.keba_power",
        "ev_charger_service": "keba.set_current",
    })
    charger = flow._data["ev_chargers"][0]
    assert charger["ev_charger_service"] == "keba.set_current"
    assert charger["ev_service_param_name"] == "current"


# ── the guard: no page refills a field the user can empty ────────────────

#: Selectors a user can leave empty. A select is in the list only when one
#: of its options is the empty value ("None").
_EMPTYABLE = {"TextSelector", "EntitySelector", "_power_sensor_selector"}


def _call_name(node) -> str:
    f = getattr(node, "func", None)
    return getattr(f, "attr", None) or getattr(f, "id", None) or ""


def _empty_option_lists(fn) -> set[str]:
    """Names assigned, in this function, a list whose options include the
    empty value."""
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.List):
            for el in n.value.elts:
                if isinstance(el, ast.Dict) and any(
                        isinstance(k, ast.Constant) and k.value == "value"
                        and isinstance(v, ast.Constant) and v.value == ""
                        for k, v in zip(el.keys, el.values, strict=True)):
                    out.update(t.id for t in n.targets if isinstance(t, ast.Name))
    return out


def _selector(value, empty_lists) -> str | None:
    for n in ast.walk(value):
        if not isinstance(n, ast.Call):
            continue
        name = _call_name(n)
        if name in _EMPTYABLE:
            return name
        if name == "SelectSelectorConfig":
            opts = next((k.value for k in n.keywords if k.arg == "options"), None)
            if isinstance(opts, ast.Name) and opts.id in empty_lists:
                return "SelectSelector with an empty option"
    return None


def _offenders() -> list[str]:
    tree = ast.parse(Path(inspect.getfile(cf)).read_text())
    found = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        empty_lists = _empty_option_lists(fn)
        pairs = []
        for n in ast.walk(fn):
            if isinstance(n, ast.Dict):
                pairs += [(k, v) for k, v in zip(n.keys, n.values, strict=True)
                          if k is not None]
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Subscript):
                pairs.append((n.targets[0].slice, n.value))
        for key, value in pairs:
            if isinstance(key, ast.Call) and _call_name(key) == "_charger_field":
                key = key.args[0]
            if not (isinstance(key, ast.Call) and _call_name(key) == "Optional"):
                continue
            default = next((k.value for k in key.keywords if k.arg == "default"), None)
            if default is None or (isinstance(default, ast.Constant)
                                   and default.value in ("", None)):
                continue
            kind = _selector(value, empty_lists)
            if kind:
                found.append(f"{fn.name}:{key.lineno} {ast.unparse(key.args[0])} ({kind})")
    return found


def test_the_guard_sees_the_fields():
    """Premise: the scan finds the service fields, so an empty result
    below is not a scan that read nothing."""
    tree = ast.parse(Path(inspect.getfile(cf)).read_text())
    keys = [ast.unparse(n.args[0]) for n in ast.walk(tree)
            if isinstance(n, ast.Call) and _call_name(n) == "Optional" and n.args]
    assert keys.count("'ev_charger_service'") == 5
    assert keys.count("'mobile_notification_service'") == 2


def test_the_guard_catches_a_refilled_field():
    """The scan on the old shape: a saved value as the default."""
    src = ("def f(c):\n"
           "    opts = [{'value': '', 'label': 'None'}]\n"
           "    return {vol.Optional('a', default=c.get('a', '')): "
           "selector.TextSelector(),\n"
           "            vol.Optional('b', default=c['b']): selector.SelectSelector("
           "selector.SelectSelectorConfig(options=opts)),\n"
           "            vol.Optional('n', default=c['n']): selector.NumberSelector()}\n")
    fn = ast.parse(src).body[0]
    lists = _empty_option_lists(fn)
    form = fn.body[1].value
    kinds = [_selector(value, lists) for value in form.values]
    assert kinds == ["TextSelector", "SelectSelector with an empty option", None]


def test_no_page_refills_a_field_the_user_emptied():
    assert not _offenders(), (
        "these fields carry the saved value as their default; Home Assistant "
        "does not send an emptied field, so validation puts the default back "
        "and the value cannot be erased (#1214) — use "
        "description={'suggested_value': …}"
    )


def test_a_suggested_value_leaves_an_emptied_field_missing():
    """What the fix rests on: voluptuous fills a default, never a
    suggestion."""
    shown = vol.Schema({
        vol.Optional("by_default", default="old"): str,
        vol.Optional("by_suggestion", description={"suggested_value": "old"}): str,
    })
    assert shown({}) == {"by_default": "old"}
