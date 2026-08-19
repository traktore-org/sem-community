"""#805 — discovery is a suggestion, not consent.

A device SEM found by itself defaulted to ``peak_only``, an ACTING mode:
load management may shed it. With 2.0's actuation-on default that means a
fresh install can switch hardware the user never configured — which is
exactly how #803 happened (a wallbox visible in the Energy Dashboard got
discovered as a generic load, defaulted to peak_only, and was turned off
for peak; the reporter uninstalled to get his car charging).

Newly-discovered devices are now monitored until the user opts them in.

The migration is the delicate half: flipping a DEFAULT silently changes
every existing install whose devices never got an explicit override —
their peak shedding would just stop. So the upgrade writes explicit
``peak_only`` overrides for everything it already knows, and only devices
discovered AFTER that point get the new default. Behaviour on an existing
install is bit-for-bit unchanged; only first installs are quieter.
"""
from __future__ import annotations

from custom_components.solar_energy_management.features.device_registry import (
    DEFAULT_DISCOVERED_CONTROL_MODE, _freeze_known_control_modes,
)


class TestTheDefaultIsMonitorOnly:

    def test_a_freshly_discovered_device_does_not_act(self):
        assert DEFAULT_DISCOVERED_CONTROL_MODE == "off", (
            "a device SEM found by itself must be monitored, not actuated — "
            "#803: a discovered wallbox was shed for peak and the user "
            "uninstalled"
        )


class TestTheUpgradeChangesNothingForExistingInstalls:

    def test_known_devices_are_frozen_at_their_old_default(self):
        overrides = {}
        known = ["energy_dashboard_wallbox", "energy_dashboard_heater"]
        frozen = _freeze_known_control_modes(overrides, known)
        assert sorted(frozen) == sorted(known)
        assert overrides == {
            "energy_dashboard_wallbox": "peak_only",
            "energy_dashboard_heater": "peak_only",
        }

    def test_an_explicit_choice_is_never_overwritten(self):
        overrides = {"energy_dashboard_pump": "surplus",
                     "energy_dashboard_towel": "off"}
        _freeze_known_control_modes(overrides, ["energy_dashboard_pump",
                                                "energy_dashboard_towel"])
        assert overrides["energy_dashboard_pump"] == "surplus"
        assert overrides["energy_dashboard_towel"] == "off"

    def test_it_runs_once_not_every_restart(self):
        overrides = {}
        first = _freeze_known_control_modes(overrides, ["a"])
        assert first == ["a"]
        # A device the user later set to off must not be re-frozen to
        # peak_only on the next boot.
        overrides["a"] = "off"
        assert _freeze_known_control_modes(overrides, ["a"]) == []

    def test_a_device_discovered_after_the_freeze_stays_monitored(self):
        overrides = {}
        _freeze_known_control_modes(overrides, ["old_device"])
        assert "new_device" not in overrides, (
            "the freeze must not invent entries for devices it has never "
            "seen — those get the new monitor-only default"
        )


class TestTheFreezeCoversARealStore:
    """Pinned against a live 19-device store (PROD, 2026-08-19): 7 devices
    carried an explicit mode, 12 rode the implicit default. Those 12 are
    precisely what a naive default flip would have silently stopped
    shedding, so the roster keys the freeze reads are load-bearing."""

    STORE_KEYS = ("priority_overrides", "mappings", "device_goals",
                  "controllable_overrides", "rated_power_overrides",
                  "dependencies", "critical_overrides")

    def test_the_freeze_reads_every_roster_key_the_store_has(self):
        import inspect
        from custom_components.solar_energy_management.features import (
            device_registry as dr,
        )
        src = inspect.getsource(dr.UnifiedDeviceRegistry._load_mappings) \
            if hasattr(dr.UnifiedDeviceRegistry, "_load_mappings") \
            else inspect.getsource(dr)
        for key in self.STORE_KEYS:
            assert f'"{key}"' in src, (
                f"{key} names devices in the real store but the #805 freeze "
                f"would not see them — those devices would silently stop "
                f"being shed on upgrade"
            )
        # A READ, not the word — the comment above the freeze names the
        # key precisely to explain why it is absent.
        assert 'get("known_devices"' not in src, (
            "there is no known_devices key in the store; reading it would "
            "make the freeze look thorough while pinning nothing"
        )

    def test_a_roster_device_without_an_explicit_mode_is_frozen(self):
        overrides = {"energy_dashboard_keba_p30_total": "surplus"}
        roster = ["energy_dashboard_keba_p30_total",
                  "energy_dashboard_kaffeetoaster",
                  "energy_dashboard_garage_carport_licht"]
        frozen = _freeze_known_control_modes(overrides, roster)
        assert sorted(frozen) == ["energy_dashboard_garage_carport_licht",
                                  "energy_dashboard_kaffeetoaster"]
        assert overrides["energy_dashboard_keba_p30_total"] == "surplus"
        assert overrides["energy_dashboard_kaffeetoaster"] == "peak_only"
