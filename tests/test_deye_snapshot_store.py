"""Production Deye snapshot-store + coordinator wiring (#709).

PR #709 ships ``DeyeBatteryAdapter`` with a fully implemented transactional
snapshot/restore protocol, but the *production* persistent store and the
coordinator runtime-injection that connects the adapter to a real
Home Assistant ``Store`` were missing — the contract only ran against an
in-memory stand-in in tests.

This module locks in the first production slice:

- ``DeyeSnapshotStore`` wraps Home Assistant's persistent ``Store`` and
  implements the exact interface the adapter already talks to
  (``async_save`` / ``async_load`` / ``async_clear`` / ``async_set_unsafe``
  plus the ``unsafe`` property). It is scope-safe: the underlying Store key
  embeds ``config_entry_id`` + ``battery_id`` so two batteries / two entries
  never share data, and the runtime store object is never serialised into
  entry ``data``/``options`` — it is attached to the adapter only.
- ``SEMCoordinator._battery_adapter_context`` injects the store plus the
  ``config_entry_id`` and ``battery_id`` when the Deye adapter is built by
  the real coordinator wiring, without touching other brands (no drift).
- Startup recovery of a pending snapshot runs fail-closed: a corrupt
  persisted snapshot never reaches the inverter (no service writes) and
  latches unsafe; a valid pending snapshot is restored and cleared.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.battery_adapters import (
    DeyeBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.deye_snapshot_store import (
    DeyeSnapshotStore,
    _snapshot_store_key,
    _unsafe_store_key,
)


# ─────────────────────────── fake HA Store ───────────────────────────

# Shared per-key backend so a "restart" (a NEW DeyeSnapshotStore scoped to
# the same entry+battery → the same Store key) actually observes the data
# written by an earlier instance — exactly what Home Assistant's persistent
# Store does across coordinator restarts. Keyed by the Store ``key``, so two
# different scopes never alias each other's snapshot or safety latch.
_FAKE_STORE_BACKEND: dict[str, dict] = {}


class _FakeHAStore:
    """In-memory stand-in for ``homeassistant.helpers.storage.Store``.

    Data is shared across Store instances that carry the same ``key`` (i.e.
    the same config-entry/battery scope), simulating disk persistence across
    a coordinator restart. ``async_remove`` clears only this store's key.
    """

    def __init__(self, hass, version, key):
        self.hass = hass
        self.version = version
        self.key = key
        self.data = _FAKE_STORE_BACKEND.setdefault(key, {"_data": None})

    async def async_load(self):
        return self.data["_data"]

    async def async_save(self, data):
        self.data["_data"] = data

    async def async_remove(self):
        self.data["_data"] = None


@pytest.fixture
def fake_store_class():
    with patch(
        "custom_components.solar_energy_management.coordinator."
        "battery_adapters.deye_snapshot_store.Store",
        _FakeHAStore,
    ) as _cls:
        # Fresh persistence backend per test — no leakage between tests.
        _FAKE_STORE_BACKEND.clear()
        yield _cls
        _FAKE_STORE_BACKEND.clear()


class _States:
    def __init__(self, values):
        self._values = values

    def get(self, entity_id):
        return self._values.get(entity_id)


def _state(value, *, age_s=1, **attributes):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        state=str(value),
        attributes=attributes,
        last_updated=now - timedelta(seconds=age_s),
        last_changed=now - timedelta(seconds=age_s),
    )


def _valid_deye_config():
    config = {
        "battery_charge_platform": "deye",
        "deye_grid_charge_switch": "switch.grid_charge",
        "deye_charge_current_entity": "number.grid_charge_current",
        "deye_battery_voltage_entity": "sensor.battery_voltage",
        "deye_battery_voltage_max_age_s": 60,
        "deye_max_charge_current_a": 25,
        "deye_bms_max_charge_current_a": 20,
        "deye_max_discharge_power": 5000,
        "deye_program_control": True,
        "deye_program_groups": [],
        "deye_observer_mode": False,
        "deye_actuation_enabled": True,
        "deye_readback_attempts": 1,
    }
    states = {
        "switch.grid_charge": _state("off"),
        "number.grid_charge_current": _state(
            0, unit_of_measurement="A", min=0, max=32
        ),
        "sensor.battery_voltage": _state(53.35),
    }
    program_times = ("01:00:00", "05:00:00", "09:00:00", "13:00:00", "17:00:00", "21:00:00")
    for index in range(1, 7):
        time_entity = f"time.program_{index}"
        soc_entity = f"number.program_{index}_soc"
        charge_entity = f"select.program_{index}_charging"
        config["deye_program_groups"].append(
            {"time": time_entity, "soc": soc_entity, "charge": charge_entity}
        )
        states[time_entity] = _state(program_times[index - 1])
        states[soc_entity] = _state(21, unit_of_measurement="%", min=0, max=100)
        states[charge_entity] = _state(
            "Disabled", options=["Disabled", "Grid", "Generator", "Both"]
        )
    return config, states


# ─────────────────────────── store unit tests ───────────────────────────

class TestDeyeSnapshotStore:
    async def test_save_load_round_trip_persists_dict(self, fake_store_class):
        store = DeyeSnapshotStore(MagicMock(), "entry-1", "battery-1")

        await store.async_save({"schema_version": 2, "value": 1})
        loaded = await store.async_load()

        assert loaded == {"schema_version": 2, "value": 1}

    async def test_clear_removes_persisted_snapshot(self, fake_store_class):
        store = DeyeSnapshotStore(MagicMock(), "entry-1", "battery-1")
        await store.async_save({"schema_version": 2})
        assert await store.async_load() == {"schema_version": 2}

        await store.async_clear()

        assert await store.async_load() is None

    async def test_set_unsafe_persists_and_updates_property(self, fake_store_class):
        store = DeyeSnapshotStore(MagicMock(), "entry-1", "battery-1")
        assert store.unsafe is False

        await store.async_set_unsafe(True)

        assert store.unsafe is True

    async def test_unsafe_latch_survives_restart_fail_closed(self, fake_store_class):
        store = DeyeSnapshotStore(MagicMock(), "entry-1", "battery-1")
        await store.async_set_unsafe(True)

        restarted = DeyeSnapshotStore(MagicMock(), "entry-1", "battery-1")
        await restarted.async_load_latch()

        assert restarted.unsafe is True

    async def test_corrupt_unsafe_latch_payload_fails_closed(self, fake_store_class):
        store = DeyeSnapshotStore(MagicMock(), "entry-1", "battery-1")
        await store._unsafe_store.async_save({"unsafe": 0})

        await store.async_load_latch()

        assert store.unsafe is True

    def test_scope_safe_keys_embed_config_entry_and_battery(self):
        a = _snapshot_store_key("entry-1", "battery-1")
        b = _snapshot_store_key("entry-1", "battery-2")
        c = _snapshot_store_key("entry-2", "battery-1")

        assert a != b
        assert a != c
        assert _unsafe_store_key("entry-1", "battery-1") != a

    def test_store_is_never_serialised_into_entry_data(self, fake_store_class):
        """The runtime store object must never leak into entry data/options."""
        store = DeyeSnapshotStore(MagicMock(), "entry-1", "battery-1")

        entry_data = {"deye_grid_charge_switch": "switch.grid_charge"}
        entry_data_serialisable = dict(entry_data)

        # The store is a runtime-only attachment; nothing in the entry
        # data/options may reference it. Assert it is not reachable.
        assert all(
            not isinstance(v, DeyeSnapshotStore) for v in entry_data_serialisable.values()
        )
        assert store not in entry_data_serialisable.values()


# ─────────────────────────── coordinator wiring ───────────────────────────

class TestCoordinatorWiring:
    def _coordinator(self, hass, config, entry_id="entry-deye-1"):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        coord = SEMCoordinator(MagicMock(), config)
        coord.hass = hass
        coord.config_entry = SimpleNamespace(entry_id=entry_id)
        return coord

    def _hass(self, states):
        hass = MagicMock()
        hass.states = _States(states)
        hass.services = SimpleNamespace(
            async_call=AsyncMock(return_value=None)
        )
        return hass

    def test_battery_adapter_context_injects_store_and_scope(self):
        config, states = _valid_deye_config()
        coord = self._coordinator(self._hass(states), config)

        pbc = coord._battery_adapter_context("battery-1")

        assert pbc["config_entry_id"] == "entry-deye-1"
        assert pbc["battery_id"] == "battery-1"
        assert isinstance(pbc["deye_snapshot_store"], DeyeSnapshotStore)
        assert pbc["deye_snapshot_store"].config_entry_id == "entry-deye-1"
        assert pbc["deye_snapshot_store"].battery_id == "battery-1"

    def test_real_wiring_gives_deye_adapter_full_snapshot_capability(self, fake_store_class):
        from custom_components.solar_energy_management.coordinator.battery_adapters import (
            adapter_for,
        )

        config, states = _valid_deye_config()
        hass = self._hass(states)
        coord = self._coordinator(hass, config)

        pbc = coord._battery_adapter_context("battery-1")
        adapter = adapter_for(hass, pbc)

        assert isinstance(adapter, DeyeBatteryAdapter)
        capability = adapter.capability()
        assert capability.available is True
        assert capability.snapshot_supported is True
        assert capability.readback_supported is True
        assert capability.restore_supported is True
        assert adapter._config_entry_id == "entry-deye-1"
        assert adapter._battery_id == "battery-1"

    def test_empty_config_entry_scope_keeps_deye_fail_closed(self):
        config, states = _valid_deye_config()
        coord = self._coordinator(self._hass(states), config)
        coord.config_entry = None

        context = coord._battery_adapter_context("primary")
        adapter = DeyeBatteryAdapter(coord.hass, context)

        assert context["config_entry_id"] == ""
        assert context["deye_snapshot_store"] is None
        assert adapter.supports_forced_charge is False

    def test_injection_is_deye_only_no_drift_for_other_brands(self, fake_store_class):
        from custom_components.solar_energy_management.coordinator.battery_adapters import (
            adapter_for,
        )

        config, states = _valid_deye_config()
        config["battery_charge_platform"] = "generic"
        config.pop("deye_observer_mode", None)
        config.pop("deye_actuation_enabled", None)
        hass = self._hass(states)
        coord = self._coordinator(hass, config)

        pbc = coord._battery_adapter_context("battery-1")
        adapter = adapter_for(hass, pbc)

        # Generic adapter must NOT carry a Deye store / Deye keys.
        assert not isinstance(adapter, DeyeBatteryAdapter)
        assert "deye_snapshot_store" not in vars(adapter)
        assert adapter._config_entry_id == "entry-deye-1"
        assert adapter._battery_id == "battery-1"

    async def test_run_battery_pipeline_builds_capable_deye(self, fake_store_class):
        """Drive the real pipeline once and inspect the cached adapter."""
        from custom_components.solar_energy_management.coordinator import (
            battery_adapters as ba_mod,
        )
        from custom_components.solar_energy_management.coordinator.actuate_battery import (
            actuate_battery,
        )
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryDecision,
            BatteryIntent,
        )
        from custom_components.solar_energy_management.coordinator.decide_battery import (
            decide_battery,
        )

        config, states = _valid_deye_config()
        hass = self._hass(states)
        coord = self._coordinator(hass, config)
        # Disable scheduler so the loop skips _maybe_run_scheduler_evaluation.
        # ``enabled`` is a read-only property backed by ``_config.enabled``
        # (SchedulerConfig dataclass field) — configure it, don't assign it.
        coord._battery_charge_scheduler._config.enabled = False
        # A MagicMock-backed hass can't drive the real TimeManager's solar
        # lookups — stub night-mode off so the pipeline's FleetContext builds.
        coord.time_manager = SimpleNamespace(is_night_mode=lambda: False)

        power = SimpleNamespace(
            batteries={},
            battery_soc=50.0,
            battery_power=-200.0,
            solar_power=500.0,
            home_consumption_power=300.0,
            ev_charging=False,
            ev_connected=False,
            battery_soc_unavailable=False,
        )
        energy = SimpleNamespace()

        with patch(
            "custom_components.solar_energy_management.coordinator.decide_battery.decide_battery",
            return_value=BatteryDecision(
                battery_id="primary",
                intent=BatteryIntent.NORMAL,
                reason="test",
            ),
        ), patch(
            "custom_components.solar_energy_management.coordinator.actuate_battery.actuate_battery",
            new=AsyncMock(),
        ):
            await coord._run_battery_pipeline(power, energy, "idle")

        adapter = coord._battery_adapters["primary"]
        assert isinstance(adapter, DeyeBatteryAdapter)
        assert adapter._snapshot_supported is True
        assert adapter._config_entry_id == "entry-deye-1"
        assert adapter._battery_id == "primary"

    # ─── startup recovery (#709): a NEW Deye adapter built by the real
    # coordinator must load the persisted safety latch and handle any
    # pending snapshot BEFORE the first actuation. These are behaviour tests
    # on the coordinator wiring (not the adapter's direct unit tests). ──────

    async def _run_pipeline(self, coord, *, decision):
        """Drive ``_run_battery_pipeline`` once with a canned decision."""
        from custom_components.solar_energy_management.coordinator.decide_battery import (
            decide_battery,
        )

        power = SimpleNamespace(
            batteries={},
            battery_soc=50.0,
            battery_power=-200.0,
            solar_power=500.0,
            home_consumption_power=300.0,
            ev_charging=False,
            ev_connected=False,
            battery_soc_unavailable=False,
        )
        with patch(
            "custom_components.solar_energy_management.coordinator.decide_battery.decide_battery",
            return_value=decision,
        ):
            await coord._run_battery_pipeline(power, SimpleNamespace(), "idle")

    async def test_new_deye_adapter_loads_persisted_unsafe_latch_fail_closed(
        self, fake_store_class
    ):
        """RED→GREEN: a persisted unsafe latch is honoured at startup.

        A previous run latched the scope unsafe. A NEW coordinator (e.g. after
        a restart) builds a fresh Deye adapter from the SAME persisted store.
        Without a startup recovery call, the in-memory latch defaults open and
        the adapter would happily force-charge. After recovery the adapter must
        come up latched-unsafe so actuation is fail-closed (no writes).
        """
        from custom_components.solar_energy_management.coordinator.battery_adapters.deye_snapshot_store import (
            DeyeSnapshotStore,
        )
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryDecision,
            BatteryIntent,
        )

        # Persist an unsafe latch for the SAME scope the coordinator will use
        # (config-entry "entry-deye-1" + single-battery fallback "primary").
        previous = DeyeSnapshotStore(MagicMock(), "entry-deye-1", "primary")
        await previous.async_set_unsafe(True)

        config, states = _valid_deye_config()
        coord = self._coordinator(self._hass(states), config)
        coord._battery_charge_scheduler._config.enabled = False
        coord.time_manager = SimpleNamespace(is_night_mode=lambda: False)

        await self._run_pipeline(
            coord,
            decision=BatteryDecision(
                battery_id="primary",
                intent=BatteryIntent.NORMAL,
                reason="test",
            ),
        )

        adapter = coord._battery_adapters["primary"]
        assert isinstance(adapter, DeyeBatteryAdapter)
        # Startup recovery must latch unsafe before any actuation…
        assert adapter.unsafe_latched is True
        # …so forced charge (and any snapshot replay) is fail-closed.
        assert adapter.supports_forced_charge is False

    async def test_new_deye_adapter_reloads_valid_pending_snapshot_before_actuation(
        self, fake_store_class
    ):
        """RED→GREEN: a valid pending snapshot is recovered by the new adapter.

        A previous run left a pending (un-cleared) snapshot. The coordinator
        builds a fresh Deye adapter that must load it — so a normal actuation
        restores the inverter to the pre-session state and clears the snapshot,
        instead of silently ignoring it and leaving the inverter in a
        force-charge state across the restart.
        """
        from custom_components.solar_energy_management.coordinator.battery_adapters.deye_snapshot_store import (
            DeyeSnapshotStore,
        )
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryDecision,
            BatteryIntent,
        )

        config, states = _valid_deye_config()
        # Build a pre-restart adapter against the shared backend, force-charge
        # once so a snapshot is persisted (mirrors the earlier unit test), then
        # throw the adapter away — only the persisted snapshot survives.
        previous_hass = self._hass(states)
        previous = DeyeBatteryAdapter(
            previous_hass,
            {
                **config,
                "config_entry_id": "entry-deye-1",
                "battery_id": "primary",
                "deye_observer_mode": False,
                "deye_actuation_enabled": True,
                "deye_readback_attempts": 1,
                "deye_snapshot_store": DeyeSnapshotStore(
                    previous_hass, "entry-deye-1", "primary"
                ),
            },
        )
        snapshot = await previous._take_snapshot("pre-restart-session")
        assert snapshot is not None
        del previous

        coord = self._coordinator(self._hass(states), config)
        coord._battery_charge_scheduler._config.enabled = False
        coord.time_manager = SimpleNamespace(is_night_mode=lambda: False)

        # NORMAL actuation should recover the pending snapshot (writes occur,
        # snapshot cleared) — NOT be a silent no-op.
        await self._run_pipeline(
            coord,
            decision=BatteryDecision(
                battery_id="primary",
                intent=BatteryIntent.NORMAL,
                reason="test",
            ),
        )

        adapter = coord._battery_adapters["primary"]
        assert isinstance(adapter, DeyeBatteryAdapter)
        assert adapter.last_intent is BatteryIntent.NORMAL
        assert adapter.unsafe_latched is False
        # The pending snapshot was restored and cleared by recovery.
        restored = DeyeSnapshotStore(MagicMock(), "entry-deye-1", "primary")
        assert await restored.async_load() is None

    async def test_corrupt_persisted_snapshot_fail_closed_zero_writes(
        self, fake_store_class
    ):
        """A corrupt persisted snapshot must latch unsafe and write nothing."""
        from custom_components.solar_energy_management.coordinator.battery_adapters.deye_snapshot_store import (
            DeyeSnapshotStore,
        )
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryDecision,
            BatteryIntent,
        )

        # Persist a corrupt payload (non-boolean grid_charge_enabled) for the
        # coordinator's scope.
        previous = DeyeSnapshotStore(MagicMock(), "entry-deye-1", "primary")
        await previous.async_save({"grid_charge_enabled": "false"})

        config, states = _valid_deye_config()
        hass = self._hass(states)
        coord = self._coordinator(hass, config)
        coord._battery_charge_scheduler._config.enabled = False
        coord.time_manager = SimpleNamespace(is_night_mode=lambda: False)

        await self._run_pipeline(
            coord,
            decision=BatteryDecision(
                battery_id="primary",
                intent=BatteryIntent.NORMAL,
                reason="test",
            ),
        )

        adapter = coord._battery_adapters["primary"]
        assert isinstance(adapter, DeyeBatteryAdapter)
        assert adapter.unsafe_latched is True
        assert adapter.supports_forced_charge is False
        # Zero HA service writes on the corrupt path.
        assert hass.services.async_call.await_count == 0
