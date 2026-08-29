"""#642/#643 — one EV power read path.

#642: `_read_ev_fleet_power` is the ONE fleet+per-charger EV power read,
shared by the energy-dashboard and legacy read paths (the #616
`_read_ev_connection_status` precedent applied to its ev_power sibling —
which had already drifted: the legacy path smoothed the fleet SUM and never
populated `ev_power_per_charger`, so build_view's fleet fallback fed every
charger the whole fleet draw on legacy-path multi-charger installs).

#643: coordinator-side consumers read THIS charger's draw through
`_charger_power_w` (the cycle's smoothed per-charger dict, raw-entity
fallback with unit normalization) instead of hand-rolled
`hass.states.get(power_entity_id)` blocks — three sites plus a fourth
display-row site that had no kW rule at all.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock


from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)

REPO = Path(__file__).resolve().parent.parent
SENSOR_READER_PY = REPO / "coordinator" / "sensor_reader.py"
COORDINATOR_PY = REPO / "coordinator" / "coordinator.py"


def _mk_reader(states: dict):
    """A minimal SensorReader with stubbed hass + config."""
    r = SensorReader.__new__(SensorReader)
    r._ev_power_hist = {}
    r._raw_config = {
        "ev_chargers": [
            {"id": "c1", "ev_charging_power_sensor": "sensor.c1"},
            {"id": "c2", "ev_charging_power_sensor": "sensor.c2"},
        ]
    }
    r._read_sensor = lambda eid, kind, **kw: states.get(eid, 0.0)
    return r


class TestSharedFleetRead642:
    def test_helper_populates_dict_and_sum(self):
        r = _mk_reader({"sensor.c1": 4000.0, "sensor.c2": 7000.0})
        readings = PowerReadings()
        assert r._read_ev_fleet_power(readings, r._raw_config["ev_chargers"]) is True
        assert readings.ev_power_per_charger == {"c1": 4000.0, "c2": 7000.0}
        assert float(readings.ev_power) == 11000.0

    def test_helper_declines_without_nested_sensors(self):
        r = _mk_reader({})
        r._raw_config = {"ev_chargers": [{"id": "c1"}]}
        readings = PowerReadings()
        assert r._read_ev_fleet_power(readings, [{"id": "c1"}]) is False
        assert readings.ev_power_per_charger == {}
        # declining must leave the reading untouched for the caller's fallbacks
        assert float(readings.ev_power) == 0.0

    def test_per_charger_blip_is_filtered_per_cid(self):
        """A single-cycle 0-blip on ONE charger must not survive — the
        legacy path's fleet-sum median half-passed it."""
        vals = {"sensor.c1": 10000.0, "sensor.c2": 3000.0}
        r = _mk_reader(vals)
        chargers = r._raw_config["ev_chargers"]
        for _ in range(3):  # warm up both medians
            r._read_ev_fleet_power(PowerReadings(), chargers)
        vals["sensor.c1"] = 0.0  # the UDP blip
        readings = PowerReadings()
        r._read_ev_fleet_power(readings, chargers)
        assert readings.ev_power_per_charger["c1"] == 10000.0  # median holds
        assert float(readings.ev_power) == 13000.0

    def test_both_read_paths_call_the_one_helper(self):
        """Structural: neither path may keep its own copy of the block."""
        src = SENSOR_READER_PY.read_text()
        assert src.count("self._read_ev_fleet_power(") == 2, (
            "expected exactly two call sites (ED + legacy paths)"
        )
        # the drifted legacy shape (one smooth over the raw sum) must be gone
        assert "self._smooth_ev_power(total_ev)" not in src


class TestChargerPowerAccessor643:
    def _mk_coord(self):
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.hass = MagicMock()
        c._ev_devices = {}
        return c

    def test_prefers_smoothed_per_charger_dict(self):
        c = self._mk_coord()
        power = PowerReadings()
        power.ev_power_per_charger["c1"] = 10450.0
        # raw entity says 0 (the blip) — must be ignored
        c.hass.states.get.return_value = MagicMock(state="0")
        assert c._charger_power_w("c1", power) == 10450.0

    def test_raw_fallback_normalizes_kw_case_insensitive(self):
        c = self._mk_coord()
        st = MagicMock(state="7.4")
        st.attributes = {"unit_of_measurement": "kW"}
        c.hass.states.get.return_value = st
        dev = MagicMock(power_entity_id="sensor.raw")
        assert c._charger_power_w("c1", PowerReadings(), dev) == 7400.0
        st.attributes = {"unit_of_measurement": "KW"}
        assert c._charger_power_w("c1", PowerReadings(), dev) == 7400.0

    def test_power_none_uses_raw_fallback(self):
        # display paths outside the update cycle pass power=None
        c = self._mk_coord()
        st = MagicMock(state="3600")
        st.attributes = {"unit_of_measurement": "W"}
        c.hass.states.get.return_value = st
        dev = MagicMock(power_entity_id="sensor.raw")
        assert c._charger_power_w("c1", None, dev) == 3600.0

    def test_unavailable_reads_zero(self):
        c = self._mk_coord()
        c.hass.states.get.return_value = MagicMock(state="unavailable")
        dev = MagicMock(power_entity_id="sensor.raw")
        assert c._charger_power_w("c1", None, dev) == 0.0


class TestChargerPriorityRows643:
    """The display rows are the 4th site converted to the accessor — they run
    every cycle, so a name slip there is a per-cycle exception."""

    def _mk_coord(self):
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.hass = MagicMock()
        st = MagicMock(state="7.4")
        st.attributes = {"unit_of_measurement": "kW"}
        c.hass.states.get.return_value = st
        dev = MagicMock(
            power_entity_id="sensor.c1_power", name="Garage",
            priority=2, phases=3, voltage=230, max_current=32, min_current=6,
        )
        c._ev_devices = {"c1": dev}
        c._last_ev_connected_per_charger = {"c1": True}
        return c

    def test_rows_build_and_normalize_kw(self):
        rows = self._mk_coord()._charger_priority_rows()
        assert len(rows) == 1
        row = rows[0]
        assert row["power_entity"] == "sensor.c1_power"
        assert row["current_power_w"] == 7400.0  # kW normalized (was ~0 W)
        assert row["is_on"] is True
        assert row["connected"] is True


class TestNoInlinePowerEntityReads643:
    """AST lint (FLEET-READ style): no `hass.states.get(...power_entity_id...)`
    outside the sanctioned accessor in coordinator.py."""

    def test_no_raw_power_entity_state_reads(self):
        src = COORDINATOR_PY.read_text()
        tree = ast.parse(src)
        lines = src.splitlines()
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name == "_charger_power_w":
                continue  # the sanctioned accessor owns the raw fallback
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Attribute)
                    and sub.attr == "power_entity_id"
                    and isinstance(sub.ctx, ast.Load)
                ):
                    line = lines[sub.lineno - 1]
                    context = "\n".join(
                        lines[max(0, sub.lineno - 3): sub.lineno + 6]
                    )
                    # reads used only for existence checks / wiring are fine;
                    # feeding hass.states.get is the forbidden shape
                    if "states.get" in context:
                        offenders.append(f"{node.name}:{sub.lineno}: {line.strip()}")
        assert not offenders, (
            "raw power_entity_id state reads outside _charger_power_w "
            "(#643 class-3 accessor bypass):\n" + "\n".join(offenders)
        )
