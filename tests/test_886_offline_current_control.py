"""#886 — the JuiceBox 'offline' current limit is never the live control surface.

Reporter (@Azlinon, 2.1.0-beta.3): JuiceBox auto-detection bound
``number.juicebox_max_current_offline_wanted`` as ``ev_current_control_entity``.
The offline register is a disconnected-mode FALLBACK — a limited-write setting
the box honours only when it has lost its server — not the online limit SEM
drives every cycle. Driving it means writing frequent current updates to a knob
that must not receive them.

Bug class 56 (a mode-qualified fallback register bound as the live control
surface). The closure is brand-agnostic: ``_reject_offline_current_control``
runs at the single discovery choke point every brand's config flows through, so
these pins assert the CLASS, not just the JuiceBox instance:

* the online twin is bound regardless of registry ordering (last-wins must not
  decide which connection MODE SEM drives);
* an offline-only charger DROPS the binding (monitor-only) rather than
  actuating the wrong register — the fail-closed, actuation-path rule;
* a plain single ``max_current`` is untouched (no regression to #816);
* the guard holds for a hand-written brand shape too, so the closure is at the
  choke point, not in the JuiceBox hint.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management import (
    _heal_offline_current_control_in_list,
)
from custom_components.solar_energy_management.hardware_detection import (
    _reject_offline_current_control,
    discover_all_ev_chargers_from_registry,
)


def _entry(entity_id, platform, device_id, device_class=None, unique_id=""):
    return SimpleNamespace(
        entity_id=entity_id, platform=platform, device_id=device_id,
        original_device_class=device_class, disabled_by=None,
        unique_id=unique_id or entity_id.split(".", 1)[1],
    )


def _discover(entries):
    registry = MagicMock()
    registry.entities.values.return_value = entries
    with patch(
        "custom_components.solar_energy_management.hardware_detection."
        "entity_registry.async_get",
        return_value=registry,
    ):
        return discover_all_ev_chargers_from_registry(MagicMock())


# The reporter's shape: identity (power + both energy counters, juicebox-named)
# plus the two current-limit numbers that differ only by connection mode.
_ONLINE = "number.juicebox_max_current_online_wanted"
_OFFLINE = "number.juicebox_max_current_offline_wanted"


def _juicebox_identity():
    return [
        _entry("sensor.juicebox_power", "mqtt", "jb-1", device_class="power"),
        _entry("sensor.juicebox_energy_lifetime", "mqtt", "jb-1",
               device_class="energy"),
        _entry("sensor.juicebox_energy_session", "mqtt", "jb-1",
               device_class="energy"),
        _entry("sensor.juicebox_status", "mqtt", "jb-1"),
    ]


class TestJuiceBoxOnlineOverOffline:
    def test_online_bound_when_offline_is_last(self):
        """last-wins would pick offline here — the guard must overrule it."""
        entries = _juicebox_identity() + [
            _entry(_ONLINE, "mqtt", "jb-1", device_class="current"),
            _entry(_OFFLINE, "mqtt", "jb-1", device_class="current"),
        ]
        c = _discover(entries)[0]
        assert c["ev_current_control_entity"] == _ONLINE, (
            "the offline fallback register was bound as the live control (#886)"
        )

    def test_online_bound_when_offline_is_first(self):
        """the fix must be ordering-independent, not merely 'prefer the last'."""
        entries = _juicebox_identity() + [
            _entry(_OFFLINE, "mqtt", "jb-1", device_class="current"),
            _entry(_ONLINE, "mqtt", "jb-1", device_class="current"),
        ]
        c = _discover(entries)[0]
        assert c["ev_current_control_entity"] == _ONLINE

    def test_offline_only_drops_the_binding(self):
        """No online twin exists → monitor-only beats driving the wrong knob.
        The charger is still discovered (power + energy), just uncontrolled."""
        entries = _juicebox_identity() + [
            _entry(_OFFLINE, "mqtt", "jb-1", device_class="current"),
        ]
        found = _discover(entries)
        assert len(found) == 1, found
        assert "ev_current_control_entity" not in found[0], (
            "SEM would actuate the offline fallback register (#886)"
        )

    def test_plain_max_current_is_untouched(self):
        """The #816 shape (one plain max_current, no mode split) still binds."""
        entries = _juicebox_identity() + [
            _entry("number.juicebox_max_current", "mqtt", "jb-1",
                   device_class="current"),
        ]
        c = _discover(entries)[0]
        assert c["ev_current_control_entity"] == "number.juicebox_max_current"


class TestGuardIsBrandAgnostic:
    """The closure lives at the choke point, so it must not know about
    JuiceBox — prove it on a hand-written-brand-shaped result too."""

    def test_swaps_to_online_twin(self):
        result = {"ev_current_control_entity":
                  "number.goe_123_max_current_offline"}
        entities = [
            _entry("number.goe_123_max_current_offline", "goecharger_mqtt", "g"),
            _entry("number.goe_123_max_current_online", "goecharger_mqtt", "g"),
        ]
        _reject_offline_current_control(result, entities)
        assert (result["ev_current_control_entity"]
                == "number.goe_123_max_current_online")

    def test_drops_when_no_online_counterpart(self):
        result = {"ev_current_control_entity":
                  "number.goe_123_max_current_offline"}
        entities = [
            _entry("number.goe_123_max_current_offline", "goecharger_mqtt", "g"),
        ]
        _reject_offline_current_control(result, entities)
        assert "ev_current_control_entity" not in result

    def test_noop_when_control_is_not_offline(self):
        result = {"ev_current_control_entity": "number.goe_123_requested_current"}
        entities = [
            _entry("number.goe_123_requested_current", "goecharger_mqtt", "g"),
        ]
        _reject_offline_current_control(dict(result), entities)
        # untouched
        _reject_offline_current_control(result, entities)
        assert (result["ev_current_control_entity"]
                == "number.goe_123_requested_current")

    def test_online_named_number_wins_when_no_exact_twin(self):
        """No literal offline→online rename match, but an online number exists."""
        result = {"ev_current_control_entity": "number.acme_limit_offline_a"}
        entities = [
            _entry("number.acme_limit_offline_a", "acme", "a"),
            _entry("number.acme_online_limit", "acme", "a"),
        ]
        _reject_offline_current_control(result, entities)
        assert result["ev_current_control_entity"] == "number.acme_online_limit"


class TestPersistedInstallHeal:
    """The reporter's charger is ALREADY persisted with the offline binding,
    and detection only re-runs when NO charger is configured — so the stored
    list must self-heal at setup, or the fix never reaches their install."""

    def _registry(self, entries):
        reg = MagicMock()
        by_id = {str(e.entity_id): e for e in entries}
        reg.async_get.side_effect = lambda eid: by_id.get(str(eid))
        reg.entities.values.return_value = entries
        return reg

    def test_persisted_offline_binding_is_swapped_to_online(self):
        entries = [
            _entry(_ONLINE, "mqtt", "jb-1", device_class="current"),
            _entry(_OFFLINE, "mqtt", "jb-1", device_class="current"),
        ]
        chargers = [{"id": "ev_charger", "name": "Juicebox Charger",
                     "ev_current_control_entity": _OFFLINE}]
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=self._registry(entries),
        ):
            healed = _heal_offline_current_control_in_list(MagicMock(), chargers)
        assert healed is not None, "the persisted offline binding was not healed"
        assert healed[0]["ev_current_control_entity"] == _ONLINE

    def test_idempotent_once_healed(self):
        entries = [_entry(_ONLINE, "mqtt", "jb-1", device_class="current")]
        hass = MagicMock()
        chargers = [{"id": "ev_charger", "ev_current_control_entity": _ONLINE}]
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=MagicMock(),
        ):
            assert _heal_offline_current_control_in_list(hass, chargers) is None

    def test_heal_does_not_drop_when_no_online_twin(self):
        """A registry that cannot resolve the online twin must LEAVE the
        binding — never silently disable an already-working charger's control."""
        reg = MagicMock()
        reg.async_get.return_value = None  # offline entity not resolvable
        reg.entities.values.return_value = []
        hass = MagicMock()
        chargers = [{"id": "ev_charger", "ev_current_control_entity": _OFFLINE}]
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=reg,
        ):
            healed = _heal_offline_current_control_in_list(hass, chargers)
        assert healed is None, "the heal dropped a binding it could not repair"

    def test_other_chargers_untouched(self):
        entries = [
            _entry(_ONLINE, "mqtt", "jb-1", device_class="current"),
            _entry(_OFFLINE, "mqtt", "jb-1", device_class="current"),
        ]
        reg = MagicMock()
        by_id = {str(e.entity_id): e for e in entries}
        reg.async_get.side_effect = lambda eid: by_id.get(str(eid))
        reg.entities.values.return_value = entries
        hass = MagicMock()
        chargers = [
            {"id": "a", "ev_current_control_entity": "number.keba_max_current"},
            {"id": "b", "ev_current_control_entity": _OFFLINE},
        ]
        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=reg,
        ):
            healed = _heal_offline_current_control_in_list(hass, chargers)
        assert healed[0]["ev_current_control_entity"] == "number.keba_max_current"
        assert healed[1]["ev_current_control_entity"] == _ONLINE
