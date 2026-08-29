"""#670 — the labels must exist in HA's label registry, not just on entities.

``entity_registry.async_update_entity(labels={...})`` stores label **IDs**
verbatim. It does not validate them and it does not create them. SEM never
called ``label_registry`` at all, so it wrote 19 ids HA had never heard of:

    labels('sensor.sem_monthly_solar_yield_energy')  -> [4 labels]   forward OK
    label_entities('sem_monthly')                    -> 0            reverse dead
    label_id('sem_monthly')                          -> None

The reverse direction is the entire feature — it is what the HA UI's label
filter, label-scoped automations and ``label_entities()`` templates use. Two
silent no-ops stacked (an unknown id is accepted; a missing mapping key returns
an empty set), so the whole thing reported healthy while doing nothing end to
end. It is also why #667's drift survived for years: with the registry side
missing, a *correct* label and a typo'd one behaved identically.

The tests below check both directions, because only checking the one SEM writes
is what let this hide.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.helpers import label_registry as lr

from custom_components.solar_energy_management.consts.labels import (
    SEM_LABELS,
    SENSOR_LABEL_MAPPING,
)
from custom_components.solar_energy_management.sensor import (
    _ensure_labels_registered,
)


@pytest.mark.unit
class TestLabelDefinitions670:
    def test_every_label_applied_to_an_entity_is_defined(self):
        """A mapping entry naming an undefined label would never be created,
        so it would resolve to nothing exactly as before #670."""
        used = set().union(*SENSOR_LABEL_MAPPING.values())
        assert not used - set(SEM_LABELS), (
            f"{sorted(used - set(SEM_LABELS))} applied to entities but not in "
            "SEM_LABELS — they would never be registered with HA (#670)."
        )

    def test_no_defined_label_is_attached_to_nothing(self):
        """Since #670 these become real labels in the user's registry. A dead
        one is no longer harmlessly inert — it shows up in their label list and
        does nothing (this is what retired ``sem_exclude``)."""
        used = set().union(*SENSOR_LABEL_MAPPING.values())
        assert not set(SEM_LABELS) - used, (
            f"{sorted(set(SEM_LABELS) - used)} defined but attached to no "
            "entity — do not create labels that do nothing (#670)."
        )

    def test_label_ids_survive_ha_slugification(self):
        """The whole design rests on ``label_id == slugify(name)``: SEM creates
        a label *named* ``sem_daily`` and relies on getting the id
        ``sem_daily`` back, because that raw string is what the mapping (and
        every already-labelled entity registry row) uses. A key that does not
        survive slugify would silently get a different id."""
        from homeassistant.util import slugify

        for label_id in SEM_LABELS:
            assert slugify(label_id) == label_id, (
                f"{label_id!r} slugifies to {slugify(label_id)!r} — creating it "
                "would yield a different id than the mapping applies (#670)."
            )


@pytest.mark.integration
class TestLabelRegistration670:
    async def test_setup_registers_every_sem_label(self, hass):
        registry = lr.async_get(hass)
        assert not [lb for lb in registry.async_list_labels() if lb.label_id in SEM_LABELS]

        _ensure_labels_registered(hass)

        for label_id, description in SEM_LABELS.items():
            entry = registry.async_get_label(label_id)
            assert entry is not None, f"{label_id} not registered (#670)"
            assert entry.description == description

    async def test_the_reverse_lookup_actually_resolves(self, hass):
        """THE closure — the direction the bug killed, exercised through the
        exact code path the HA UI and templates use.

        ``template.label_entities`` resolves the name through the *label*
        registry first and returns ``[]`` when that misses, before it ever
        looks at the entity registry's index. So the entity was always in the
        index; the gate in front of it was the missing piece.
        """
        from homeassistant.helpers import entity_registry as er

        # (#791) HA 2026.8 moved ``label_entities`` from a module-level
        # function into the template engine's LabelExtension — the
        # PUBLIC surface (a rendered template) is the same on every
        # supported HA, so the oracle goes through it instead of the
        # implementation's address.
        try:
            from homeassistant.helpers.template import label_entities
        except ImportError:  # 2026.8+ — render the template surface
            from homeassistant.helpers.template import Template

            def label_entities(hass_, name):
                return Template(
                    "{{ label_entities(%r) | list }}" % name, hass_
                ).async_render()

        ent_reg = er.async_get(hass)
        entry = ent_reg.async_get_or_create(
            "sensor", "solar_energy_management", "test_670_unique",
            suggested_object_id="sem_monthly_solar_yield_energy",
        )
        ent_reg.async_update_entity(entry.entity_id, labels={"sem_monthly"})

        # Pre-fix behaviour: label attached, reverse lookup dead.
        assert label_entities(hass, "sem_monthly") == []

        _ensure_labels_registered(hass)

        assert entry.entity_id in label_entities(hass, "sem_monthly"), (
            "the entity carries the label but is unreachable through it — this "
            "is exactly the #670 symptom, not a fix for it"
        )

    async def test_it_is_idempotent_across_restarts(self, hass):
        """Runs on every setup. A second pass must not create duplicates
        (``sem_daily_2``) — those would carry no entities at all."""
        _ensure_labels_registered(hass)
        _ensure_labels_registered(hass)

        registry = lr.async_get(hass)
        sem = [lb for lb in registry.async_list_labels() if lb.label_id.startswith("sem_")]
        assert len(sem) == len(SEM_LABELS), (
            f"{len(sem)} sem_* labels for {len(SEM_LABELS)} keys — duplicates "
            f"created: {sorted(lb.label_id for lb in sem)}"
        )

    async def test_a_user_customisation_is_never_clobbered(self, hass):
        """Create-only. A user who renames or recolours a SEM label keeps it —
        we match on id, and an existing id is left completely alone."""
        registry = lr.async_get(hass)
        _ensure_labels_registered(hass)
        registry.async_update("sem_battery", name="My Battery Stuff", color="red")

        _ensure_labels_registered(hass)

        entry = registry.async_get_label("sem_battery")
        assert entry.name == "My Battery Stuff"
        assert entry.color == "red"

    async def test_unrelated_user_labels_are_untouched(self, hass):
        """The real HA-TEST registry held four of the user's own labels
        (pv_anlage, e_mobility, elektro, bewasserung) when this was found."""
        registry = lr.async_get(hass)
        mine = registry.async_create(name="pv_anlage", color="green")

        _ensure_labels_registered(hass)

        still = registry.async_get_label(mine.label_id)
        assert still is not None
        assert still.name == "pv_anlage"
        assert still.color == "green"

    async def test_a_name_collision_does_not_raise(self, hass):
        """If a user renamed one of their own labels to exactly ours,
        ``async_create`` raises ValueError. Setup must survive it — theirs
        wins, we do not rename or delete user labels."""
        registry = lr.async_get(hass)
        theirs = registry.async_create(name="mine")
        registry.async_update(theirs.label_id, name="sem_solar")

        _ensure_labels_registered(hass)  # must not raise

        assert registry.async_get_label(theirs.label_id).name == "sem_solar"

    def test_an_unloaded_registry_does_not_take_the_platform_down(self):
        """Labels are cosmetic; nothing here may break sensor setup.

        Caught by two ``test_integration`` tests, not by the ones above: those
        use the real ``hass`` fixture, whose label registry has been loaded, so
        they never walk this path. With a registry that was never loaded, the
        *read* raises ``AttributeError: no attribute '_label_data'`` — and
        before the guard that propagated out of ``async_setup_entry`` and took
        the whole sensor platform with it. A MagicMock hass (as the integration
        tests use) hits exactly this.
        """
        from unittest.mock import MagicMock

        hass = MagicMock()
        unloaded = lr.LabelRegistry(hass)  # deliberately no async_load()

        with pytest.raises(AttributeError):
            unloaded.async_get_label("sem_daily")

        with patch.object(lr, "async_get", return_value=unloaded):
            _ensure_labels_registered(hass)  # must not raise
