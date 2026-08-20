"""#804 Phase A — observe-only phase model. Ships INERT (gate 4).

The estimate is the #716 measured-W/A idea made phase-aware: a charger's
real draw divided by its commanded amps is volts-actually-in-use, and
that over the per-phase voltage ≈ active phases. evcc needs a separate
GetPhases poll for this; the measurement is already in SEM's hands.

Phase A surfaces the estimate and validates the (new, optional)
``ev_phase_switch_entity`` capability the user names — it never writes
to it. Phases B-D (manual select / reactive auto / planner boundaries)
build on this observation layer.
"""

from custom_components.solar_energy_management.coordinator.ev_phases import (
    PHASE_MIN_AMPS, PHASE_MIN_WATTS, PHASE_SWITCH_DOMAINS,
    estimate_active_phases, validate_phase_switch_entity,
)


class TestEstimateActivePhases:

    def test_single_phase_zoe_at_20a(self):
        # Zoe R: 1-phase 20 A ≈ 4.6 kW → 4600/20/230 = 1.0
        assert estimate_active_phases(4600.0, 20, 230.0) == 1

    def test_three_phase_at_min_current(self):
        # 3-phase 6 A ≈ 4.14 kW → 4140/6/230 = 3.0
        assert estimate_active_phases(4140.0, 6, 230.0) == 3

    def test_two_phase_split(self):
        assert estimate_active_phases(2760.0, 6, 230.0) == 2

    def test_rounding_towards_the_nearest_phase(self):
        # A car pulling slightly under nameplate still reads its phases:
        # 10 A three-phase drawing 6.4 kW → 6400/10/230 = 2.78 → 3
        assert estimate_active_phases(6400.0, 10, 230.0) == 3

    def test_below_power_floor_is_unknown(self):
        # Ramp-up / trickle: not a measurement, no estimate.
        assert estimate_active_phases(300.0, 6, 230.0) is None

    def test_no_commanded_amps_is_unknown(self):
        assert estimate_active_phases(4600.0, 0, 230.0) is None

    def test_absurd_ratio_clamps_to_three(self):
        # A wrong amps reading must not invent a 5-phase charger.
        assert estimate_active_phases(7000.0, 6, 230.0) == 3

    def test_low_ratio_clamps_to_one(self):
        # Efficiency losses can pull W/A below one phase's volts.
        assert estimate_active_phases(1500.0, 10, 230.0) == 1

    def test_none_inputs_are_unknown(self):
        assert estimate_active_phases(None, 6, 230.0) is None
        assert estimate_active_phases(4600.0, None, 230.0) is None

    def test_zero_voltage_is_unknown_not_a_crash(self):
        assert estimate_active_phases(4600.0, 20, 0.0) is None


class TestValidatePhaseSwitchEntity:

    def _lookup(self, existing):
        return lambda eid: eid in existing

    def test_unconfigured_is_none_not_invalid(self):
        configured, valid = validate_phase_switch_entity(
            None, self._lookup(set()))
        assert configured is None
        assert valid is None

    def test_a_real_select_validates(self):
        configured, valid = validate_phase_switch_entity(
            "select.goe_psm", self._lookup({"select.goe_psm"}))
        assert configured == "select.goe_psm"
        assert valid is True

    def test_number_and_switch_domains_validate(self):
        for eid in ("number.keba_x2_phases", "switch.openwb_phases"):
            _, valid = validate_phase_switch_entity(
                eid, self._lookup({eid}))
            assert valid is True, eid

    def test_missing_entity_is_invalid(self):
        configured, valid = validate_phase_switch_entity(
            "select.goe_psm", self._lookup(set()))
        assert configured == "select.goe_psm"
        assert valid is False

    def test_wrong_domain_is_invalid(self):
        # A sensor can't perform a switch — naming one is a config error
        # worth surfacing, not silently accepting (evcc's #30143 lesson:
        # probe or declare, never infer — and validate the declaration).
        _, valid = validate_phase_switch_entity(
            "sensor.goe_phases", self._lookup({"sensor.goe_phases"}))
        assert valid is False

    def test_domains_are_the_actuator_trio(self):
        assert PHASE_SWITCH_DOMAINS == (
            "select", "number", "switch",
            "input_select", "input_number", "input_boolean")


class TestInertness:
    """Gate 4: Phase A observes. The module must be pure — no HA imports,
    no service calls, nothing that could actuate."""

    def test_module_is_pure(self):
        import ast, inspect
        from custom_components.solar_energy_management.coordinator import (
            ev_phases,
        )
        tree = ast.parse(inspect.getsource(ev_phases))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", "") or ""
                names = [a.name for a in node.names]
                for n in [mod] + names:
                    assert not n.startswith("homeassistant"), (
                        f"ev_phases must stay pure, imports {n}")

    def test_thresholds_exist_and_are_sane(self):
        assert PHASE_MIN_WATTS >= 400.0
        assert 1 <= PHASE_MIN_AMPS <= 6


class TestSwitchValuesAndCommand:
    """(Phase B) The mapped values per domain, and the one service call a
    switch turns into. select values are REQUIRED (option names are the
    device's own vocabulary — never guessed); number defaults to 1/3;
    switch defaults to off=1p / on=3p."""

    def test_number_defaults(self):
        from custom_components.solar_energy_management.coordinator.ev_phases import (
            resolve_switch_values,
        )
        v1, v3, ready = resolve_switch_values("number.keba_phases", {})
        assert (v1, v3, ready) == ("1", "3", True)

    def test_switch_defaults(self):
        from custom_components.solar_energy_management.coordinator.ev_phases import (
            resolve_switch_values,
        )
        v1, v3, ready = resolve_switch_values("switch.openwb_phases", {})
        assert (v1, v3, ready) == ("off", "on", True)

    def test_select_requires_named_options(self):
        from custom_components.solar_energy_management.coordinator.ev_phases import (
            resolve_switch_values,
        )
        _, _, ready = resolve_switch_values("select.goe_psm", {})
        assert ready is False
        v1, v3, ready = resolve_switch_values("select.goe_psm", {
            "ev_phase_switch_value_1p": "1 Phase",
            "ev_phase_switch_value_3p": "3 Phasen",
        })
        assert (v1, v3, ready) == ("1 Phase", "3 Phasen", True)

    def test_explicit_values_override_defaults(self):
        from custom_components.solar_energy_management.coordinator.ev_phases import (
            resolve_switch_values,
        )
        v1, v3, _ = resolve_switch_values("number.goe_psm", {
            "ev_phase_switch_value_1p": "1",
            "ev_phase_switch_value_3p": "2",   # go-e's psm: 2 means 3p
        })
        assert (v1, v3) == ("1", "2")

    def test_command_shapes(self):
        from custom_components.solar_energy_management.coordinator.ev_phases import (
            phase_switch_command,
        )
        assert phase_switch_command("select.goe_psm", "3 Phasen") == (
            "select", "select_option",
            {"entity_id": "select.goe_psm", "option": "3 Phasen"})
        assert phase_switch_command("number.keba_phases", "3") == (
            "number", "set_value",
            {"entity_id": "number.keba_phases", "value": 3.0})
        assert phase_switch_command("switch.openwb_phases", "on") == (
            "switch", "turn_on", {"entity_id": "switch.openwb_phases"})
        assert phase_switch_command("switch.openwb_phases", "off") == (
            "switch", "turn_off", {"entity_id": "switch.openwb_phases"})

    def test_unknown_domain_returns_none(self):
        from custom_components.solar_energy_management.coordinator.ev_phases import (
            phase_switch_command,
        )
        assert phase_switch_command("sensor.goe_phases", "3") is None


class TestHelperDomainTwins:
    """input_select / input_number / input_boolean are first-class switch
    targets — the natural path for users who proxy their wallbox control
    through a helper + automation (and the sim rig's mock vocabulary)."""

    def test_helper_domains_validate(self):
        from custom_components.solar_energy_management.coordinator.ev_phases import (
            validate_phase_switch_entity,
        )
        for eid in ("input_select.psm", "input_number.phases",
                    "input_boolean.three_phase"):
            _, valid = validate_phase_switch_entity(eid, lambda e: True)
            assert valid is True, eid

    def test_helper_values_and_commands(self):
        from custom_components.solar_energy_management.coordinator.ev_phases import (
            phase_switch_command, resolve_switch_values,
        )
        assert resolve_switch_values("input_number.phases", {}) == ("1", "3", True)
        assert resolve_switch_values("input_boolean.tp", {}) == ("off", "on", True)
        _, _, ready = resolve_switch_values("input_select.psm", {})
        assert ready is False
        assert phase_switch_command("input_select.psm", "3 Phasen") == (
            "input_select", "select_option",
            {"entity_id": "input_select.psm", "option": "3 Phasen"})
        assert phase_switch_command("input_number.phases", "3") == (
            "input_number", "set_value",
            {"entity_id": "input_number.phases", "value": 3.0})
        assert phase_switch_command("input_boolean.tp", "on") == (
            "input_boolean", "turn_on", {"entity_id": "input_boolean.tp"})
