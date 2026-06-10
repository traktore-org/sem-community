"""Storage-heal + writer-recovery tests for poisoned ``options.ev_chargers``.

Follow-up to #462/#464. The writer fixes (#467/#468/#469 + the beta.4
smart-merge fall-through) stopped NEW corruption of the options-side
charger list, but none of them repaired storage that earlier builds
(v1.7.2 .. v1.7.3-beta.3) had already corrupted:

* naive set_option full-replace from a stale Config-card cache could
  drop a sibling charger,
* the pre-#469 per-charger select/number writers could clobber the
  list to ``[]``,
* the setup-time auto-discovery reseed then planted a single
  ``id: "ev_charger"`` entry — permanently shadowing the data-side
  chargers via the ``{**data, **options}`` merge.

Once poisoned, a per-charger write for a missing id silently no-op'd
(the #469 ``or``-fallback only fires for missing/EMPTY lists, not
partial ones) — the "changing charger 2 does nothing" symptom.

Three layers under test here:

1. ``_heal_ev_chargers_options`` — pure setup-time reconcile that
   unions data + options by id (options fields win) and drops id-less
   ghost entries.
2. ``SEMPerChargerSelect`` / ``SEMPerChargerNumber`` — when the
   charger id is missing from the stored list, the write recovers the
   charger from ``entry.data`` and appends it (with a WARNING) instead
   of silently no-op'ing.
3. ``_merge_ev_chargers_by_id`` — id-less incoming entries are dropped
   (they'd otherwise become positional ghosts colliding with real
   siblings at registration).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription

from custom_components.solar_energy_management import (
    _heal_ev_chargers_options,
    _merge_ev_chargers_by_id,
)
from custom_components.solar_energy_management.number import SEMPerChargerNumber
from custom_components.solar_energy_management.select import SEMPerChargerSelect


TWO_CHARGERS_DATA = [
    {
        "id": "ev_charger",
        "name": "Laadpaal Links",
        "charge_mode": "solar_only",
        "ev_target_soc": 80,
        "vehicle_soc_entity": "sensor.audi_soc",
    },
    {
        "id": "ev_charger_1",
        "name": "Laadpaal Rechts",
        "charge_mode": "solar_plus_cheap",
        "ev_target_soc": 100,
        "vehicle_soc_entity": "sensor.cooper_soc",
    },
]


# ─────────────────────────────────────────────────────────────────
# 1. _heal_ev_chargers_options — the setup-time storage repair
# ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHealEvChargersOptions:
    def test_partial_options_restores_data_sibling(self):
        """The RienduPre shape: options has charger 1 only, data has both."""
        poisoned = [{"id": "ev_charger", "name": "Laadpaal Links",
                     "charge_mode": "always_max"}]
        healed = _heal_ev_chargers_options(TWO_CHARGERS_DATA, poisoned)
        assert healed is not None
        by_id = {c["id"]: c for c in healed}
        assert set(by_id) == {"ev_charger", "ev_charger_1"}
        # options-side field wins for the charger that was in options
        assert by_id["ev_charger"]["charge_mode"] == "always_max"
        # data-only fields of that charger are preserved (union, not replace)
        assert by_id["ev_charger"]["ev_target_soc"] == 80
        # the data-only sibling is restored verbatim
        assert by_id["ev_charger_1"]["charge_mode"] == "solar_plus_cheap"

    def test_empty_options_list_restores_all_data_chargers(self):
        """The pre-#469 ``[]`` clobber shape."""
        healed = _heal_ev_chargers_options(TWO_CHARGERS_DATA, [])
        assert healed is not None
        assert [c["id"] for c in healed] == ["ev_charger", "ev_charger_1"]

    def test_idless_ghost_entries_are_dropped(self):
        """Ghosts (Config-card ``newChargers[idx] = {}``) are removed."""
        poisoned = [
            {"id": "ev_charger", "charge_mode": "off"},
            {"ev_target_type": "soc"},  # ghost — no id
        ]
        healed = _heal_ev_chargers_options(TWO_CHARGERS_DATA, poisoned)
        assert healed is not None
        assert all(c.get("id") for c in healed)
        assert {c["id"] for c in healed} == {"ev_charger", "ev_charger_1"}

    def test_complete_options_list_is_left_alone(self):
        """Healthy storage → no write (returns None) so setup stays quiet."""
        complete = _heal_ev_chargers_options(TWO_CHARGERS_DATA, [])
        # one heal pass produces the stable union…
        assert complete is not None
        # …which a second pass recognises as already-healed
        assert _heal_ev_chargers_options(TWO_CHARGERS_DATA, complete) is None

    def test_options_only_charger_is_preserved(self):
        """A charger that exists only in options (added via flow) survives."""
        opts = [{"id": "ev_charger_2", "name": "Garage", "charge_mode": "off"}]
        healed = _heal_ev_chargers_options(TWO_CHARGERS_DATA, opts)
        assert healed is not None
        assert {c["id"] for c in healed} == {
            "ev_charger", "ev_charger_1", "ev_charger_2",
        }

    def test_no_data_side_chargers_is_noop_for_healthy_options(self):
        """Installs whose chargers live purely in options stay untouched."""
        opts = [dict(c) for c in TWO_CHARGERS_DATA]
        assert _heal_ev_chargers_options(None, opts) is None


# ─────────────────────────────────────────────────────────────────
# 2. Per-charger writers recover a charger missing from the stored list
# ─────────────────────────────────────────────────────────────────


def _mock_coordinator(config: dict) -> MagicMock:
    coord = MagicMock()
    coord.last_update_success = True
    coord.config = config
    coord.device_info = {"identifiers": {("solar_energy_management", "test")}}
    return coord


def _mock_entry(data: dict, options: dict) -> MagicMock:
    entry = MagicMock()
    entry.data = data
    entry.options = options
    entry.entry_id = "test_entry_poisoned"
    return entry


def _poisoned_fixtures():
    """data has both chargers; options has charger 1 ONLY (poisoned)."""
    data = {"ev_chargers": [dict(c) for c in TWO_CHARGERS_DATA]}
    options = {"ev_chargers": [
        {"id": "ev_charger", "name": "Laadpaal Links", "charge_mode": "always_max"},
    ]}
    coord = _mock_coordinator({**data, **options})
    entry = _mock_entry(data, options)
    return coord, entry


@pytest.mark.unit
class TestPerChargerWriterRecovery:
    @pytest.mark.asyncio
    async def test_select_write_recovers_charger_missing_from_options(self, caplog):
        """#462/#464: charger 2's mode flip must land even when its id is
        missing from a non-empty ``options.ev_chargers`` list."""
        coord, entry = _poisoned_fixtures()
        desc = SelectEntityDescription(
            key="charger_ev_charger_1_charge_mode",
            options=["solar_only", "min_plus_solar", "always_max", "off"],
        )
        sel = SEMPerChargerSelect(
            coord, desc, entry, "ev_charger_1", "charge_mode", "solar_plus_cheap",
        )
        sel.hass = coord.hass = MagicMock()
        sel.async_write_ha_state = MagicMock()

        await sel.async_select_option("off")

        sel.hass.config_entries.async_update_entry.assert_called_once()
        new_options = sel.hass.config_entries.async_update_entry.call_args[1]["options"]
        by_id = {c["id"]: c for c in new_options["ev_chargers"]}
        # the write landed — recovered from entry.data, not silently dropped
        assert by_id["ev_charger_1"]["charge_mode"] == "off"
        # recovery pulled the full data-side dict, not a bare stub
        assert by_id["ev_charger_1"]["vehicle_soc_entity"] == "sensor.cooper_soc"
        # the sibling that WAS in options is untouched
        assert by_id["ev_charger"]["charge_mode"] == "always_max"
        # the runtime config mirror sees the recovered charger too
        runtime_by_id = {
            c["id"]: c for c in coord.config["ev_chargers"]
        }
        assert runtime_by_id["ev_charger_1"]["charge_mode"] == "off"
        # never silent: the anomaly is logged
        assert "missing from the stored ev_chargers list" in caplog.text

    @pytest.mark.asyncio
    async def test_number_write_recovers_charger_missing_from_options(self, caplog):
        coord, entry = _poisoned_fixtures()
        desc = NumberEntityDescription(key="charger_ev_charger_1_target_soc")
        num = SEMPerChargerNumber(
            coord, desc, entry, "ev_charger_1", "ev_target_soc", 100,
        )
        num.hass = coord.hass = MagicMock()
        num.async_write_ha_state = MagicMock()

        await num.async_set_native_value(80.0)

        num.hass.config_entries.async_update_entry.assert_called_once()
        new_options = num.hass.config_entries.async_update_entry.call_args[1]["options"]
        by_id = {c["id"]: c for c in new_options["ev_chargers"]}
        assert by_id["ev_charger_1"]["ev_target_soc"] == 80.0
        assert by_id["ev_charger"]["charge_mode"] == "always_max"
        assert "missing from the stored ev_chargers list" in caplog.text

    @pytest.mark.asyncio
    async def test_time_write_recovers_charger_missing_from_options(self, caplog):
        """time.py was missed by the original #469 patch round — it still
        clobbered ev_chargers to [] when options lacked the key and silently
        no-op'd on a partial list. Same contract as select/number now."""
        from datetime import time as dt_time
        from homeassistant.components.time import TimeEntityDescription
        from custom_components.solar_energy_management.time import SEMPerChargerTime

        coord, entry = _poisoned_fixtures()
        desc = TimeEntityDescription(key="charger_ev_charger_1_target_time")
        ent = SEMPerChargerTime(
            coord, desc, entry, "ev_charger_1", "ev_target_time", "07:00",
        )
        ent.hass = coord.hass = MagicMock()
        ent.async_write_ha_state = MagicMock()

        await ent.async_set_value(dt_time(6, 30))

        new_options = ent.hass.config_entries.async_update_entry.call_args[1]["options"]
        by_id = {c["id"]: c for c in new_options["ev_chargers"]}
        assert by_id["ev_charger_1"]["ev_target_time"] == "06:30"
        assert by_id["ev_charger"]["charge_mode"] == "always_max"
        assert "missing from the stored ev_chargers list" in caplog.text

    @pytest.mark.asyncio
    async def test_time_write_falls_back_to_entry_data(self):
        """Options without the ev_chargers key must not be clobbered to []."""
        from datetime import time as dt_time
        from homeassistant.components.time import TimeEntityDescription
        from custom_components.solar_energy_management.time import SEMPerChargerTime

        data = {"ev_chargers": [dict(c) for c in TWO_CHARGERS_DATA]}
        coord = _mock_coordinator(dict(data))
        entry = _mock_entry(data, {})
        desc = TimeEntityDescription(key="charger_ev_charger_target_time")
        ent = SEMPerChargerTime(
            coord, desc, entry, "ev_charger", "ev_target_time", "07:00",
        )
        ent.hass = coord.hass = MagicMock()
        ent.async_write_ha_state = MagicMock()

        await ent.async_set_value(dt_time(5, 45))

        new_options = ent.hass.config_entries.async_update_entry.call_args[1]["options"]
        by_id = {c["id"]: c for c in new_options["ev_chargers"]}
        # both chargers survived the write — no [] clobber
        assert set(by_id) == {"ev_charger", "ev_charger_1"}
        assert by_id["ev_charger"]["ev_target_time"] == "05:45"

    @pytest.mark.asyncio
    async def test_select_write_unknown_charger_creates_stub(self):
        """Charger missing from BOTH sides still persists the write under a
        minimal ``{"id": ...}`` stub rather than vanishing."""
        coord, entry = _poisoned_fixtures()
        entry.data = {"ev_chargers": []}
        desc = SelectEntityDescription(
            key="charger_ev_charger_9_charge_mode",
            options=["solar_only", "off"],
        )
        sel = SEMPerChargerSelect(
            coord, desc, entry, "ev_charger_9", "charge_mode", "solar_only",
        )
        sel.hass = coord.hass = MagicMock()
        sel.async_write_ha_state = MagicMock()

        await sel.async_select_option("off")

        new_options = sel.hass.config_entries.async_update_entry.call_args[1]["options"]
        by_id = {c["id"]: c for c in new_options["ev_chargers"]}
        assert by_id["ev_charger_9"] == {"id": "ev_charger_9", "charge_mode": "off"}


# ─────────────────────────────────────────────────────────────────
# 3. _merge_ev_chargers_by_id drops id-less ghosts
# ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestMergeDropsGhosts:
    def test_incoming_without_id_is_dropped(self):
        existing = [{"id": "A", "charge_mode": "off"}]
        incoming = [{"name": "Stray", "charge_mode": "solar_only"}]
        result = _merge_ev_chargers_by_id(existing, incoming)
        assert result == [{"id": "A", "charge_mode": "off"}]

    def test_ghost_drop_keeps_valid_incoming_entries(self):
        existing = [{"id": "A", "charge_mode": "off"}]
        incoming = [
            {"ev_target_type": "soc"},          # ghost
            {"id": "A", "charge_mode": "always_max"},
            {"id": "B", "name": "New"},
        ]
        result = _merge_ev_chargers_by_id(existing, incoming)
        assert {c["id"] for c in result} == {"A", "B"}
        assert next(c for c in result if c["id"] == "A")["charge_mode"] == "always_max"
