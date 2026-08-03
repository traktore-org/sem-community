"""#679 — the #634 "floor 0 = never grids at night" default must be reachable.

#634 settled the axis with Guido: the mode is the *daytime* axis, the "At least"
floor is the overnight guarantee, and it applies in every mode including
``solar_only``. The safety half of that deal is that an unset floor means 0,
which is how the #346 contract ("solar_only never grids at night") survives as
the default.

It was not reachable. ``_install_defaults()`` persists ``daily_ev_target: 10``
into the entry on every install, and an absent ``ev_target_soc`` resolves to 80.
The gate fell back to those globals, so a fresh ``solar_only`` charger joined the
night lane — behaving exactly like ``min_plus_solar``, which makes it not a
distinct mode at all. onkelfu's install (#627) is the live case.

The existing contract test (``test_629_ev_orchestration.py::
test_night_lane_gate_floor_aware``) passes because it hand-builds
``{"daily_ev_target": 0}`` — a config ``_install_defaults()`` never produces.
That is the #256 shape: the zero-config path is the one nobody tests. So the
tests here drive the *installed* config, not a constructed one.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.consts.ev_charge_modes import (
    mode_allows_night_charging,
    solar_only_night_floor,
)


def _installed_config(**charger_overrides) -> dict:
    """A config shaped exactly like a fresh install, not a hand-built one."""
    from custom_components.solar_energy_management.config_flow import (
            SolarEnergyManagementConfigFlow as ConfigFlow,
        )

    cfg = dict(ConfigFlow._install_defaults())
    charger = {"id": "ev_charger", "name": "EV Charger",
               "charge_mode": "solar_only"}
    charger.update(charger_overrides)
    cfg["ev_chargers"] = [charger]
    return cfg


class TestTheDefaultIsReachable:
    def test_install_defaults_really_do_seed_a_nonzero_global_floor(self):
        """Pin the premise. If this ever becomes 0, the bug is gone at source."""
        from custom_components.solar_energy_management.config_flow import (
            SolarEnergyManagementConfigFlow as ConfigFlow,
        )

        assert ConfigFlow._install_defaults()["daily_ev_target"] > 0.1, (
            "The premise of #679 changed: the installer no longer seeds a "
            "nonzero global floor. Re-derive the gate rather than deleting "
            "this — the fix below assumes the global cannot express intent."
        )

    def test_fresh_solar_only_charger_does_not_join_the_night_lane(self):
        """THE regression. A default install must keep the #346 contract."""
        cfg = _installed_config()
        assert mode_allows_night_charging(cfg, cfg["ev_chargers"][0]) is False

    def test_a_deliberate_per_charger_floor_still_opts_in(self):
        """#634 must keep working — this fix narrows the opt-in, not removes it."""
        cfg = _installed_config(daily_ev_target=1.5)
        assert mode_allows_night_charging(cfg, cfg["ev_chargers"][0]) is True

    def test_an_explicit_per_charger_zero_stays_out(self):
        cfg = _installed_config(daily_ev_target=0)
        assert mode_allows_night_charging(cfg, cfg["ev_chargers"][0]) is False


class TestTargetBasis:
    """The gate read ``daily_ev_target`` even on a ``%``-targeted charger."""

    def test_soc_targeted_charger_reads_its_own_floor_key(self):
        cfg = _installed_config(ev_target_type="soc", ev_target_soc=90)
        assert mode_allows_night_charging(cfg, cfg["ev_chargers"][0]) is True

    def test_soc_targeted_charger_ignores_the_kwh_floor(self):
        """onkelfu's shape: SOC-targeted, no per-charger kWh floor.

        The old gate consulted the seeded global ``daily_ev_target`` — a key
        this charger does not use — and enabled night charging on the strength
        of it.
        """
        cfg = _installed_config(ev_target_type="soc")
        assert cfg["daily_ev_target"] > 0.1          # the seeded global is there
        assert mode_allows_night_charging(cfg, cfg["ev_chargers"][0]) is False

    def test_kwh_targeted_charger_ignores_a_soc_floor(self):
        cfg = _installed_config(ev_target_type="kwh", ev_target_soc=90)
        assert mode_allows_night_charging(cfg, cfg["ev_chargers"][0]) is False


class TestOtherModesUnaffected:
    """Only ``solar_only`` opts in. The other night modes top up by definition."""

    @pytest.mark.parametrize(
        "mode", ["min_plus_solar", "solar_plus_cheap", "always_max"],
    )
    def test_night_modes_still_allowed_without_any_per_charger_floor(self, mode):
        cfg = _installed_config(charge_mode=mode)
        assert mode_allows_night_charging(cfg, cfg["ev_chargers"][0]) is True

    def test_off_is_never_allowed(self):
        cfg = _installed_config(charge_mode="off", daily_ev_target=99)
        assert mode_allows_night_charging(cfg, cfg["ev_chargers"][0]) is False


class TestTheTwinsCannotDrift:
    """Both gates were hand-copies carrying a "keep in sync" note (#679)."""

    def _state_machine(self, cfg):
        from custom_components.solar_energy_management.coordinator.charging_control import (
            ChargingStateMachine,
        )
        sm = ChargingStateMachine.__new__(ChargingStateMachine)
        sm.hass = MagicMock()
        sm.config = cfg
        sm._night_enabled_cached = None
        sm._night_enabled_pending = None
        sm._night_enabled_pending_cycles = 0
        return sm

    def _coordinator(self, cfg):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord.config = cfg
        return coord

    @pytest.mark.parametrize(
        "overrides",
        [
            {},                                          # fresh install
            {"daily_ev_target": 1.5},                    # deliberate opt-in
            {"daily_ev_target": 0},                      # explicit zero
            {"ev_target_type": "soc"},                   # SOC, no floor
            {"ev_target_type": "soc", "ev_target_soc": 90},
            {"charge_mode": "min_plus_solar"},
            {"charge_mode": "off"},
        ],
    )
    def test_state_machine_and_coordinator_agree(self, overrides):
        cfg = _installed_config(**overrides)
        charger = cfg["ev_chargers"][0]
        assert (
            self._state_machine(cfg)._any_night_charging_enabled()
            is self._coordinator(cfg)._mode_allows_night_charging(charger)
        ), f"the two night gates disagree on {overrides}"


class TestFloorHelperIsTotal:
    """``solar_only_night_floor`` is consulted before any charging decision."""

    @pytest.mark.parametrize(
        "cfg", [None, {}, [], "nonsense", {"daily_ev_target": None},
                {"daily_ev_target": "not-a-number"},
                {"ev_target_type": "soc", "ev_target_soc": "?"}],
    )
    def test_unusable_config_reads_as_no_floor(self, cfg):
        """Never-grids is the safe answer, so garbage must fall that way."""
        assert solar_only_night_floor(cfg) == 0.0

    def test_a_string_number_is_honoured(self):
        """Options round-tripped through storage can arrive as strings."""
        assert solar_only_night_floor({"daily_ev_target": "2.5"}) == 2.5
