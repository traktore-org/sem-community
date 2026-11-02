"""#810 — what the crawler makes of a real EG4 Web Monitor install.

The entity shapes below are copied from a live Home Assistant that ran the
real ``eg4_web_monitor`` 3.5.1-beta.21 against a simulated FlexBOSS21 on
Modbus TCP: unique_id is ``<serial>_<key>``, translation_key is empty, units
are as the integration sets them (``ac_charge_power`` is kW, the mode select
is ``Normal`` / ``Standby``).

Two lexicon gaps showed up and are fixed here for every brand:

* ``pv_total_power`` — the sum of all strings — was refused by the solar rule
  because it holds the word ``total`` (counters and energy sums).
* ``ac_charge_start_battery_soc`` — the SOC at which AC charging BEGINS —
  was offered as the charge target SOC.
"""
from __future__ import annotations

import importlib.util
import pathlib
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

from custom_components.solar_energy_management import hardware_detection as hd
from custom_components.solar_energy_management.consts import (
    integration_roster as roster_mod,
)
from custom_components.solar_energy_management.consts import role_lexicon as lex
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    PLATFORM_GRID_SIGN_INVERT,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SER = "4512670118"
DOM = "eg4_web_monitor"

# (platform, key, device_class, unit, options, state_class)
_SHAPES = [
    ("sensor", "pv_total_power", "power", "W", None, "measurement"),
    ("sensor", "pv1_power", "power", "W", None, "measurement"),
    ("sensor", "pv2_power", "power", "W", None, "measurement"),
    ("sensor", "pv3_power", "power", "W", None, "measurement"),
    ("sensor", "grid_power", "power", "W", None, "measurement"),
    ("sensor", "grid_import_power", "power", "W", None, "measurement"),
    ("sensor", "grid_export_power", "power", "W", None, "measurement"),
    ("sensor", "grid_import_power_l1", "power", "W", None, "measurement"),
    ("sensor", "grid_export_power_l1", "power", "W", None, "measurement"),
    ("sensor", "battery_power", "power", "W", None, "measurement"),
    ("sensor", "battery_bank_battery_bank_power", "power", "W", None,
     "measurement"),
    ("sensor", "state_of_charge", "battery", "%", None, "measurement"),
    ("sensor", "consumption_power", "power", "W", None, "measurement"),
    ("sensor", "total_load_power", "power", "W", None, "measurement"),
    ("sensor", "eps_power", "power", "W", None, "measurement"),
    ("sensor", "battery_voltage", "voltage", "V", None, "measurement"),
    ("sensor", "grid_import_lifetime", "energy", "kWh", None, "total_increasing"),
    ("sensor", "grid_export_lifetime", "energy", "kWh", None, "total_increasing"),
    ("number", "ac_charge_power", None, "kW", None, None),
    ("number", "ac_charge_soc_limit", None, "%", None, None),
    ("number", "ac_charge_start_battery_soc", None, "%", None, None),
    ("number", "system_charge_soc_limit", None, "%", None, None),
    ("select", "operating_mode", None, None, ["Normal", "Standby"], None),
    ("switch", "ac_charge", None, None, None, None),
]


def _entity_id(platform, key):
    # the live switch for key ``ac_charge`` is named ``…_ac_charge_mode``
    name = "ac_charge_mode" if key == "ac_charge" else key
    return f"{platform}.eg4_{name}"


def _rows():
    return [
        NS(entity_id=_entity_id(p, k), platform=DOM, unique_id=f"{SER}_{k}",
           translation_key=None, disabled_by=None, device_id="dev1",
           config_entry_id="cfg1", original_name=k, name=None,
           original_device_class=dc, unit_of_measurement=unit,
           entity_category=None,
           capabilities={"options": opts} if opts else None,
           has_entity_name=True, original_icon=None, area_id=None,
           hidden_by=None, options={}, supported_features=0)
        for p, k, dc, unit, opts, _sc in _SHAPES
    ]


def _registry():
    reg = MagicMock()
    reg.entities = {r.entity_id: r for r in _rows()}
    return reg


def _vocabulary():
    vocab: dict = {}
    for p, k, _dc, _u, opts, _sc in _SHAPES:
        vocab.setdefault(p, {})[k] = {"options": list(opts or [])}
    return vocab


def _crawler():
    spec = importlib.util.spec_from_file_location(
        "crawler_810", ROOT / "scripts" / "crawl_integration_roster.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestLexiconGaps:
    def test_the_sum_of_all_strings_is_a_solar_power(self):
        assert lex.role_for("sensor", "pv_total_power") == "solar_power"
        assert lex.role_for("sensor", "solar_total_power") == "solar_power"
        assert lex.role_for("sensor", "total_pv_power") == "solar_power"

    def test_counters_and_single_strings_are_still_not(self):
        for key in ("pv_total_energy", "total_pv_energy", "solar_total",
                    "pv_power_today", "pv1_power", "pv_total_power_forecast",
                    "total_power"):
            assert lex.role_for("sensor", key) != "solar_power", key

    def test_the_start_threshold_is_not_the_target(self):
        assert lex.role_for("number", "ac_charge_start_battery_soc") \
            != "battery_target_soc"
        assert lex.role_for("number", "ac_charge_soc_limit") \
            == "battery_target_soc"

    def test_a_start_word_inside_another_word_does_not_matter(self):
        # whole segment only: ``restart`` is not ``start``
        assert lex.role_for("number", "restart_charge_target_soc") \
            == "battery_target_soc"

    def test_the_global_ceiling_stays_out(self):
        assert lex.role_for("number", "system_charge_soc_limit") \
            != "battery_target_soc"


class TestCrawlerOutput:
    """The crawler, run over the keys this integration really creates."""

    def test_every_role_is_named_from_the_keys_alone(self):
        got = _crawler().roles_from_vocabulary(_vocabulary(), lex, "energy", DOM)
        keys = {role: tuple(v["keys"]) for role, v in got.items()}
        assert keys["solar_power"] == ("pv_total_power",)
        assert keys["battery_power"] == ("battery_power",)
        assert keys["battery_soc"] == ("state_of_charge",)
        assert keys["battery_charge_limit"] == ("ac_charge_power",)
        assert keys["battery_target_soc"] == ("ac_charge_soc_limit",)
        assert keys["battery_strategy"] == ("operating_mode",)
        assert keys["battery_force_charge"] == ("ac_charge",)
        assert keys["grid_power"] == ("grid_power",)
        assert keys["grid_import_power"] == ("grid_import_power",)
        assert keys["grid_export_power"] == ("grid_export_power",)

    def test_the_select_options_are_kept_as_the_integration_spells_them(self):
        got = _crawler().roles_from_vocabulary(_vocabulary(), lex, "energy", DOM)
        assert got["battery_strategy"]["options"] == ("Normal", "Standby")

    def test_the_shipped_row_has_the_solar_sensor(self):
        row = roster_mod.ROLE_VOCAB[DOM]
        assert row["solar_power"]["keys"] == ("pv_total_power",)
        assert row["battery_target_soc"]["keys"] == ("ac_charge_soc_limit",)
        assert row["battery_charge_limit"]["keys"] == ("ac_charge_power",)

    def test_the_live_registry_gets_a_proposal_for_each_read_role(self):
        prop = hd.propose_roles_from_roster(_rows(), DOM)
        assert prop["solar_power"]["entity"] == "sensor.eg4_pv_total_power"
        assert prop["battery_power"]["entity"] == "sensor.eg4_battery_power"
        assert prop["battery_soc"]["entity"] == "sensor.eg4_state_of_charge"
        assert prop["grid_power"]["entity"] == "sensor.eg4_grid_power"

    def test_the_target_is_the_ac_charge_limit_not_the_start_threshold(self):
        prop = hd.propose_roles_from_roster(_rows(), DOM)
        assert prop["battery_target_soc"]["entity"] \
            == "number.eg4_ac_charge_soc_limit"
        assert prop["battery_charge_limit"]["entity"] \
            == "number.eg4_ac_charge_power"

    def test_the_mode_select_is_read_only_for_sem(self):
        prop = hd.propose_roles_from_roster(_rows(), DOM)
        assert prop["battery_strategy"]["entity"] == "select.eg4_operating_mode"
        assert prop["battery_strategy"]["action"] == "observe_only"

    def test_the_four_sources_come_from_the_declared_keys(self):
        out = hd.propose_energy_sources(registry=_registry())
        assert out["solar_power_sensor"]["entity"] == "sensor.eg4_pv_total_power"
        assert out["battery_power_sensor"]["entity"] == "sensor.eg4_battery_power"
        assert out["battery_soc_sensor"]["entity"] == "sensor.eg4_state_of_charge"
        assert out["grid_import_power_sensor"]["entity"] == "sensor.eg4_grid_power"

    def test_shape_alone_proposes_nothing_because_it_cannot_tell(self, monkeypatch):
        # three PV strings, three grid power sensors, a battery bank beside the
        # inverter's own battery power and four load sensors:
        # a guess here would look confirmed in the form (#1213)
        monkeypatch.setattr(hd, "_roster", lambda: None)
        assert hd.propose_energy_sources(registry=_registry()) == {}


class TestSignAndCensus:
    def test_grid_power_counts_import_as_positive(self):
        # the integration computes power_to_user − power_to_grid
        assert PLATFORM_GRID_SIGN_INVERT[DOM] is True

    def test_the_battery_needs_no_seed(self):
        from custom_components.solar_energy_management.coordinator import (
            sensor_reader as sr,
        )
        assert DOM not in sr.PLATFORM_BATTERY_SIGN_INVERT

    def test_the_install_is_a_known_inverter_not_an_unknown_one(self):
        assert DOM in hd.KNOWN_INVERTER_DOMAINS
        census = hd.build_integration_census(registry=_registry())
        assert DOM in census["known_inverter_domains_present"]
        assert DOM not in census["unknown_energy_domains"]
