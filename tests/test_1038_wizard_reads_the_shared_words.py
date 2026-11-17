"""#1038 — the setup wizard must judge a status sensor with the reader's words.

Found by loading Home Assistant's own Ohme test data (HA 2026.8.2): Ohme's
status sensor reports ``plugged_in``, ``finished`` and ``pending_approval``.
The reader knows all three (``status_enum.py``), but the wizard's check
(``EVChargerDetector._validate_entity``) kept its own word list. That list
had ``"plugged in"`` — the label HA shows — never the state HA stores, so
``validate_ev_configuration`` refused the sensor and the user could not
finish setup or reconfigure while the car sat plugged in.

The same copy had Peblar as ``"no ev connected"``; core stores
``no_ev_connected``, and ``suspended`` for a car plugged in but paused —
a word neither list knew, so the reader also read that car as gone.

Bug class 46 shape (c), the third copy of one vocabulary (#833 removed the
reader's two). The option lists below are core's own, cited per brand.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management import hardware_detection as hd
from custom_components.solar_energy_management.coordinator.charger_adapters import (
    status_enum as se,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)

# Core's ENUM options, as HA stores them (state = option key, never label).
# Ohme: ohme ChargerStatus, rig snapshot HA 2026.8.2 (sensor.ohme_home_pro_status).
OHME = ["unplugged", "pending_approval", "charging", "plugged_in", "paused",
        "finished"]
# Peblar: peblar/const.py PEBLAR_CP_STATE_TO_HOME_ASSISTANT (cp_state).
PEBLAR = ["suspended", "charging", "error", "fault", "invalid",
          "no_ev_connected"]
# NRGkick: rig snapshot HA 2026.8.2 (sensor.nrgkick_test_status) — SEM's
# own nrgkick row binds this sensor as ev_charging_sensor.
NRGKICK = ["standby", "connected", "charging", "error", "wakeup"]
# Blue Current: blue_current/sensor.py — SEM's pattern binds vehicle_status
# as ev_connected and activity as ev_charging.
BLUE_CURRENT_VEHICLE = ["standby", "vehicle_detected", "ready", "no_power",
                        "vehicle_error"]
BLUE_CURRENT_ACTIVITY = ["available", "charging", "unavailable", "error",
                         "offline"]
# Tesla Wall Connector: tesla_wall_connector/sensor.py (status).
TESLA_WC = ["booting", "not_connected", "connected", "ready", "negotiating",
            "error", "charging_finished", "waiting_car", "charging_reduced",
            "charging"]

STATUS = "sensor.charger_status"
POWER = "sensor.charger_power"


def _detector(state, options=None):
    attrs = {"options": options} if options is not None else {}
    st = SimpleNamespace(state=state, attributes=attrs)
    pw = SimpleNamespace(state="0", attributes={"unit_of_measurement": "W"})
    hass = MagicMock()
    hass.states.get = lambda eid: {STATUS: st, POWER: pw}.get(eid)
    with patch.object(hd, "entity_registry"):
        return hd.EVChargerDetector(hass)


def _wizard_errors(state, options=None):
    """What the setup and reconfigure forms say on submit."""
    return _detector(state, options).validate_ev_configuration({
        "ev_connected_sensor": STATUS,
        "ev_charging_sensor": STATUS,
        "ev_charging_power_sensor": POWER,
    })


def _accepts(state, options=None, role="ev_connected"):
    return _detector(state, options)._validate_entity(STATUS, role)


def _reader(state):
    hass = MagicMock()
    hass.states.get = lambda eid: (SimpleNamespace(state=state, attributes={})
                                   if eid == STATUS else None)
    r = SensorReader(hass, {"ev_connected_sensor": STATUS})
    r._sign_vote_warmup = 0
    return r


def _plugged(state):
    return _reader(state)._read_binary_sensor(STATUS, "ev_plug")


def _charging(state):
    return _reader(state)._read_binary_sensor(STATUS, "ev_charging")


class TestTheReportedCase:
    """Ohme's status sensor, in every state core lists."""

    @pytest.mark.parametrize("state", OHME)
    def test_the_form_takes_ohme_in_every_state(self, state):
        assert _wizard_errors(state, OHME) == {}, (
            f"Ohme at {state!r}: the wizard refuses a sensor the reader knows")

    @pytest.mark.parametrize("state", OHME)
    def test_every_ohme_state_is_a_word_the_reader_knows(self, state):
        # without the options attribute: the word list alone must know it
        assert _wizard_errors(state) == {}
        assert se.classify_charger_status(state) != "unknown"

    def test_plugged_in_reads_as_a_car_that_is_not_charging(self):
        assert _plugged("plugged_in") is True
        assert _charging("plugged_in") is False


class TestPeblarStoresTheKeyNotTheLabel:
    """The wizard's copy spelled Peblar ``no ev connected``; core stores
    ``no_ev_connected``. ``suspended`` (a car plugged in, paused) was in
    neither list, so the reader read that car as gone."""

    @pytest.mark.parametrize("state", PEBLAR)
    def test_the_form_takes_peblar_in_every_state(self, state):
        assert _wizard_errors(state, PEBLAR) == {}

    @pytest.mark.parametrize("state", ["suspended", "charging",
                                       "no_ev_connected"])
    def test_the_states_with_a_meaning_are_words_the_reader_knows(self, state):
        assert _wizard_errors(state) == {}

    def test_suspended_is_a_car_that_is_plugged_in(self):
        assert _plugged("suspended") is True
        assert _charging("suspended") is False

    def test_no_ev_connected_is_an_empty_bay(self):
        assert _plugged("no_ev_connected") is False
        assert _charging("no_ev_connected") is False

    def test_charging_is_plugged_and_charging(self):
        assert _plugged("charging") is True
        assert _charging("charging") is True

    @pytest.mark.parametrize("state,expected", [
        ("suspended", False),       # the status wins over a lagging 3 kW
        ("charging", True),
        ("no_ev_connected", False),
        ("error", True),            # unknown: the power fallback, as before
    ])
    def test_the_adapter_reads_peblar_status(self, state, expected):
        from custom_components.solar_energy_management.coordinator.charger_adapters import (
            GenericAdapter,
        )
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerPower,
        )
        dev = MagicMock()
        dev.charging_status_entity = STATUS
        dev.hass.states.get = lambda eid: (SimpleNamespace(state=state)
                                           if eid == STATUS else None)
        a = GenericAdapter(dev)
        assert a.actual_charging(
            ChargerPower(charger_id="peblar", power_w=3000.0)) is expected
        assert a._status_class() != "locked"

    @pytest.mark.parametrize("state", ["error", "fault", "invalid"])
    def test_a_fault_says_nothing_about_the_cable(self, state):
        # unknown on purpose: the reader falls back, as before
        assert se.classify_charger_status(state) == "unknown"
        assert se.is_cable_present(state) is None


class TestASensorIsJudgedByTheOptionsItLists:
    """A sensor caught at setup in a state with no control meaning (a
    fault, a boot) is still the right sensor when its listed options let
    the reader answer yes AND no for the role."""

    @pytest.mark.parametrize("options", [OHME, PEBLAR, TESLA_WC],
                             ids=["ohme", "peblar", "tesla_wall_connector"])
    @pytest.mark.parametrize("role", ["ev_connected", "ev_charging"])
    def test_a_full_vocabulary_passes_in_every_state(self, options, role):
        refused = [s for s in options if not _accepts(s, options, role)]
        assert refused == [], f"the wizard refuses {refused}"

    @pytest.mark.parametrize("options", [
        NRGKICK, BLUE_CURRENT_ACTIVITY, TESLA_WC,
    ], ids=["nrgkick", "blue_current_activity", "tesla_wall_connector"])
    def test_a_charging_status_passes_in_every_state(self, options):
        # NRGkick's status and Blue Current's activity are what SEM binds
        # as the charging sensor
        refused = [s for s in options if s != "unavailable"
                   and not _accepts(s, options, "ev_charging")]
        assert refused == [], f"the wizard refuses {refused}"

    def test_the_options_carry_it_not_the_state(self):
        # the proof that the options are read: the same state on a sensor
        # that lists nothing is refused
        assert _accepts("wakeup", NRGKICK, "ev_charging") is True
        assert _accepts("wakeup", None, "ev_charging") is False

    def test_one_known_word_is_not_enough(self):
        # Blue Current vehicle_status lists "ready" but SEM cannot read
        # "vehicle_detected" as plugged or not: refused, as before
        assert _accepts("vehicle_detected", BLUE_CURRENT_VEHICLE,
                        "ev_connected") is False
        assert _accepts("standby", BLUE_CURRENT_VEHICLE, "ev_connected") is False
        # nor is it a charging sensor: it lists no charging word
        assert _accepts("vehicle_detected", BLUE_CURRENT_VEHICLE,
                        "ev_charging") is False

    def test_a_plug_sensor_must_list_a_car_and_no_car(self):
        assert _accepts("x", ["unplugged", "x"], "ev_connected") is False
        assert _accepts("x", ["plugged_in", "x"], "ev_connected") is False
        assert _accepts("x", ["plugged_in", "unplugged", "x"],
                        "ev_connected") is True

    def test_a_charging_sensor_must_list_charging_and_not_charging(self):
        assert _accepts("wakeup", ["charging", "wakeup", "standby"],
                        "ev_charging") is False
        assert _accepts("wakeup", ["connected", "wakeup"], "ev_charging") is False
        assert _accepts("wakeup", ["charging", "connected", "wakeup"],
                        "ev_charging") is True

    @pytest.mark.parametrize("options", [
        # Peblar charge_current_limit_source, NRGkick cellular_mode: ENUM
        # sensors of a charger that are not its status
        ["charging_cable", "current_limiter", "solar_charging"],
        ["no_service", "gsm", "lte_cat_m1", "lte_nb_iot"],
    ])
    @pytest.mark.parametrize("role", ["ev_connected", "ev_charging"])
    def test_a_list_with_no_status_word_is_still_refused(self, options, role):
        assert _accepts(options[0], options, role) is False

    def test_unavailable_is_refused_whatever_it_lists(self):
        assert _accepts("unavailable", BLUE_CURRENT_ACTIVITY, "ev_charging") is False

    @pytest.mark.parametrize("options", ["charging, paused", {"x": 1}, 7])
    def test_options_that_are_not_a_list_are_refused(self, options):
        assert _accepts("wakeup", options) is False


class TestTheWizardAndTheReaderAgree:
    """Every word the reader knows passes the wizard, for both roles; a word
    the reader cannot read does not."""

    WORDS = sorted(se._CHARGING | se._NOT_CHARGING | se._LOCKED)

    @pytest.mark.parametrize("role", ["ev_connected", "ev_charging"])
    def test_every_known_word_passes(self, role):
        refused = [w for w in self.WORDS if not _accepts(w, role=role)]
        assert refused == [], f"the wizard refuses words the reader knows: {refused}"

    @pytest.mark.parametrize("state", ["on", "off", "ON", "Paused", "0", "1"])
    def test_binary_states_pass(self, state):
        assert _accepts(state) is True

    @pytest.mark.parametrize("state", ["230.4", "1534.2", "3", "7.4"])
    def test_any_other_number_is_not_a_plug(self, state):
        # the reader would read it as on (> 0): a voltage or an energy
        # total picked by mistake would show a car plugged in all the time
        assert _accepts(state) is False
        assert _plugged(state) is True

    @pytest.mark.parametrize("state", ["Faulted", "Error", "fault"])
    def test_a_box_caught_in_a_fault_passes_on_a_plain_sensor(self, state):
        # OCPP "Faulted" and Wallbox "Error" are plain sensors, no options:
        # the old list took them, and reconfigure must still save
        assert _wizard_errors(state) == {}
        # and they still mean nothing to the reader
        assert se.classify_charger_status(state) == "unknown"
        assert se.is_cable_present(state) is None
        assert _plugged(state) is False

    @pytest.mark.parametrize("state", ["C2", "b1", "A", "f"])
    def test_a_bare_pilot_code_still_passes(self, state):
        # the old list took them; ABL eMH1 (#808) may store them. Never
        # mapped: the reader falls back, as before
        assert _wizard_errors(state) == {}
        assert se.classify_charger_status(state) == "unknown"
        assert _plugged(state) is False

    def test_tesla_not_connected_is_an_empty_bay(self):
        assert _wizard_errors("not_connected") == {}
        assert _plugged("not_connected") is False
        assert _charging("not_connected") is False

    @pytest.mark.parametrize("state", ["maybe", "idle", "true", "nan",
                                       "no ev connected", "firmware 1.2.3"])
    def test_a_word_the_reader_cannot_read_is_refused(self, state):
        assert se.classify_charger_status(state) == "unknown"
        assert _accepts(state) is False

    def test_the_extra_sets_never_collide_with_a_class(self):
        classes = se._CHARGING | se._NOT_CHARGING | se._LOCKED
        assert se._FAULT.isdisjoint(classes)
        assert se._IEC_PILOT.isdisjoint(classes)

    def test_the_power_role_keeps_its_own_check(self):
        det = _detector("plugged_in")
        assert det._validate_entity(POWER, "ev_charging_power") is True


def _status_word_lists(tree):
    """Every tuple/list/set literal, and every dict's keys, holding two or
    more status words — unless they are only a bare on/off pair."""
    found = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.Tuple, ast.List, ast.Set)):
            elts = n.elts
        elif isinstance(n, ast.Dict):
            elts = [k for k in n.keys if k is not None]
        else:
            continue
        words = [e.value for e in elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)
                 and se.knows_status(e.value)]
        if len(words) >= 2 and not all(
                w.strip().lower() in ("on", "off") for w in words):
            found.append((n.lineno, words))
    return found


# Lists that are not a charger's status words, each with its reason.
_NOT_A_CHARGER_LIST = {
    # SEM's own home-battery status labels (battery_status_map)
    ("sensor.py", frozenset({"charging", "discharging"})),
    # (#1375) words of a battery SOC sensor's name that mark a code, not a level
    ("coordinator/sensor_reader.py", frozenset({"error", "fault"})),
}


class TestTheCopyIsGone:
    """No module but status_enum.py may write a list of status words again
    — the words belong there, where the reader and the wizard both read
    them."""

    def test_no_status_word_in_validate_entity(self):
        src = textwrap.dedent(inspect.getsource(
            hd.EVChargerDetector._validate_entity))
        found = sorted({
            n.value for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and se.knows_status(n.value)
        })
        assert found == [], (
            f"_validate_entity names status words {found} — ask "
            "status_enum.knows_status instead")

    def test_no_word_list_anywhere_in_the_package(self):
        root = Path(hd.__file__).parent
        hits, walked = [], set()
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel.split("/")[0] in ("tests", "tools", "scripts") or \
                    rel == "coordinator/charger_adapters/status_enum.py":
                continue
            walked.add(rel)
            for line, words in _status_word_lists(ast.parse(path.read_text())):
                if (rel, frozenset(words)) not in _NOT_A_CHARGER_LIST:
                    hits.append(f"{rel}:{line} {words}")
        assert {"hardware_detection.py", "coordinator/sensor_reader.py",
                "coordinator/coordinator.py", "config_flow.py"} <= walked
        assert hits == [], (
            "a private list of charger status words — they belong in "
            "status_enum.py:\n" + "\n".join(hits))

    def test_the_lint_can_fail(self):
        bad = 'def f(s):\n    return s in ("on", "plugged in", "charging")\n'
        assert _status_word_lists(ast.parse(bad)) == [
            (2, ["on", "plugged in", "charging"])]
        assert _status_word_lists(ast.parse('x = ("on", "off")\n')) == []
        # on plus one real word is a copy too
        assert _status_word_lists(ast.parse('x = ("on", "charging")\n')) == [
            (1, ["on", "charging"])]
        assert _status_word_lists(ast.parse(
            'x = {"charging": True, "paused": False}\n')) == [
            (1, ["charging", "paused"])]
