"""#1376 — a saved ``zaptec.limit_current`` with no field name kept the
charger's own current number unused.

A Zaptec Go 2 was saved with ``ev_charger_service: zaptec.limit_current``
aimed at a car sensor, beside the Go's own number (``charger_max_current``).
When a service is set, SEM writes only through it. ``limit_current`` sets
the current of the whole site (#804), and #1144 takes it out of a save — but
only by the saved field name (``available_current``). This save had none, so
SEM wrote ``{"current": N}`` to the site's service, which refused it, and
the charger never got a current.

The rule now: a service is the site's by its OWN fields too (R6), read live.
The refs step and the builder ask when Home Assistant can tell; a device
built while it cannot (the service's fields come from its services.yaml,
which is read after start) asks again before each write.
"""
from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management import charger_refs as cr
from custom_components.solar_energy_management import hardware_detection as hd

from .integrations_rig.rig import load_capture, replay
from .test_1144_saved_site_limit import (
    _CORE,
    OWN_CURRENT,
    POWER,
    RESUME,
    _entry,
    _seed_core,
    _set_up,
    _unload,
    _values,
)

CAR_SENSOR = "sensor.e_niro_target_range_of_charge_ac"
#: The reporter's card (discussion #1374), on the rig's Zaptec capture: the
#: site's service with no field name, aimed at a car sensor, beside the
#: Go's own current number.
CARD = {
    "id": "zaptec_go", "name": "Zaptec Charger",
    "ev_charging_power_sensor": POWER,
    "ev_charger_service": "zaptec.limit_current",
    "ev_charger_service_entity_id": CAR_SENSOR,
    "ev_current_control_entity": OWN_CURRENT,
    "ev_start_stop_entity": RESUME,
    "ev_min_current": 6, "ev_max_current": 16,
}
SERVICE_KEYS = ("ev_charger_service", "ev_charger_service_entity_id")
#: Zaptec's ``limit_current`` fields, as the capture holds them
ZAPTEC_LIMIT_FIELDS = load_capture("zaptec")["services"]["limit_current"]


def _capture_fields(service):
    domain, name = service.split(".", 1)
    cap = load_capture("zaptec")
    return cap["services"].get(name) if domain == cap["domain"] else None


# ── premise: the bug ─────────────────────────────────────────────────────

def test_premise_the_saved_field_alone_does_not_see_it():
    """#1144's check reads the saved field name; this save has none."""
    assert hd.site_limit_controls(CARD) == ()


def test_the_services_own_fields_say_it():
    assert set(hd.site_limit_controls(CARD, fields_of=_capture_fields)) == set(
        SERVICE_KEYS)


# ── what a site service is ───────────────────────────────────────────────

@pytest.mark.parametrize("service,fields,site", [
    ("zaptec.limit_current", ZAPTEC_LIMIT_FIELDS, True),
    ("zaptec.limit_current", ["available_current_phase1", "device_id"], True),
    # a charger's own current service
    ("easee.set_charger_dynamic_limit", ["current", "device_id"], False),
    ("keba.set_current", ["current"], False),
    ("zaptec.resume_charging", ["charger_id", "device_id"], False),
    # a service that ALSO takes a charger's own current is not only the site's
    ("x.set_limits", ["available_current", "current"], False),
    # an entity platform's service is judged by its target, not its fields
    ("number.set_value", ["available_current", "entity_id"], False),
    # nothing known says nothing
    ("zaptec.limit_current", None, False),
    ("zaptec.limit_current", [], False),
])
def test_what_sets_a_site_limit(service, fields, site):
    assert hd.service_sets_a_site_limit(service, fields) is site


def test_a_saved_per_phase_field_is_the_sites_too():
    """The saved field may name one phase of the site's current."""
    card = {"ev_charger_service": "zaptec.limit_current",
            "ev_service_param_name": "available_current_phase2"}
    assert set(hd.site_limit_controls(card)) == {
        "ev_charger_service", "ev_service_param_name"}


def test_a_charger_service_stays_whatever_its_fields():
    for card, fields in (
            ({"ev_charger_service": "easee.set_charger_dynamic_limit",
              "ev_service_param_name": "current"}, ["current", "device_id"]),
            ({"ev_charger_service": "keba.set_current",
              "ev_charger_service_entity_id": "binary_sensor.keba_plug"},
             ["current"])):
        assert hd.site_limit_controls(
            card, fields_of=lambda s, f=fields: f) == ()


def test_the_real_saved_option_sets_are_untouched():
    """PROD's and HA-TEST's real charger lists, every service read as a
    charger's own (or not readable)."""
    fixtures = Path(__file__).resolve().parent / "fixtures"
    for name in ("hw_996_prod_options.json", "hw_996_hatest_options.json"):
        opts = json.loads((fixtures / name).read_text())
        for c in opts["ev_chargers"]:
            for fields_of in (lambda s: None, lambda s: ["current", "device_id"]):
                assert hd.site_limit_controls(
                    c, MagicMock(return_value=None), fields_of) == (), c


# ── the live read ────────────────────────────────────────────────────────

async def test_service_fields_reads_a_registered_service(hass):
    await replay(hass, load_capture("zaptec"))
    assert hd.service_fields(hass, "zaptec.limit_current") == sorted(
        ZAPTEC_LIMIT_FIELDS)
    # not registered, or no field known: unknown, never "no"
    assert hd.service_fields(hass, "zaptec.no_such_service") is None
    assert hd.service_fields(hass, "nothing") is None
    assert hd.service_fields(None, "zaptec.limit_current") is None


async def test_service_fields_does_not_wait_for_start(hass):
    """At boot SEM is set up before Home Assistant runs; a registered
    service can be read then (``_services_of`` says unknown)."""
    await replay(hass, load_capture("zaptec"))
    from homeassistant.core import CoreState
    hass.set_state(CoreState.not_running)
    try:
        assert hd._services_of(hass) is None, "premise"
        assert hd.service_fields(hass, "zaptec.limit_current")
    finally:
        hass.set_state(CoreState.running)


# ── the refs step: the save loses it ─────────────────────────────────────

async def test_the_reporters_save_loses_the_site_service(hass, caplog):
    await replay(hass, load_capture("zaptec"))
    entry = _entry(hass, {cr.LEGACY_KEY: [dict(CARD)]})
    with caplog.at_level(logging.INFO):
        (card,) = cr.async_reconcile(hass, entry)
    for k in SERVICE_KEYS:
        assert k not in card, k
    assert card["ev_current_control_entity"] == OWN_CURRENT
    assert card["ev_start_stop_entity"] == RESUME
    assert "limit_current" not in _values(entry.options)
    assert CAR_SENSOR not in _values(entry.options)


async def test_the_refs_step_keeps_it_while_the_fields_are_unknown(hass):
    """Unknown is not "the site's": nothing is taken out on a guess."""
    await replay(hass, load_capture("zaptec"))
    entry = _entry(hass, {cr.LEGACY_KEY: [dict(CARD)]})
    with patch.object(hd, "service_fields", return_value=None):
        (card,) = cr.async_reconcile(hass, entry)
    assert card["ev_charger_service"] == "zaptec.limit_current"


# ── the builder and the write ────────────────────────────────────────────

def _recorder(sent):
    async def _record(domain, service, data=None, *, why=""):
        sent.append((domain, service, dict(data or {})))
        return True
    return _record


@pytest.mark.asyncio
async def test_the_builder_drops_it_and_writes_the_chargers_number(
        sem_real_hass, caplog):
    """The refs step down: the builder asks the service itself, and a
    write goes to the Go's own number."""
    hass = sem_real_hass
    _seed_core(hass)
    await replay(hass, load_capture("zaptec"))
    entry = _entry(hass, {cr.LEGACY_KEY: [dict(CARD)]}, data=dict(_CORE))
    with patch.object(cr, "async_reconcile",
                      side_effect=RuntimeError("refs down")), \
            caplog.at_level(logging.WARNING):
        devs = await _set_up(hass, entry)
    try:
        dev = devs["zaptec_go"]
        assert not dev.charger_service
        assert not dev.charger_service_entity_id
        assert dev.current_entity_id == OWN_CURRENT
        assert "#1376" in caplog.text
        sent = []
        with patch.object(dev, "send", side_effect=_recorder(sent)):
            await dev._set_current(10)
        assert ("number", "set_value",
                {"entity_id": OWN_CURRENT, "value": 10}) in sent, sent
        assert not [c for c in sent if c[0] == "zaptec"], sent
    finally:
        await _unload(hass, entry)


def _bare_zaptec():
    """The Zaptec services registered with no readable schema: their fields
    come only from Home Assistant's description cache (services.yaml)."""
    cap = json.loads(json.dumps(load_capture("zaptec")))
    cap["services_without_schema"] = True
    return cap


def _forget_descriptions(hass):
    from homeassistant.helpers.service import SERVICE_DESCRIPTION_CACHE
    cache = hass.data.get(SERVICE_DESCRIPTION_CACHE, {})
    kept = {k: cache.pop(k) for k in list(cache) if k[0] == "zaptec"}
    return kept


@pytest.mark.asyncio
async def test_a_device_built_at_boot_drops_it_before_its_first_write(
        sem_real_hass, caplog):
    """At boot the service's fields cannot be read yet (services.yaml is
    loaded after start). The device asks again before it writes; once Home
    Assistant can tell, the site's service is gone for good and the Go's
    own number takes the current."""
    hass = sem_real_hass
    _seed_core(hass)
    await replay(hass, _bare_zaptec())
    kept = _forget_descriptions(hass)
    assert hd.service_fields(hass, "zaptec.limit_current") is None, "premise"
    entry = _entry(hass, {cr.LEGACY_KEY: [dict(CARD)]}, data=dict(_CORE))
    devs = await _set_up(hass, entry)
    try:
        dev = devs["zaptec_go"]
        assert dev.charger_service == "zaptec.limit_current", (
            "premise: unknown at build, the service is kept")
        from homeassistant.helpers.service import SERVICE_DESCRIPTION_CACHE
        hass.data.setdefault(SERVICE_DESCRIPTION_CACHE, {}).update(kept)
        sent = []
        with patch.object(dev, "send", side_effect=_recorder(sent)), \
                caplog.at_level(logging.WARNING):
            await dev._set_current(10)
            await dev._set_current(12)
        assert not dev.charger_service
        assert [c for c in sent if c[0] == "number"] == [
            ("number", "set_value", {"entity_id": OWN_CURRENT, "value": 10}),
            ("number", "set_value", {"entity_id": OWN_CURRENT, "value": 12})]
        assert not [c for c in sent if c[0] == "zaptec"], sent
        assert caplog.text.count("#1376") == 1, "said once"
    finally:
        await _unload(hass, entry)


async def test_the_device_check_settles_once(hass):
    """Asked until Home Assistant can tell, then never again; a charger's
    own service is kept."""
    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
    )
    await replay(hass, _bare_zaptec())
    kept = _forget_descriptions(hass)
    hass.services.async_register(
        "zaptec", "own_current", lambda call: None)
    from homeassistant.helpers.service import SERVICE_DESCRIPTION_CACHE
    hass.data[SERVICE_DESCRIPTION_CACHE][("zaptec", "own_current")] = {
        "fields": {"current": {}, "device_id": {}}}
    own = CurrentControlDevice(hass=hass, device_id="a", name="a",
                               charger_service="zaptec.own_current")
    own._settle_charger_service()
    assert own.charger_service == "zaptec.own_current"
    assert own._charger_service_settled
    site = CurrentControlDevice(hass=hass, device_id="b", name="b",
                                charger_service="zaptec.limit_current",
                                current_entity_id=OWN_CURRENT)
    with patch.object(hd, "service_fields", wraps=hd.service_fields) as asked:
        site._settle_charger_service()
        site._settle_charger_service()
        assert asked.call_count == 2, "unknown: asked again"
        assert site.charger_service == "zaptec.limit_current"
        hass.data[SERVICE_DESCRIPTION_CACHE].update(kept)
        site._settle_charger_service()
        site._settle_charger_service()
        assert asked.call_count == 3, "known: never asked again"
    assert site.charger_service is None
    assert site.current_entity_id == OWN_CURRENT


def test_the_producer_on_a_device_with_nothing_to_ask():
    dev = SimpleNamespace(charger_service=None)
    assert hd.refuse_site_limit_service(None, dev, "x") is False
    dev = SimpleNamespace(charger_service="number.set_value")
    assert hd.refuse_site_limit_service(None, dev, "x") is False
    dev = SimpleNamespace(charger_service="zaptec.limit_current")
    assert hd.refuse_site_limit_service(None, dev, "x") is None
    assert dev.charger_service == "zaptec.limit_current"


# ── a charger whose only control was the site's ─────────────────────────

async def test_nothing_left_to_act_is_a_failed_write_not_a_set_one(hass):
    """Dropped after the build with no number and no start/stop: the write
    fails (the Repair at three), it is never claimed as set. With a way to
    start and stop it is a start/stop charger, as the builder makes it."""
    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
    )
    await replay(hass, load_capture("zaptec"))
    bare = CurrentControlDevice(hass=hass, device_id="z", name="z",
                                charger_service="zaptec.limit_current")
    sent = []
    with patch.object(bare, "send", side_effect=_recorder(sent)), \
            patch("custom_components.solar_energy_management.coordinator."
                  "repair_issues.raise_charger_actuation_failed") as repair:
        for amps in (10, 10, 10):
            await bare._set_current(amps)
    assert bare.charger_service is None
    assert sent == []
    assert bare._current_setpoint == 0
    assert bare._actuation_failures == 3
    assert repair.call_count == 1
    assert "#1376" in repair.call_args.kwargs["error"]

    stops = CurrentControlDevice(hass=hass, device_id="s", name="s",
                                 charger_service="zaptec.limit_current")
    stops.start_stop_entity = RESUME
    with patch.object(stops, "send", side_effect=_recorder([])):
        await stops._set_current(10)
    assert stops.charger_service is None
    assert stops._actuation_failures == 0


# ── guard: no write through the charger service without asking ──────────

def test_every_write_through_the_charger_service_asks_first():
    """A method that takes ``charger_service`` apart for more than its
    domain (``domain, service = …split(...)``, a whole split kept or passed
    on) can send the service itself, so it asks ``_settle_charger_service``
    before it. A new write path that forgets would write a site's limit."""
    src = (Path(hd.__file__).resolve().parent / "devices" / "base.py").read_text()
    tree = ast.parse(src)
    parent = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}

    def domain_only(call):
        up = parent.get(call)
        return (isinstance(up, ast.Subscript) and up.value is call
                and ast.unparse(up.slice) == "0")

    writers = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        splits = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == "split"
                  and "self.charger_service" in ast.unparse(n.func.value)
                  and not domain_only(n)]
        if not splits:
            continue
        writers.append(fn.name)
        asks = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
                and ast.unparse(n.func) == "self._settle_charger_service"]
        assert asks and min(asks) < min(s.lineno for s in splits), fn.name
    assert {"_set_current", "_send_phase_shape"} <= set(writers), writers
