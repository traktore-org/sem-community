"""#1103 — SEM's own sensor is never an input, and the grid pick is read.

@LightBridge16 (SolarEdge + an Enphase Envoy, Energy Dashboard with grid
counters but no grid power): the Repair "SEM is checking two guessed grid
meters" named ``sensor.sem_grid_import_power`` as the grid IMPORT meter —
SEM's own result, worked out from the meter it was now standing in for —
and the Envoy's SOLAR ``current_power_production`` as the export meter. The
way out it named, "Configure → Sensors", is a page that does not exist.

Three faults, each pinned here:

1. A scan that turns "some sensor in the house" into an input admitted SEM's
   own entities. The grid name scan is the reported one; the battery SOC
   scan (``sensor.sem_battery_soc``) and the capacity scan
   (``sensor.sem_diag_battery_capacity``, the SAVED size) are the same
   mistake. One predicate, ``utils.own_entity.is_sem_entity``, asks the
   entity registry who owns the entity; a structural test below holds every
   state scan in the package to it.
2. The Config card's **Sensor sources → Grid power** pick (``grid_power_sensor``)
   was read on the legacy path only. On a home WITH an Energy Dashboard it
   changed nothing: grid stayed 0 and the name guess ran on.
3. An export pick with no import half is never read, yet raised the
   "checking" Repair — which then waited for ever.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.utils.own_entity import is_sem_entity

from .test_split_grid_integration import (
    _make_energy_dashboard_config,
    _make_reader_with_states,
    _state,
)

DOMAIN = "solar_energy_management"
SR = "custom_components.solar_energy_management.coordinator.sensor_reader"
_ROOT = Path(__file__).resolve().parents[1]


def _registry(platform_of=None, device_of=None):
    """An entity registry that answers ``platform`` and ``device_id``."""
    platform_of = platform_of or {}
    device_of = device_of or {}
    reg = MagicMock()

    def _get(eid):
        e = MagicMock()
        e.entity_id = eid
        e.platform = platform_of.get(eid, "some_integration")
        e.device_id = device_of.get(eid)
        return e
    reg.async_get = _get
    reg.entities = {}
    return reg


def _reporter_ed():
    return _make_energy_dashboard_config(
        solar_power="sensor.solaredge_ac_power",
        grid_import_power=None,
        grid_import_energy="sensor.solaredge_m1_imported_kwh",
        grid_export_energy="sensor.solaredge_m1_exported_kwh",
        battery_power=None,
    )


def _reporter_states(**extra):
    states = {
        "sensor.solaredge_ac_power": _state(2600, device_class="power"),
        "sensor.solaredge_m1_ac_power": _state(-1200, device_class="power"),
        "sensor.envoy_122217046540_current_power_production":
            _state(2500, device_class="power"),
        # SEM's own result, with exactly the shape a meter has.
        "sensor.sem_grid_import_power": _state(0, device_class="power"),
        "sensor.solaredge_m1_imported_kwh": _state(100, "kWh"),
        "sensor.solaredge_m1_exported_kwh": _state(50, "kWh"),
    }
    states.update(extra)
    return states


_REPORTER_REG = dict(
    platform_of={"sensor.sem_grid_import_power": DOMAIN,
                 "sensor.envoy_122217046540_current_power_production": "enphase_envoy"},
    device_of={"sensor.solaredge_m1_imported_kwh": "m1",
               "sensor.solaredge_m1_ac_power": "m1"},
)


# ── the predicate ────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestThePredicate:
    def test_sem_owns_what_the_registry_says_it_owns(self):
        reg = _registry({"sensor.renamed_by_user": DOMAIN})
        assert is_sem_entity(None, "sensor.renamed_by_user", reg) is True

    def test_a_sem_shaped_id_is_not_proof(self):
        # The id is the user's to rename; the registry is the owner's record.
        reg = _registry({"sensor.sem_meter": "shelly"})
        assert is_sem_entity(None, "sensor.sem_meter", reg) is False

    def test_no_registry_entry_is_no_answer(self):
        reg = MagicMock()
        reg.async_get = lambda eid: None
        assert is_sem_entity(None, "sensor.template_meter", reg) is False

    def test_a_broken_registry_filters_nothing(self):
        reg = MagicMock()
        reg.async_get = MagicMock(side_effect=RuntimeError("boom"))
        assert is_sem_entity(None, "sensor.x", reg) is False
        assert is_sem_entity(None, "", reg) is False


# ── 1. the grid name scan ────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheGridScan:
    def _discover(self, states):
        reader = _make_reader_with_states(MagicMock(), states, _reporter_ed())
        with patch(f"{SR}.er.async_get", return_value=_registry(**_REPORTER_REG)):
            return reader._discover_split_grid_power(reader._energy_dashboard_config)

    def test_sems_own_import_sensor_is_not_a_candidate(self):
        # The reporter's Repair, reproduced: before the fix this returned
        # ("sensor.sem_grid_import_power", <envoy>, "any-device").
        imp, exp, conf = self._discover(_reporter_states())
        assert imp is None
        assert exp == "sensor.envoy_122217046540_current_power_production"

    def test_a_real_candidate_after_sem_in_the_alphabet_now_wins(self):
        # First match wins over a sorted scan, and "sensor.sem_" sorts before
        # "sensor.solaredge_": SEM's own sensor used to take the place of a
        # real one that came later.
        imp, _exp, _conf = self._discover(_reporter_states(**{
            "sensor.solaredge_power_consumption": _state(800, device_class="power"),
        }))
        assert imp == "sensor.solaredge_power_consumption"


# ── 2. the Grid power pick on the Energy Dashboard path ─────────────────────

@pytest.mark.unit
class TestTheGridPickIsRead:
    def _read(self, ed=None, extra_config=None, states=None):
        reader = _make_reader_with_states(
            MagicMock(), states or _reporter_states(), ed or _reporter_ed(),
            extra_config,
        )
        reader._discover_split_grid_power = MagicMock(
            side_effect=AssertionError("the name guess ran"))
        with patch(f"{SR}.er.async_get", return_value=_registry(**_REPORTER_REG)), \
                patch(f"{SR}._ri") as ri:
            readings = reader._read_from_energy_dashboard()
        return reader, readings, ri

    def test_the_pick_is_read_on_a_dashboard_home(self):
        # Before the fix: grid 0, "No grid power sensor found", guess on.
        reader, readings, ri = self._read(
            extra_config={"grid_power_sensor": "sensor.solaredge_m1_ac_power"})
        assert readings.grid_power == -1200.0
        assert reader._grid_source_key == "combined:sensor.solaredge_m1_ac_power"
        # Nothing is guessed, so a guess Repair a previous run left goes.
        ri.clear_split_grid_guessed.assert_called()
        ri.raise_split_grid_guessed.assert_not_called()

    def test_the_pick_stands_above_the_dashboards_own_sensor(self):
        ed = _reporter_ed()
        ed.grid_import_power = "sensor.solaredge_ac_power"
        ed.grid_power_list = ["sensor.solaredge_ac_power"]
        _r, readings, _ri = self._read(
            ed=ed, extra_config={"grid_power_sensor": "sensor.solaredge_m1_ac_power"})
        assert readings.grid_power == -1200.0

    def test_a_whole_manual_pair_stands_above_the_pick(self):
        states = _reporter_states(**{
            "sensor.p1_import": _state(300, device_class="power"),
            "sensor.p1_export": _state(0, device_class="power"),
        })
        reader, readings, _ri = self._read(states=states, extra_config={
            "grid_power_sensor": "sensor.solaredge_m1_ac_power",
            "grid_import_power_entity": "sensor.p1_import",
            "grid_export_power_entity": "sensor.p1_export",
        })
        assert readings.grid_power == -300.0
        assert reader._grid_source_key.startswith("manual:")

    def test_half_a_manual_pair_gives_way_to_the_pick(self):
        states = _reporter_states(**{"sensor.p1_import": _state(300, device_class="power")})
        reader, readings, _ri = self._read(states=states, extra_config={
            "grid_power_sensor": "sensor.solaredge_m1_ac_power",
            "grid_import_power_entity": "sensor.p1_import",
        })
        assert readings.grid_power == -1200.0
        assert reader._grid_source_key == "combined:sensor.solaredge_m1_ac_power"

    def test_an_export_half_gives_way_to_the_pick_too(self):
        # Review M2: the give-way rule checked the import half only, so an
        # export-only half read "export minus 0" and hid every import.
        states = _reporter_states(**{"sensor.p1_export": _state(0, device_class="power")})
        reader, readings, _ri = self._read(states=states, extra_config={
            "grid_power_sensor": "sensor.solaredge_m1_ac_power",
            "grid_export_power_entity": "sensor.p1_export",
        })
        assert readings.grid_power == -1200.0
        assert reader._grid_source_key == "combined:sensor.solaredge_m1_ac_power"

    def test_sems_own_sensor_picked_by_hand_is_ignored(self, caplog):
        # Review H1: the card's picker lists SEM's own power sensors. Read
        # as the meter, sensor.sem_grid_power is SEM's last answer, for ever.
        states = _reporter_states(**{"sensor.sem_grid_power": _state(1234, device_class="power")})
        reader = _make_reader_with_states(
            MagicMock(), states, _reporter_ed(),
            {"grid_power_sensor": "sensor.sem_grid_power"})
        reg = _registry({"sensor.sem_grid_power": DOMAIN,
                         "sensor.sem_grid_import_power": DOMAIN})
        with patch(f"{SR}.er.async_get", return_value=reg), patch(f"{SR}._ri"):
            with caplog.at_level("WARNING"):
                readings = reader._read_from_energy_dashboard()
                reader._read_from_energy_dashboard()
        assert readings.grid_power == 0.0
        assert reader._grid_source_key != "combined:sensor.sem_grid_power"
        assert caplog.text.count("sensor.sem_grid_power is one of SEM's own") == 1

    def test_without_a_pick_the_dashboard_home_is_unchanged(self):
        ed = _reporter_ed()
        ed.grid_import_power = "sensor.solaredge_m1_ac_power"
        ed.grid_power_list = ["sensor.solaredge_m1_ac_power"]
        reader, readings, _ri = self._read(ed=ed)
        assert readings.grid_power == -1200.0
        assert reader._grid_source_key == "combined:sensor.solaredge_m1_ac_power"


# ── 2b. a saved sign lock belongs to the source it was learned on ───────────

@pytest.mark.unit
class TestASavedLockKeepsItsSource:
    """Review H2. Every pair path sets the grid lock, and the lock was saved
    with no source. After the reload that applies a Grid power pick, the old
    lock skipped every detector: a pick in HA convention read import as
    export. The lock now carries its source, like the one-tap flip (#971)."""

    def _reader(self, saved):
        ed = _reporter_ed()
        reader = _make_reader_with_states(
            MagicMock(), _reporter_states(), ed,
            {"grid_power_sensor": "sensor.solaredge_m1_ac_power"})
        reader.restore_sign_state(saved)
        return reader

    def _read_power(self, reader):
        with patch(f"{SR}.er.async_get", return_value=_registry(**_REPORTER_REG)), \
                patch(f"{SR}._ri"):
            return reader.read_power()

    def test_the_lock_is_saved_with_its_source(self):
        reader = self._reader(None)
        self._read_power(reader)
        assert reader.export_sign_state()["grid_source"] == \
            "combined:sensor.solaredge_m1_ac_power"

    def test_a_lock_from_another_source_is_dropped(self):
        reader = self._reader({"grid_detected": True, "grid_inverted": False,
                               "grid_source": "manual:sensor.a|sensor.b"})
        assert reader._grid_sign_detected is True
        self._read_power(reader)
        assert reader._grid_sign_detected is False

    def test_a_lock_from_the_same_source_is_kept(self):
        reader = self._reader({"grid_detected": True, "grid_inverted": True,
                               "grid_source": "combined:sensor.solaredge_m1_ac_power"})
        power = self._read_power(reader)
        assert reader._grid_sign_detected is True
        assert power.grid_power == 1200.0          # the kept lock negates

    def test_a_store_from_before_the_source_is_kept_as_it_was(self):
        reader = self._reader({"grid_detected": True, "grid_inverted": True})
        self._read_power(reader)
        assert reader._grid_sign_detected is True

    def test_the_brand_seed_reads_the_pick_through_read_power(self):
        # The pick is a SolarEdge meter: the brand table says it reports
        # import as positive, so SEM negates it from the first cycle.
        reader = self._reader(None)
        reg = _registry({"sensor.solaredge_m1_ac_power": "solaredge"},
                        {"sensor.solaredge_m1_imported_kwh": "m1"})
        with patch(f"{SR}.er.async_get", return_value=reg), patch(f"{SR}._ri"):
            power = reader.read_power()
        assert reader._grid_sign_detected is True
        assert power.grid_power == 1200.0


@pytest.mark.unit
class TestAPairIsNeverUnlockedIntoANegation:
    """Re-review N1: dropping the restored lock on a PAIR source let the
    brand seed run — on the leftover Grid power pick's platform — and negate
    "export − import" for ever. A pair's sign is by declaration."""

    def _pair_reader(self, saved, extra=None):
        states = _reporter_states(**{
            "sensor.p1_import": _state(2000, device_class="power"),
            "sensor.p1_export": _state(0, device_class="power"),
        })
        cfg = {"grid_power_sensor": "sensor.solaredge_m1_ac_power",
               "grid_import_power_entity": "sensor.p1_import",
               "grid_export_power_entity": "sensor.p1_export"}
        cfg.update(extra or {})
        reader = _make_reader_with_states(MagicMock(), states, _reporter_ed(), cfg)
        reader.restore_sign_state(saved)
        return reader

    def _read(self, reader, n=3):
        reg = _registry({"sensor.solaredge_m1_ac_power": "solaredge"},
                        {"sensor.solaredge_m1_imported_kwh": "m1"})
        with patch(f"{SR}.er.async_get", return_value=reg), patch(f"{SR}._ri"):
            return [reader.read_power().grid_power for _ in range(n)]

    def test_a_manual_pair_under_a_leftover_brand_pick_reads_import(self):
        reader = self._pair_reader({"grid_detected": True, "grid_inverted": False,
                                    "grid_source": "combined:sensor.solaredge_m1_ac_power"})
        assert self._read(reader) == [-2000.0] * 3
        assert reader._grid_sign_detected is True
        assert reader._grid_sign_inverted is False

    def test_an_inversion_carried_from_a_combined_meter_is_not_kept_on_a_pair(self):
        reader = self._pair_reader({"grid_detected": True, "grid_inverted": True,
                                    "grid_source": "combined:sensor.other"})
        assert self._read(reader) == [-2000.0] * 3

    def test_a_pair_with_one_sem_half_is_no_pair(self):
        # Re-review M1: the old guess Repair's own pair — SEM's import
        # sensor and the Envoy's SOLAR production — read as +2500 export.
        reader = _make_reader_with_states(MagicMock(), _reporter_states(), _reporter_ed(), {
            "grid_import_power_entity": "sensor.sem_grid_import_power",
            "grid_export_power_entity": "sensor.envoy_122217046540_current_power_production",
        })
        with patch(f"{SR}.er.async_get", return_value=_registry(**_REPORTER_REG)), \
                patch(f"{SR}._ri"):
            readings = reader._read_from_energy_dashboard()
        assert readings.grid_power == 0.0
        assert not str(reader._grid_source_key or "").startswith("manual:")

    def test_a_restored_source_is_saved_until_this_run_knows_its_own(self):
        reader = self._pair_reader({"grid_detected": True, "grid_inverted": False,
                                    "grid_source": "manual:sensor.p1_import|sensor.p1_export"})
        assert reader.export_sign_state()["grid_source"] == \
            "manual:sensor.p1_import|sensor.p1_export"


# ── 3. half a pair is not "being checked" ───────────────────────────────────

@pytest.mark.unit
class TestHalfAPairIsSaidAsItIs:
    def _run(self, states):
        reader = _make_reader_with_states(MagicMock(), states, _reporter_ed())
        with patch(f"{SR}.er.async_get", return_value=_registry(**_REPORTER_REG)), \
                patch(f"{SR}._ri") as ri:
            readings = reader._read_from_energy_dashboard()
        return readings, ri

    def test_an_export_only_guess_raises_could_not_find(self):
        readings, ri = self._run(_reporter_states())
        assert readings.grid_power == 0.0
        ri.raise_split_grid_rejected.assert_called_once()
        assert ri.raise_split_grid_rejected.call_args.kwargs == {
            "import_entity": None,
            "export_entity": "sensor.envoy_122217046540_current_power_production",
        }
        ri.raise_split_grid_guessed.assert_not_called()

    def test_a_whole_guessed_pair_is_still_being_checked(self):
        readings, ri = self._run(_reporter_states(**{
            "sensor.solaredge_power_consumption": _state(800, device_class="power"),
        }))
        ri.raise_split_grid_guessed.assert_called_once()
        ri.raise_split_grid_rejected.assert_not_called()


# ── 1b. the siblings: battery SOC and capacity scans ────────────────────────

@pytest.mark.unit
class TestTheBatteryScans:
    def test_sems_soc_copy_does_not_make_the_real_one_ambiguous(self):
        # Strategy 1 (name stem) and 2 (same device) find nothing; the
        # last-resort scan needs EXACTLY one candidate. SEM's own copy of
        # the SOC made it two, so none.
        states = {
            "sensor.inverter_pbattery": _state(-500, device_class="power"),
            "sensor.speicher_ladezustand": _state(64, "%", device_class="battery"),
            "sensor.sem_battery_soc": _state(64, "%", device_class="battery"),
        }
        reader = _make_reader_with_states(MagicMock(), states, _reporter_ed())
        reg = _registry({"sensor.sem_battery_soc": DOMAIN})
        with patch(f"{SR}.er.async_get", return_value=reg), \
                patch(f"{SR}.er.async_entries_for_device", return_value=[]):
            assert reader._auto_detect_battery_soc("sensor.inverter_pbattery") == \
                "sensor.speicher_ladezustand"

    def test_sems_soc_copy_alone_is_not_a_soc_sensor(self):
        states = {
            "sensor.inverter_pbattery": _state(-500, device_class="power"),
            "sensor.sem_battery_soc": _state(64, "%", device_class="battery"),
        }
        reader = _make_reader_with_states(MagicMock(), states, _reporter_ed())
        reg = _registry({"sensor.sem_battery_soc": DOMAIN})
        with patch(f"{SR}.er.async_get", return_value=reg), \
                patch(f"{SR}.er.async_entries_for_device", return_value=[]):
            assert reader._auto_detect_battery_soc("sensor.inverter_pbattery") is None

    def _capacity(self, states):
        ed = _reporter_ed()
        ed.battery_power = "sensor.inverter_pbattery"
        reader = _make_reader_with_states(MagicMock(), states, ed)
        reg = _registry({"sensor.sem_diag_battery_capacity": DOMAIN})
        with patch(f"{SR}.er.async_get", return_value=reg):
            return reader.auto_detect_battery_capacity_kwh()

    def test_the_saved_size_is_not_a_found_battery(self):
        # sensor.sem_diag_battery_capacity shows the SAVED capacity (unitless).
        # Read here, a saved size came back as proof a battery exists.
        assert self._capacity({
            "sensor.inverter_pbattery": _state(0, device_class="power"),
            "sensor.sem_diag_battery_capacity": _state(10, unit=None),
        }) is None

    def test_a_real_rated_capacity_is_still_found(self):
        assert self._capacity({
            "sensor.inverter_pbattery": _state(0, device_class="power"),
            "sensor.sem_diag_battery_capacity": _state(10, unit=None),
            "sensor.pack_rated_capacity": _state(9.6, "kWh"),
        }) == pytest.approx(9.6)


# ── the guard: every state scan answers the question ────────────────────────

#: Domains SEM publishes entities in. A scan of any other domain cannot meet
#: one of SEM's own entities.
_SEM_DOMAINS = {"sensor", "binary_sensor", "switch", "number", "select",
                "button", "time"}

#: Scans that need no filter, each with the reason. A new scan is not added
#: here to make the test pass: it calls ``is_sem_entity`` instead.
_EXEMPT = {
    ("coordinator/retention.py", "run_purge"):
        "looks for SEM's own entities on purpose — it purges them",
    ("tariff/tariff_provider.py", "detect_provider"):
        "matches brand words only (tibber, amber, octopus_energy, nord_pool, "
        "nordpool) that no SEM entity id carries",
    ("coordinator/battery_adapters/huawei.py", "_forcible_status_reading"):
        "matches the Huawei word 'forcible' only",
    ("coordinator/repair_issues.py", "detect_keba_failsafe_state"):
        "matches 'keba' AND 'failsafe' only",
    ("devices/base.py", "_failsafe_readback_state"):
        "needs fallback_current + failsafe_timeout attributes and the "
        "charger's brand word; SEM's binary sensors carry neither",
}


def _scans():
    """(file, function, domain-literal-or-None) for every ``.async_all(`` call
    in production code."""
    out = []
    for path in sorted(_ROOT.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        if rel.startswith(("tests/", "tools/", "scripts/")) or "__pycache__" in rel:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "async_all"):
                    domains = None
                    if node.args and isinstance(node.args[0], ast.Constant):
                        domains = {node.args[0].value}
                    elif node.args and isinstance(node.args[0], ast.List):
                        domains = {e.value for e in node.args[0].elts
                                   if isinstance(e, ast.Constant)}
                    out.append((rel, fn, domains))
    return out


def _calls_predicate(fn) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if name == "is_sem_entity":
                return True
    return False


@pytest.mark.unit
class TestEveryScanAsksWhoOwnsTheEntity:
    def test_the_walk_finds_the_scans_it_is_about(self):
        # Not vacuous: the three reported scans are among those it walks.
        names = {(rel, fn.name) for rel, fn, _d in _scans()}
        for want in ("_discover_split_grid_power", "_auto_detect_battery_soc",
                     "auto_detect_battery_capacity_kwh"):
            assert ("coordinator/sensor_reader.py", want) in names

    def test_every_scan_that_can_meet_a_sem_entity_filters_it(self):
        missing = []
        for rel, fn, domains in _scans():
            if domains is not None and not (domains & _SEM_DOMAINS):
                continue                      # e.g. weather: SEM has none
            if (rel, fn.name) in _EXEMPT or _calls_predicate(fn):
                continue
            missing.append(f"{rel}:{fn.lineno} {fn.name}")
        assert not missing, (
            "these state scans can read one of SEM's own entities back as an "
            "input — filter with utils.own_entity.is_sem_entity (#1103): "
            + ", ".join(sorted(set(missing))))

    def test_every_exemption_still_names_a_real_scan(self):
        names = {(rel, fn.name) for rel, fn, _d in _scans()}
        stale = set(_EXEMPT) - names
        assert not stale, f"exemptions with no scan left: {stale}"


# ── the Repair names places that exist ──────────────────────────────────────

@pytest.mark.unit
class TestTheRepairNamesARealPlace:
    @pytest.mark.parametrize("lang", sorted(
        p.stem for p in (_ROOT / "translations").glob("*.json")))
    @pytest.mark.parametrize("key", ["split_grid_guessed", "split_grid_rejected"])
    def test_the_way_out_names_what_that_card_shows(self, key, lang):
        # The reporter's card is Dutch. A Repair naming "Sensor sources" on a
        # card that says "Sensorbronnen" sends them hunting again — and both
        # places are hidden until Advanced is on (review M1).
        text = json.loads((_ROOT / "translations" / f"{lang}.json").read_text(
            encoding="utf-8"))["issues"][key]["description"]
        assert "Configure → Sensors" not in text   # no such page (#1103)
        assert "→ Sensoren" not in text
        cards = json.loads((_ROOT / "dashboard" / "translations.json").read_text(
            encoding="utf-8"))
        labels = {**cards["en"], **cards["zh" if lang == "zh-Hans" else lang]}
        for label_key in ("Configuration", "config_advanced_label",
                          "config_section_sensor_sources", "config_grid_power_sensor",
                          "config_section_tariff", "config_grid_import_entity",
                          "config_grid_export_entity"):
            want = labels.get(label_key) or label_key
            assert f"**{want}**" in text, (lang, label_key)

    def test_both_places_are_on_the_dashboard(self):
        from ._dashboard_src import dashboard_src
        card = dashboard_src()
        for key in ("grid_power_sensor", "grid_import_power_entity", "grid_export_power_entity"):
            assert f"'{key}'" in card, key
