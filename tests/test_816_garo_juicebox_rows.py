"""#816 — GARO and JuiceBox 48 become brand rows, from their reporters' evidence.

Both chargers are proven working on real installs — GARO through #700/#748
(the 6 A floor drove the STOP-unenforceable fix, confirmed on v1.7.6-beta.14),
JuiceBox 48 through #683/#698 (SOC mix-up and Load-Management double-detection,
both fixed and confirmed) — and both still forced their owners through the
generic/manual path, on brands the matrix already lists.

#814 made brand support data precisely so this costs no per-brand machinery.
Two notes from the issue are load-bearing and pinned here:

* **GARO's 6 A floor is a hardware property, and the row carries it.** #700
  exists because SEM kept issuing an unenforceable stop against that floor —
  detection that finds the entity but not the floor re-arms that bug for the
  next GARO owner.
* **JuiceBox rides the generic ``mqtt`` platform**, so its matcher must be
  provably unable to claim someone's unrelated MQTT devices: every role
  requires the juicebox naming, and identity requires power AND energy
  together. A Shelly plug publishing power over MQTT must not become a
  charger.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.hardware_detection import (
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


class TestGaro:
    """The reporter's shape from #700/#748: switch.garo_laddbox + a
    current-limit number with a 6 A hardware floor."""

    def _entries(self):
        return [
            _entry("switch.garo_laddbox", "garo_wallbox", "garo-1"),
            _entry("number.garo_charge_limit", "garo_wallbox", "garo-1",
                   device_class="current"),
            _entry("sensor.garo_charging_power", "garo_wallbox", "garo-1",
                   device_class="power"),
            _entry("sensor.garo_status", "garo_wallbox", "garo-1"),
        ]

    def test_the_charger_is_discovered(self):
        found = _discover(self._entries())
        assert len(found) == 1, found
        c = found[0]
        assert c["ev_current_control_entity"] == "number.garo_charge_limit"
        assert c["ev_start_stop_entity"] == "switch.garo_laddbox"
        assert c["ev_charging_power_sensor"] == "sensor.garo_charging_power"

    def test_the_six_amp_floor_rides_the_row(self):
        """#700's whole story: SEM commanded below the floor and the stop was
        unenforceable. The floor is hardware, so detection must carry it."""
        c = _discover(self._entries())[0]
        assert c.get("ev_min_current") == 6, (
            "the GARO row does not carry its 6 A floor — the next GARO owner "
            "re-lives #700 (#816)"
        )


class TestJuiceBox:
    """#683/#698's shape: JuiceBoxProxy over MQTT, platform 'mqtt',
    sensor.juicebox_<id>_* naming, lifetime AND session energy both present."""

    def _entries(self):
        return [
            _entry("sensor.juicebox_abc123_power", "mqtt", "jb-1",
                   device_class="power"),
            _entry("sensor.juicebox_abc123_energy_lifetime", "mqtt", "jb-1",
                   device_class="energy"),
            _entry("sensor.juicebox_abc123_energy_session", "mqtt", "jb-1",
                   device_class="energy"),
            _entry("sensor.juicebox_abc123_status", "mqtt", "jb-1"),
            _entry("number.juicebox_abc123_max_current", "mqtt", "jb-1",
                   device_class="current"),
        ]

    def test_the_charger_is_discovered_with_both_energies(self):
        found = _discover(self._entries())
        assert len(found) == 1, found
        c = found[0]
        assert c["ev_charging_power_sensor"] == "sensor.juicebox_abc123_power"
        assert c["ev_total_energy_sensor"] == "sensor.juicebox_abc123_energy_lifetime"
        assert c["ev_session_energy_sensor"] == "sensor.juicebox_abc123_energy_session"
        assert c["ev_current_control_entity"] == "number.juicebox_abc123_max_current"

    def test_an_unrelated_mqtt_device_is_never_claimed(self):
        """The mqtt platform is everyone's platform. A Shelly plug with power
        and energy must not become a charger."""
        entries = [
            _entry("sensor.shelly_toaster_power", "mqtt", "sh-1",
                   device_class="power"),
            _entry("sensor.shelly_toaster_energy", "mqtt", "sh-1",
                   device_class="energy"),
            _entry("switch.shelly_toaster", "mqtt", "sh-1"),
        ]
        assert _discover(entries) == [], (
            "a non-juicebox MQTT device was registered as a charger (#816)"
        )

    def test_power_alone_is_not_identity(self):
        """Even juicebox-named, one sensor is not a charger (#695/#698)."""
        entries = [
            _entry("sensor.juicebox_abc123_power", "mqtt", "jb-1",
                   device_class="power"),
        ]
        assert _discover(entries) == []
