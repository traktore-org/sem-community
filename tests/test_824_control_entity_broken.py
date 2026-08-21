"""#824 — a control entity that never loaded must not be written to in silence.

@onkelfu's charging-current control did nothing for days. The cause was one
unsupported line in a template number::

    number:
      - name: wb_einfahrt_ladestrom
        mode: slider      # not valid here

HA refused to load the entity properly; it existed only as ``restored: true``.
SEM went on writing to it every cycle, believing it was steering the charger,
while nothing reached the wallbox.

The obvious hook is the wrong one. ``raise_charger_actuation_failed`` already
exists, but it fires from ``_record_actuation_failure(error: Exception)``
after three writes that RAISED — and his writes never raised. That is the
defining property of this bug class: **the failure produces no error**, so
anything built on exception handling keeps missing it.

Hence a pre-flight check on the entity SEM is about to depend on, and the
same Repair treatment a dead sensor already gets. A dead *sensor* makes
SEM's numbers look wrong, which people notice and report. A dead *control
entity* makes SEM look like it is working — commanded current on the
dashboard, a clean log — while the car does whatever it likes.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.control_entity import (
    CONTROL_ENTITY_DOMAINS,
    validate_control_entity,
)


def _states(mapping):
    return lambda eid: mapping.get(eid)


@pytest.mark.unit
class TestTheVerdict:

    def test_unconfigured_is_not_an_error(self):
        """Most chargers name no current entity at all — absence of a
        capability is not a fault."""
        v = validate_control_entity(None, _states({}))
        assert v.configured is None and v.valid is None and v.reason is None

    def test_a_live_entity_is_valid(self):
        v = validate_control_entity(
            "number.wb_ladestrom", _states({"number.wb_ladestrom": "8"}))
        assert v.valid is True and v.reason is None

    def test_a_restored_entity_is_broken(self):
        """THE case: the entity exists, HA reports it unavailable, and every
        write lands nowhere without raising."""
        v = validate_control_entity(
            "number.wb_ladestrom", _states({"number.wb_ladestrom": "unavailable"}))
        assert v.valid is False
        assert v.reason == "unavailable"

    def test_an_unknown_entity_is_broken(self):
        v = validate_control_entity(
            "number.wb_ladestrom", _states({"number.wb_ladestrom": "unknown"}))
        assert v.valid is False and v.reason == "unavailable"

    def test_a_missing_entity_is_broken(self):
        """Renamed upstream, or a typo in the config."""
        v = validate_control_entity("number.gone", _states({}))
        assert v.valid is False and v.reason == "missing"

    def test_the_wrong_domain_is_broken(self):
        """A sensor cannot be commanded. Naming one is a config error that
        should be visible immediately, not at the first charge attempt."""
        v = validate_control_entity(
            "sensor.wb_power", _states({"sensor.wb_power": "3400"}))
        assert v.valid is False and v.reason == "wrong_domain"

    def test_helper_twins_are_first_class(self):
        """input_number / input_boolean are what people build when their
        charger has no native control — the #804 lesson."""
        assert "input_number" in CONTROL_ENTITY_DOMAINS
        assert "input_boolean" in CONTROL_ENTITY_DOMAINS
        v = validate_control_entity(
            "input_number.ladestrom", _states({"input_number.ladestrom": "10"}))
        assert v.valid is True

    def test_it_is_pure(self):
        """Like #814's validator: no hass, no HA imports — so it can be
        tested exactly like this, and cannot actuate anything."""
        import inspect

        from custom_components.solar_energy_management.coordinator import (
            control_entity,
        )
        src = inspect.getsource(control_entity)
        assert "homeassistant" not in src, (
            "the validator reached into HA — it must stay pure and injectable"
        )


@pytest.mark.unit
class TestItBecomesVisible:

    def test_a_repair_exists_for_it(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "coordinator"
               / "repair_issues.py").read_text()
        assert "charger_control_entity_broken" in src, (
            "no Repair — the user would still have to instrument Modbus "
            "themselves to discover the writes are going nowhere"
        )

    def test_the_repair_is_translated_everywhere(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        missing = []
        for f in sorted((root / "translations").glob("*.json")):
            issues = json.loads(f.read_text(encoding="utf-8")).get("issues", {})
            if "charger_control_entity_broken" not in issues:
                missing.append(f.name)
        assert not missing, f"Repair has no translation in: {missing}"

    def test_the_coordinator_checks_the_charger_entities(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "coordinator"
               / "coordinator.py").read_text()
        assert "validate_control_entity" in src, (
            "nothing calls the validator, so it would never fire"
        )
        assert "_control_valid" in src, (
            "the per-charger verdict is not published beside "
            "charger_<id>_phase_switch_valid, so the card cannot show it"
        )

    def test_a_transient_flap_stays_quiet(self):
        """A restart's warm-up window must not file a Repair — the sensor
        Repair already learned this (#611 cries wolf)."""
        from custom_components.solar_energy_management.coordinator import (
            repair_issues,
        )
        assert repair_issues.UNAVAILABLE_REPAIR_THRESHOLD_S >= 300
