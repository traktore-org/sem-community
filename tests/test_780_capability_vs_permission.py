"""#780 — two axes, two words: capability vs permission.

Two subsystems keep a row per appliance. ``LoadManager._devices`` carries a
flag called ``is_controllable``; the surplus list carries ``control_mode``
(``surplus`` / ``peak_only`` / ``off`` / ``manual``). The names suggest they
answer the same question. They do not:

* **capability** — is there anything to switch? (a control handle was
  discovered: ``control is not None``)
* **permission** — may SEM switch it, and under which policy? (``control_mode``
  plus the user's explicit "hands off this load" opt-out from #650)

``is_controllable`` was neither: it was capability AND-ed with half of
permission, under a name that reads as pure permission. In #779 the reporter's
diagnostics said ``is_controllable: true`` for a device he had set to
**Mode: Off** while SEM was switching it off. Capability true, permission off,
both correct — and it read exactly like the bug we were chasing. It cost real
diagnosis time on both sides. #650 is the earlier scar: it had to document why
``controllable_override=True`` is *not* the symmetric case of ``False``,
because "controllable" was being read as permission there too.

So the axes get their own names and their own accessors, in one module that
says what each one means (``features/device_axes.py``), and every consumer asks
the question it actually means:

    has_control_handle(row)   capability
    user_hands_off(row)       permission — the user's explicit opt-out
    may_actuate(row)          both, in one call: a handle AND permission

The legacy key stays readable for one release (a row written by an older
install, or by a code path not yet migrated, still answers correctly), which is
what most of these tests pin: the migration must not move a single decision.

The one decision that DOES move is named here too — the "how much can we shed?"
counters used to include ``control_mode: off`` devices that the shed loop would
never touch, over-reporting exactly the way #193/#649 said they must not.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.solar_energy_management.features.device_axes import (
    has_control_handle,
    may_actuate,
    user_hands_off,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDevice,
)
from custom_components.solar_energy_management.features.load_management import (
    LoadManagementCoordinator,
)


SWITCH_CONTROL = {"type": "switch", "entity": "switch.dishwasher"}


# --------------------------------------------------------------------------
# The dataclass: one property per axis, the mixed one kept as a legacy alias
# --------------------------------------------------------------------------
class TestUnifiedDeviceAxes780:

    def _dev(self, control=SWITCH_CONTROL, override=None):
        return UnifiedDevice(
            energy_sensor="sensor.spuelmaschine_energy",
            power_sensor="sensor.spuelmaschine_power",
            name="Spülmaschine",
            priority=5,
            control=control,
            controllable_override=override,
        )

    def test_capability_is_only_about_the_handle(self):
        """A hands-off device still HAS a handle — that's the whole point.

        Pre-#780 the opt-out was folded into the capability flag, so a device
        the user had said "never touch" reported as if SEM had found no way to
        control it at all. Two different facts, one bit.
        """
        assert self._dev(override=False).has_control_handle is True
        assert self._dev(override=None).has_control_handle is True
        assert self._dev(override=True).has_control_handle is True
        assert self._dev(control=None).has_control_handle is False

    def test_permission_is_only_about_the_user(self):
        assert self._dev(override=False).user_hands_off is True
        assert self._dev(override=None).user_hands_off is False
        # (#650) True is not the symmetric case — it clears back to derived,
        # it never invents a handle. So it is not an opt-out either.
        assert self._dev(override=True).user_hands_off is False

    def test_legacy_flag_answers_exactly_as_before(self):
        """The mixed flag survives one release, with its OLD truth table."""
        assert self._dev(override=None).is_controllable is True
        assert self._dev(override=False).is_controllable is False
        assert self._dev(control=None).is_controllable is False
        assert self._dev(control=None, override=True).is_controllable is False

    def test_to_dict_carries_both_axes_and_the_legacy_key(self):
        d = self._dev(override=False).to_dict()
        assert d["has_control_handle"] is True
        assert d["user_hands_off"] is True
        assert d["is_controllable"] is False


# --------------------------------------------------------------------------
# The accessors: read-new-then-legacy, so no row loses its answer
# --------------------------------------------------------------------------
class TestDeviceAxisAccessors780:

    def test_new_key_wins_when_present(self):
        assert has_control_handle({"has_control_handle": False}) is False
        assert has_control_handle({"has_control_handle": True}) is True

    def test_legacy_key_still_answers_capability(self):
        """A row written before the migration carries only the mixed key."""
        assert has_control_handle({"is_controllable": False}) is False
        assert has_control_handle({"is_controllable": True}) is True

    def test_unknown_row_is_assumed_controllable(self):
        """The historic default at every call site was ``True``."""
        assert has_control_handle({}) is True

    def test_hands_off_defaults_to_false(self):
        assert user_hands_off({}) is False
        assert user_hands_off({"user_hands_off": True}) is True
        assert user_hands_off({"is_controllable": False}) is False

    @pytest.mark.parametrize("legacy", [True, False])
    def test_legacy_row_decides_exactly_as_the_old_expression_did(self, legacy):
        """``may_actuate`` on a legacy-only row == the old ``is_controllable``.

        This is the equivalence the whole migration rests on: the old sites
        read ``device_info.get("is_controllable", True)``, so every legacy row
        must reach the same verdict through the new call.
        """
        row = {"is_controllable": legacy, "control_mode": "peak_only"}
        assert may_actuate(row) is legacy

    def test_both_axes_must_say_yes(self):
        assert may_actuate({"has_control_handle": True}) is True
        assert may_actuate({"has_control_handle": False}) is False
        assert may_actuate(
            {"has_control_handle": True, "user_hands_off": True}) is False
        # (#49) the mode is the other half of permission
        assert may_actuate(
            {"has_control_handle": True, "control_mode": "off"}) is False
        assert may_actuate(
            {"has_control_handle": True, "control_mode": "surplus"}) is True


# --------------------------------------------------------------------------
# The consumer that matters: the peak-shed loop
# --------------------------------------------------------------------------
@pytest.fixture
def lm780(mock_hass):
    entry = MagicMock()
    entry.entry_id = "entry_780"
    entry.data = {}
    entry.options = {
        "load_management_enabled": True,
        "target_peak_limit": 5.0,
        "warning_peak_level": 4.5,
        "emergency_peak_level": 6.0,
        "peak_hysteresis": 0.3,
    }
    with patch(
        "custom_components.solar_energy_management.features.load_management.LoadDeviceDiscovery"
    ) as MockDiscovery, patch(
        "custom_components.solar_energy_management.features.load_management.Store"
    ) as MockStore:
        discovery = MagicMock()
        discovery.discover_from_energy_dashboard = AsyncMock(return_value={})
        discovery.discover_controllable_devices = MagicMock(return_value={})
        discovery.get_device_current_state = MagicMock(
            return_value={"is_on": True, "current_power": 1000})
        discovery.turn_off_device = AsyncMock(return_value=True)
        MockDiscovery.return_value = discovery
        store = MagicMock()
        store.async_load = AsyncMock(return_value=None)
        store.async_save = AsyncMock()
        MockStore.return_value = store
        lm = LoadManagementCoordinator(mock_hass, entry)
        lm._store = store
        lm._device_discovery = discovery
        yield lm


def _row(**over):
    row = {
        "switch_entity": "switch.x",
        "power_entity": "sensor.x_power",
        "friendly_name": "X",
        "power_rating": 1.0,
        "is_available": True,
        "is_critical": False,
        "priority": 5,
        "control_mode": "peak_only",
        "control": SWITCH_CONTROL,
    }
    row.update(over)
    return row


class TestShedLoopReadsTheRightAxis780:

    def test_no_handle_is_not_sheddable_without_the_legacy_key(self, lm780):
        """A migrated row carries only the new key — it must still be heard."""
        lm780._devices = {"a": _row(has_control_handle=False)}
        assert lm780._get_devices_for_shedding() == []

    def test_hands_off_is_not_sheddable_even_with_a_handle(self, lm780):
        """#650's guarantee, now expressed on the axis it belongs to."""
        lm780._devices = {
            "a": _row(has_control_handle=True, user_hands_off=True)}
        assert lm780._get_devices_for_shedding() == []

    def test_a_plain_row_is_still_sheddable(self, lm780):
        lm780._devices = {"a": _row(has_control_handle=True)}
        assert [d for d, _ in lm780._get_devices_for_shedding()] == ["a"]

    def test_legacy_only_row_is_still_heard(self, lm780):
        lm780._devices = {"a": _row(is_controllable=False)}
        assert lm780._get_devices_for_shedding() == []

    @pytest.mark.asyncio
    async def test_emergency_shed_honours_the_new_keys(self, lm780):
        lm780._devices = {
            "keep": _row(has_control_handle=True, user_hands_off=True),
            "shed": _row(has_control_handle=True),
        }
        shed = []
        lm780._shed_device = AsyncMock(side_effect=lambda d, r: shed.append(d))
        lm780._last_grid_import_w = 5500.0  # (#896) the plan reads the meter
        await lm780._emergency_load_shedding()
        assert shed == ["shed"]

    def test_off_mode_devices_are_not_counted_as_sheddable(self, lm780):
        """The counters must match what shedding would actually target.

        ``_get_devices_for_shedding`` has skipped ``control_mode: off`` since
        #49, but the "how much can we shed?" counters never asked — so a user
        who set three loads to Off still saw them in ``controllable_devices``
        and their draw in ``available_load_reduction``. Same over-report
        #193/#649 fixed on the other exclusions.
        """
        lm780._devices = {
            "off": _row(has_control_handle=True, control_mode="off"),
            "on": _row(has_control_handle=True, control_mode="peak_only"),
        }
        data = lm780.get_load_management_data()
        assert data["controllable_devices"] == 1
        assert data["available_load_reduction"] == 1.0

    @pytest.mark.asyncio
    async def test_the_user_toggle_writes_permission_not_capability(self, lm780):
        """"Hands off" must not erase the discovered handle.

        Pre-#780 the priority card's toggle overwrote ``is_controllable``, so
        the row forgot that a switch had ever been found — and any consumer
        asking "can this even be controlled?" got the user's preference back.
        """
        lm780._devices = {"a": _row(has_control_handle=True)}
        await lm780.async_set_hands_off("a", True)
        assert lm780._devices["a"]["has_control_handle"] is True
        assert lm780._devices["a"]["user_hands_off"] is True
        # the legacy key stays derived, for readers that haven't migrated
        assert lm780._devices["a"]["is_controllable"] is False

        await lm780.async_set_hands_off("a", False)
        assert lm780._devices["a"]["user_hands_off"] is False
        assert lm780._devices["a"]["is_controllable"] is True


# --------------------------------------------------------------------------
# One row, two consumers: the registry derives, LoadManager reads
# --------------------------------------------------------------------------
class TestRegistrySyncCarriesBothAxes780:

    def test_sync_writes_both_axes_into_the_load_manager_row(self):
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry,
        )
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg.hass = MagicMock()
        reg._surplus_controller = None
        reg._service_registrations = {}
        reg._control_mode_overrides = {}
        reg._ev_charger_rows = []
        reg._discovery = None
        reg._load_manager = MagicMock()
        reg._load_manager._devices = {}
        reg._devices = [
            UnifiedDevice(
                energy_sensor="sensor.spuelmaschine_energy",
                power_sensor=None,
                name="Spülmaschine",
                priority=5,
                control=SWITCH_CONTROL,
                controllable_override=False,
            )
        ]
        reg._get_power_rating = MagicMock(return_value=1.0)
        reg._sync_to_load_manager()
        row = reg._load_manager._devices["energy_dashboard_spuelmaschine"]
        assert row["has_control_handle"] is True
        assert row["user_hands_off"] is True
        assert row["is_controllable"] is False


# --------------------------------------------------------------------------
# Step 3: the line that misled #779 answers its own question
# --------------------------------------------------------------------------
class TestDiagnosticsAnswerBothAxes780:

    @pytest.mark.asyncio
    async def test_diagnostics_row_names_both_axes_and_the_verdict(self):
        from custom_components.solar_energy_management import diagnostics

        coordinator = MagicMock()
        coordinator._load_manager.is_enabled.return_value = True
        coordinator._load_manager.get_load_management_data.return_value = {
            "devices": {
                "energy_dashboard_spuelmaschine": {
                    "device_type": "individual_device",
                    "has_control_handle": True,
                    "user_hands_off": False,
                    "control_mode": "off",
                    "is_critical": False,
                    "priority": 5,
                },
            },
        }
        row = diagnostics._load_manager_diagnostics(coordinator)["devices"][
            "energy_dashboard_spuelmaschine"]
        # capability and permission, side by side — #779 saw only the first,
        # under a name that reads like the second.
        assert row["has_control_handle"] is True
        assert row["control_mode"] == "off"
        assert row["user_hands_off"] is False
        # and the one-line answer to "would SEM touch this?"
        assert row["may_actuate"] is False


# --------------------------------------------------------------------------
# The ratchet: the shed loop may never go back to reading the mixed key
# --------------------------------------------------------------------------
class TestNoRedriftToTheMixedKey780:

    def test_load_management_asks_only_through_the_axis_module(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent
               / "features" / "load_management.py").read_text()
        offenders = [
            line.strip()
            for line in src.splitlines()
            if '"is_controllable"' in line
            and not line.strip().startswith("#")
            # the one sanctioned write: the derived legacy key, for readers
            # that have not migrated yet
            and "# LEGACY-WRITE" not in line
        ]
        assert offenders == [], (
            "load_management must ask device_axes, not the mixed key: "
            + "; ".join(offenders)
        )

    def test_the_card_reads_the_capability_key(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "dashboard" / "card"
               / "src" / "cards" / "sem-load-priority-card.js").read_text()
        assert "has_control_handle" in src
