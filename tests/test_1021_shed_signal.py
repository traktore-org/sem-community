"""#1021 — the grid operator's "reduce load" signal (§14a EnWG, ripple control)."""
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.shed_signal import (
    LEGAL_FLOOR_KW, ShedSignal, read_shed_signal,
)


def _S(state):
    return SimpleNamespace(state=state)


def _get(states):
    return lambda e: states.get(e)


class TestTheInput:
    def test_no_entity_is_inert(self):
        assert read_shed_signal(None, 4.2, _get({})) == ShedSignal(
            False, None, "none", None)

    def test_on_gives_the_cap(self):
        s = read_shed_signal("binary_sensor.relay", 4.2,
                             _get({"binary_sensor.relay": _S("on")}))
        assert s.active and s.cap_kw == 4.2 and s.state == "on"

    def test_off_is_off(self):
        s = read_shed_signal("binary_sensor.relay", 4.2,
                             _get({"binary_sensor.relay": _S("off")}))
        assert not s.active and s.cap_kw is None and s.state == "off"

    def test_cap_from_a_sensor(self):
        s = read_shed_signal("binary_sensor.relay", "sensor.lpc_kw",
                             _get({"binary_sensor.relay": _S("on"),
                                   "sensor.lpc_kw": _S("6.3")}))
        assert s.cap_kw == 6.3

    def test_a_numeric_string_is_a_number_not_an_entity(self):
        # options may store "5.5" as text — the dot must not make it an entity
        s = read_shed_signal("binary_sensor.relay", "5.5",
                             _get({"binary_sensor.relay": _S("on")}))
        assert s.cap_kw == 5.5

    def test_unreadable_cap_falls_back_to_the_legal_floor(self):
        s = read_shed_signal("binary_sensor.relay", "sensor.lpc_kw",
                             _get({"binary_sensor.relay": _S("on"),
                                   "sensor.lpc_kw": _S("unavailable")}))
        assert s.cap_kw == LEGAL_FLOOR_KW == 4.2

    def test_zero_or_missing_cap_falls_back_to_the_legal_floor(self):
        for limit in (0, None, -1, "", True):
            s = read_shed_signal("binary_sensor.relay", limit,
                                 _get({"binary_sensor.relay": _S("on")}))
            assert s.cap_kw == 4.2, limit

    def test_unavailable_signal_is_off_and_says_so(self):
        s = read_shed_signal("binary_sensor.relay", 4.2,
                             _get({"binary_sensor.relay": _S("unavailable")}))
        assert not s.active and s.state == "unavailable"

    def test_a_missing_entity_is_off_and_says_unknown(self):
        s = read_shed_signal("binary_sensor.gone", 4.2, _get({}))
        assert not s.active and s.state == "unknown"

    def test_input_boolean_true_reads_on(self):
        s = read_shed_signal("input_boolean.relay", 4.2,
                             _get({"input_boolean.relay": _S("on")}))
        assert s.active

    def test_the_reader_never_raises(self):
        def boom(_e):
            raise RuntimeError("state machine gone")
        s = read_shed_signal("binary_sensor.relay", 4.2, boom)
        assert not s.active and s.state == "unknown"
