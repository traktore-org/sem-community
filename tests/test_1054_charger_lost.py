"""#1054 round 3 (weindler, 11.10.2026, beta.15) — the working go-e was gone.

The old card an earlier detection had half-filled (``goecharger_28eb748ac3``:
a name and one energy counter) sat FIRST in both stores. Being first made it
the primary charger, and three things followed:

1. the Configure dialog's "Remove a charger" never offered the primary, so
   the only charger it listed was the working go-e;
2. the Detected-hardware page counted the go-e as configured because the old
   card named one of its entities, so the complete offer — and its create
   button — was hidden, and the working charger could not be made again;
3. the removed charger's daily kWh and SOC rows stayed published, so the
   health check warned every cycle ("9.45 kWh against a fleet total of 0").

The rule now: a complete charger always wins over a half-filled card for the
same box, a half-filled card never claims or hides its box, and state of a
charger that is no longer configured is dropped.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management import _merge_ev_chargers_by_id
from custom_components.solar_energy_management.hardware_detection import (
    build_detection_report,
    charger_is_complete,
)

from .test_1054_goe_followup import P, _configured_goe, _goe_entities, _registry

OLD = {
    "id": "goecharger_28eb748ac3",
    "name": "Goecharger Charger",
    "ev_total_energy_sensor": f"sensor.{P}_energy_total",
}
NEW = {**_configured_goe(), "id": "goecharger_118c19168da8cdf95739aaf95b2598a4"}


def _device_of(eid: str):
    """Every go-e entity sits on the box ``dev1``; anything else is unknown."""
    return "dev1" if eid.startswith(("sensor.goecharger_", "switch.goecharger_")) else None


def _through_refs(existing, incoming, live=None):
    """What the user sees after a write: set_option's merge (siblings kept),
    then the next start's refs decide one charger per device (#1054)."""
    from custom_components.solar_energy_management.charger_refs import (
        reconcile, signature,
    )
    refs, resolved = reconcile(data_list=None, legacy=[dict(c) for c in existing],
                               refs=None, sig=None, device_of=_device_of,
                               live_by_device=live or {})
    merged = _merge_ev_chargers_by_id(resolved, [dict(c) for c in incoming])
    _refs, out = reconcile(data_list=None, legacy=merged, refs=refs,
                           sig=signature(resolved), device_of=_device_of,
                           live_by_device=live or {})
    return out


# ── the rule ─────────────────────────────────────────────────────────────

class TestCompleteWins:

    def test_what_complete_means(self):
        assert charger_is_complete(NEW)
        assert not charger_is_complete(OLD)
        assert not charger_is_complete(None)

    def test_a_charger_without_plug_sensors_is_complete(self):
        """(#1092 suite) V2C, NRGkick, OpenEVSE, Peblar and Zaptec have no
        plug or charging sensor. A power reading and a control is a charger
        SEM can run; the setup form's three sensors are not the rule."""
        for control in ({"ev_current_control_entity": "number.box_current"},
                        {"ev_charger_service": "zaptec.limit_current"},
                        {"ev_start_stop_entity": "switch.box_charge"},
                        {"ev_start_service": "keba.enable"},
                        {"ev_charge_mode_entity": "select.box_mode"}):
            card = {"ev_charging_power_sensor": "sensor.box_power", **control}
            assert charger_is_complete(card), control
        assert not charger_is_complete(
            {"ev_charging_power_sensor": "sensor.box_power"})

    def test_the_create_replaces_the_half_filled_card_of_the_same_box(self):
        """weindler's state, then the create button: one charger, the
        working one, in the old card's place."""
        out = _through_refs([dict(OLD)], [dict(NEW)])
        assert [c["id"] for c in out] == [NEW["id"]]
        assert out[0]["ev_charger_service"] == "goecharger.set_max_current"

    def test_it_takes_the_old_cards_place_so_a_primary_stays_primary(self):
        other = {"id": "keba", "name": "KEBA",
                 "ev_charging_power_sensor": "sensor.keba_power",
                 "ev_charger_service": "keba.set_current"}
        out = _through_refs([dict(OLD), dict(other)], [dict(NEW)])
        assert [c["id"] for c in out] == [NEW["id"], "keba"]

    def test_an_existing_complete_charger_drops_the_half_card(self):
        out = _through_refs([dict(OLD), dict(NEW)], [dict(NEW)])
        assert [c["id"] for c in out] == [NEW["id"]]

    def test_a_complete_card_is_never_displaced(self):
        twin = {**NEW, "id": "goecharger_twin"}
        out = _through_refs([dict(twin)], [dict(NEW)])
        # a copy of the running charger → the running one keeps the box
        assert [c["id"] for c in out] == ["goecharger_twin"]
        assert charger_is_complete(out[0])

    def test_a_half_card_on_another_box_stays(self):
        stranger = {"id": "other", "ev_total_energy_sensor": "sensor.other_energy"}
        out = _through_refs([dict(stranger)], [dict(NEW)])
        assert [c["id"] for c in out] == ["other", NEW["id"]]

    def test_a_half_incoming_card_never_displaces_anything(self):
        out = _through_refs([dict(NEW)], [{**OLD}])
        assert [c["id"] for c in out] == [NEW["id"]]

    def test_the_heal_never_displaces(self):
        """No device lookup, no fold — the start-up heal keeps both for the
        user to sort out, as before."""
        out = _merge_ev_chargers_by_id([dict(OLD)], [dict(OLD), dict(NEW)])
        assert [c["id"] for c in out] == [OLD["id"], NEW["id"]]


# ── the report: a half-filled card does not claim its box ─────────────────

class TestTheReportOffersTheBoxAgain:

    def test_a_half_card_does_not_hide_the_box(self):
        rep = build_detection_report(registry=_registry(_goe_entities()),
                                     configured_chargers=[dict(OLD)])
        configured = [c for c in rep["chargers"] if c.get("configured")]
        assert configured == [], configured
        assert [i["charger_id"] for i in rep["incomplete_chargers"]] == [OLD["id"]]
        # the box is walked exactly as an unconfigured one: same offer
        bare = build_detection_report(registry=_registry(_goe_entities()))
        assert rep["chargers"] == bare["chargers"]
        assert rep["near_misses"] == bare["near_misses"]
        assert any(n.get("suggested_charger") for n in rep["near_misses"]
                   if n["platform"] == "goecharger")

    def test_a_complete_card_still_claims_it(self):
        rep = build_detection_report(registry=_registry(_goe_entities()),
                                     configured_chargers=[dict(OLD), dict(NEW)])
        rows = [c for c in rep["chargers"] if c.get("configured")]
        assert [r["charger_id"] for r in rows] == [NEW["id"]]


# ── the Configure dialog can remove the half card ─────────────────────────

class TestTheDialogCanRemoveTheHalfCard:

    @staticmethod
    async def _remove_choices(chargers):
        from custom_components.solar_energy_management.config_flow import (
            OptionsFlowHandler,
        )
        flow = OptionsFlowHandler.__new__(OptionsFlowHandler)
        flow._data = {"ev_chargers": [dict(c) for c in chargers]}
        flow.hass = None
        shown = {}

        def _show_form(**kw):
            shown.update(kw)
            return kw

        flow.async_show_form = _show_form

        async def _menu(*a, **k):
            return {"menu": True}

        flow.async_step_ev_charger_menu = _menu
        res = await flow.async_step_ev_charger_remove()
        if res.get("menu"):
            return None
        sel = shown["data_schema"].schema
        field = next(iter(sel.values()))
        return [o["value"] for o in field.config["options"]]

    @pytest.mark.asyncio
    async def test_a_half_filled_primary_is_offered(self):
        assert await self._remove_choices([OLD, NEW]) == [OLD["id"], NEW["id"]]

    @pytest.mark.asyncio
    async def test_a_working_primary_is_still_protected(self):
        assert await self._remove_choices([NEW, OLD]) == [OLD["id"]]

    @pytest.mark.asyncio
    async def test_the_last_charger_is_never_offered(self):
        assert await self._remove_choices([OLD]) is None


# ── state of a removed charger is dropped ─────────────────────────────────

class TestStaleStateIsSwept:

    @staticmethod
    def _coord(chargers, daily, detectors, devices=()):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        fake = SimpleNamespace(
            config={"ev_chargers": chargers},
            _ev_devices={d: object() for d in devices},
            _daily_ev_per_charger=dict(daily),
            _daily_ev_per_charger_date={k: "2026-10-11" for k in daily},
            _ev_taper_detectors={k: MagicMock() for k in detectors},
        )
        swept = SEMCoordinator._sweep_unconfigured_charger_state(fake)
        return fake, swept

    def test_weindlers_buckets_go(self):
        stale = [NEW["id"]] + [f"{NEW['id']}_{n}" for n in range(1, 5)]
        fake, swept = self._coord([dict(OLD)], {NEW["id"]: 9.45},
                                  stale)
        assert swept == sorted(stale)
        assert fake._daily_ev_per_charger == {}
        assert fake._ev_taper_detectors == {}

    def test_a_configured_charger_keeps_its_state(self):
        fake, swept = self._coord([dict(NEW)], {NEW["id"]: 9.45}, [NEW["id"]])
        assert swept == []
        assert fake._daily_ev_per_charger == {NEW["id"]: 9.45}

    def test_a_registered_device_keeps_its_state(self):
        fake, swept = self._coord([], {"ev_charger_0": 1.0}, [],
                                  devices=["ev_charger_0"])
        assert swept == []

    def test_an_id_less_charger_stops_the_sweep(self):
        fake, swept = self._coord([{"name": "no id"}], {"ev_charger_0": 1.0},
                                  ["ev_charger_0"])
        assert swept == []
        assert fake._daily_ev_per_charger == {"ev_charger_0": 1.0}


# ── the real set_option path: one write, both stores, survives a reload ───

@pytest.mark.asyncio
async def test_setup_folds_a_half_card_into_the_complete_one(
    sem_real_hass, sem_multi_wallbox_config_entry,
):
    """A half card for the right box first, the complete one second (the
    beta.13 shape). (#1054 device refs) The first start makes one ref per
    device: the complete charger, in the half card's place; ``entry.data``
    keeps no list, so nothing can bring the half card back."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.solar_energy_management.const import DOMAIN

    from .test_services_real import _seed_sem_input_sensors, _setup_sem

    h = sem_real_hass
    _seed_sem_input_sensors(h)
    for side in ("left", "right"):
        h.states.async_set(f"sensor.test_wb_{side}_charging_power", "0",
                           {"unit_of_measurement": "W"})
        h.states.async_set(f"number.test_wb_{side}_max_current", "0",
                           {"unit_of_measurement": "A"})
        h.states.async_set(f"binary_sensor.test_wb_{side}_cable_connected", "off")
        h.states.async_set(f"sensor.test_wb_{side}_status", "idle")
    box_entry = MockConfigEntry(domain="test_wb")
    box_entry.add_to_hass(h)
    dev = dr.async_get(h).async_get_or_create(
        config_entry_id=box_entry.entry_id, identifiers={("test_wb", "right")})
    reg = er.async_get(h)
    for domain, obj in (("sensor", "test_wb_right_charging_power"),
                        ("sensor", "test_wb_right_status"),
                        ("sensor", "test_wb_right_charging_energy"),
                        ("binary_sensor", "test_wb_right_cable_connected"),
                        ("number", "test_wb_right_max_current")):
        reg.async_get_or_create(domain, "test_wb", obj, suggested_object_id=obj,
                                config_entry=box_entry, device_id=dev.id)

    base = sem_multi_wallbox_config_entry
    left, right = base.data["ev_chargers"]
    half = {"id": "right_old", "name": "Old card",
            "ev_total_energy_sensor": "sensor.test_wb_right_charging_energy"}
    complete = {**right, "id": "right_new",
                "ev_total_energy_sensor": "sensor.test_wb_right_charging_energy"}
    entry = MockConfigEntry(domain=DOMAIN, version=base.version,
                            minor_version=base.minor_version,
                            data={**base.data, "ev_chargers": [half, left]},
                            options={"ev_chargers": [dict(half), dict(left), dict(complete)]})
    await _setup_sem(h, entry)

    assert [r["id"] for r in entry.options["ev_charger_refs"]] == ["right_new", "ev_charger"]
    assert [c["id"] for c in entry.options["ev_chargers"]] == ["right_new", "ev_charger"]
    assert "ev_chargers" not in entry.data

    await h.config_entries.async_reload(entry.entry_id)
    await h.async_block_till_done()
    assert [r["id"] for r in entry.options["ev_charger_refs"]] == ["right_new", "ev_charger"]
    assert sorted(entry.runtime_data._ev_devices) == ["ev_charger", "right_new"]
