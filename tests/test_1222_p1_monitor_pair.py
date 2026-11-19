"""#1222 — a P1 Monitor's grid power is found in every language.

P1 Monitor (HA core ``p1_monitor``) gives a smart meter's grid import and
export power as two sensors. When the Energy Dashboard's grid entry has
counters and no power sensor, SEM looks for that pair. It matched the
ENGLISH entity_id words only (``power_consumption`` / ``power_production``),
and P1 Monitor's names follow the user's language: ``sensor.smartmeter_
stroomverbruik`` in Dutch, ``…_stromverbrauch`` in German. Nothing matched,
and the grid read 0 W.

The keys do not change with the language, but they are common words: a heat
pump, a car and a solar inverter use them for their own power. A lexicon
rule could not name one brand, so the crawler gave ``p1_monitor`` no keys,
and with no anchor word it called the integration "other". A rule may now
carry words for one integration only (``brand_any``). A Tibber Pulse has the
same shape (``power`` / ``power_production``, German "Energie") and is swept
with it. Bug class 10, the split-pair half.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import re
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.consts import (
    integration_roster as roster_mod,
)
from custom_components.solar_energy_management.consts import role_lexicon as lex
from custom_components.solar_energy_management.coordinator import sensor_reader as sr_mod
from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _ha_component(domain: str) -> pathlib.Path:
    import homeassistant
    return pathlib.Path(homeassistant.__file__).parent / "components" / domain


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _state(value, unit="W", device_class=None, state_class="measurement"):
    s = MagicMock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit}
    if device_class:
        s.attributes["device_class"] = device_class
    if state_class:
        s.attributes["state_class"] = state_class
    return s


def _ed(import_energy, export_energy):
    ed = MagicMock()
    ed.solar_power = None
    ed.solar_power_list = []
    ed.grid_import_power = None
    ed.grid_power_list = []
    ed.grid_power_from = None
    ed.grid_power_to = None
    ed.grid_import_energy = import_energy
    ed.grid_export_energy = export_energy
    ed.grid_import_energy_list = [import_energy]
    ed.grid_export_energy_list = [export_energy]
    ed.battery_power = None
    ed.battery_power_list = []
    ed.battery_power_from = None
    ed.battery_power_to = None
    ed.battery_power_inverted = False
    ed.battery_power_pairs = []
    ed.battery_soc = None
    ed.battery_soc_list = []
    ed.battery_charge_energy = None
    ed.battery_discharge_energy = None
    ed.ev_power = None
    ed.has_solar = False
    ed.has_grid = True
    ed.has_battery = False
    ed.has_ev = False
    return ed


def _entry(entity_id, platform, translation_key, unique_id, device_id):
    e = MagicMock()
    e.entity_id = entity_id
    e.platform = platform
    e.translation_key = translation_key
    e.unique_id = unique_id
    e.device_id = device_id
    e.disabled_by = None
    return e


def _names(domain: str, lang: str, keys) -> dict:
    """The names HA gives these keys in ``lang``, read from HA's own files.
    A key the language has not translated is English, as in HA."""
    def load(code):
        path = _ha_component(domain) / "translations" / f"{code}.json"
        return json.loads(path.read_text()).get("entity", {}).get("sensor", {})

    def device_class_names(code):
        # (#1313) HA 2026.11 dropped names that equal the sensor type's own
        # name (Tibber's "power"); HA then names the entity by its device
        # class, from the sensor component's translations.
        path = _ha_component("sensor") / "translations" / f"{code}.json"
        return json.loads(path.read_text()).get("entity_component", {})

    tr, en = load(lang), load("en")
    dc, dc_en = device_class_names(lang), device_class_names("en")

    def name(k):
        found = tr.get(k) or en.get(k) or dc.get(k) or dc_en.get(k)
        assert found, f"HA names no '{k}' for {domain}"
        return found["name"]
    return {k: name(k) for k in keys}


class _Meter:
    """A meter as HA sets it up in one language. ``rows`` is a list of
    ``(translation_key, uid key, device, state)``; the entity_id is the
    device name plus the translated name, as HA builds it."""

    def __init__(self, platform, lang, rows, counters, uid):
        names = _names(platform, lang, [r[0] for r in rows])
        self.states, entries, self.eid = {}, [], {}
        for tk, key, device, state in rows:
            eid = f"sensor.{_slug(device)}_{_slug(names[tk])}"
            self.eid[tk] = eid
            self.states[eid] = state
            entries.append(_entry(eid, platform, tk, uid(device, key), device))
        self.registry = MagicMock()
        self.registry.entities = {e.entity_id: e for e in entries}
        self.registry.async_get = lambda eid: self.registry.entities.get(eid)
        device_of = {e.entity_id: e.device_id for e in entries}
        hass = MagicMock()
        hass.states.get = lambda eid: self.states.get(eid)

        def _all(domain=None):
            out = []
            for eid, st in self.states.items():
                s = MagicMock()
                s.entity_id = eid
                s.state = st.state
                s.attributes = st.attributes
                if domain is None or eid.startswith(f"{domain}."):
                    out.append(s)
            return out

        hass.states.async_all = _all
        self.reader = SensorReader(hass, {"update_interval": 10})
        self.reader._sign_vote_warmup = 0
        self.reader._energy_dashboard_config = _ed(
            self.eid[counters[0]], self.eid[counters[1]])
        self.reader._get_device_for_entity = device_of.get

    def read(self):
        with patch.object(sr_mod.er, "async_get", return_value=self.registry), \
                patch.object(sr_mod, "_ri", MagicMock()), \
                patch.object(sr_mod, "is_sem_entity", lambda *a, **k: False):
            return self.reader.read_power()

    @property
    def picks(self):
        d = self.reader._split_grid_discovery
        return d["import"], d["export"], d["confidence"]


_P1_ENTRY = "01JABCDEF0123456789ABCDEF"   # unique_id = f"{entry}_{service}_{key}"
_P1_LANGS = ("de", "en", "fy", "nl")


def _p1_monitor(lang, import_w, export_w):
    """P1 Monitor's SmartMeter device (power + counters) and its Phases
    device, in watts, as ``p1_monitor/sensor.py`` builds them."""
    def kwh(v):
        return _state(v, "kWh", "energy", "total_increasing")

    def w(v):
        return _state(v, "W", "power")

    rows = [
        ("power_consumption", "power_consumption", "SmartMeter", w(import_w)),
        ("power_production", "power_production", "SmartMeter", w(export_w)),
        ("energy_consumption_high", "energy_consumption_high", "SmartMeter",
         kwh(4321.0)),
        ("energy_production_high", "energy_production_high", "SmartMeter",
         kwh(1234.0)),
        ("power_consumed_phase_l1", "power_consumed_phase_l1", "Phases",
         w(import_w / 3)),
        ("power_produced_phase_l1", "power_produced_phase_l1", "Phases",
         w(export_w / 3)),
    ]
    return _Meter("p1_monitor", lang, rows,
                  ("energy_consumption_high", "energy_production_high"),
                  lambda dev, key: f"{_P1_ENTRY}_{dev.lower()}_{key}")


_PULSE_HOME = "96a14971-525a-4420-aae9-e5aedaa129ff"
_PULSE_LANGS = ("de", "en", "sv")


def _tibber_pulse(lang, import_w, export_w):
    """A Tibber Pulse as ``tibber/sensor.py`` builds it: one device per home,
    unique_id ``<home id>_rt_<camelCase key>``, beside an average power."""
    def kwh(v):
        return _state(v, "kWh", "energy", "total_increasing")

    dev = "Tibber Pulse Home"
    rows = [
        ("power", "power", dev, _state(import_w, "W", "power")),
        ("power_production", "powerProduction", dev,
         _state(export_w, "W", "power")),
        ("average_power", "averagePower", dev, _state(777, "W", "power")),
        ("last_meter_consumption", "lastMeterConsumption", dev, kwh(9876.0)),
        ("last_meter_production", "lastMeterProduction", dev, kwh(543.0)),
    ]
    return _Meter("tibber", lang, rows,
                  ("last_meter_consumption", "last_meter_production"),
                  lambda _dev, key: f"{_PULSE_HOME}_rt_{key}")


_IMP = {"p1_monitor": "power_consumption", "tibber": "power"}
_EXP = {"p1_monitor": "power_production", "tibber": "power_production"}
_CASES = ([("p1_monitor", lang) for lang in _P1_LANGS]
          + [("tibber", lang) for lang in _PULSE_LANGS])
_BUILD = {"p1_monitor": _p1_monitor, "tibber": _tibber_pulse}


@pytest.mark.parametrize("brand,lang", _CASES)
class TestTheMeterIsFoundInEveryLanguage:
    def test_import_reads_as_import(self, brand, lang):
        meter = _BUILD[brand](lang, import_w=1200, export_w=0)
        power = meter.read()
        assert meter.picks == (meter.eid[_IMP[brand]], meter.eid[_EXP[brand]],
                               "declared")
        assert power.grid_power == pytest.approx(-1200.0)

    def test_export_reads_as_export(self, brand, lang):
        meter = _BUILD[brand](lang, import_w=0, export_w=2500)
        power = meter.read()
        assert meter.picks == (meter.eid[_IMP[brand]], meter.eid[_EXP[brand]],
                               "declared")
        assert power.grid_power == pytest.approx(2500.0)


class TestTheKeyIsWhatFindsIt:
    """The control that makes the tests above mean something: without the
    roster's keys, a translated meter is not found, and an English one is
    found by its words only where they fit."""

    def _without(self, monkeypatch, brand):
        vocab = dict(roster_mod.ROLE_VOCAB)
        if brand == "p1_monitor":
            vocab.pop("p1_monitor", None)
        else:
            vocab["tibber"] = dict(vocab["tibber"])
            for role, extra in (("grid_import_power", "power"),
                                ("grid_export_power", "power_production")):
                body = dict(vocab["tibber"][role])
                body["keys"] = tuple(k for k in body["keys"] if k != extra)
                vocab["tibber"][role] = body
        monkeypatch.setattr(roster_mod, "ROLE_VOCAB", vocab)

    @pytest.mark.parametrize("lang", ["nl", "de"])
    def test_a_translated_p1_monitor_is_lost_without_the_key(self, monkeypatch, lang):
        self._without(monkeypatch, "p1_monitor")
        meter = _p1_monitor(lang, import_w=1200, export_w=0)
        meter.read()
        assert meter.picks[:2] == (None, None)

    def test_an_english_p1_monitor_was_found_by_its_words(self, monkeypatch):
        self._without(monkeypatch, "p1_monitor")
        meter = _p1_monitor("en", import_w=1200, export_w=0)
        meter.read()
        assert meter.picks == (meter.eid["power_consumption"],
                               meter.eid["power_production"], "same-device")

    def test_a_german_pulse_is_lost_without_the_key(self, monkeypatch):
        self._without(monkeypatch, "tibber")
        meter = _tibber_pulse("de", import_w=1200, export_w=0)
        meter.read()
        assert meter.picks[:2] == (None, None)

    def test_an_english_pulse_had_only_its_export(self, monkeypatch):
        """``…_power`` has no word the name search knows: half a pair."""
        self._without(monkeypatch, "tibber")
        meter = _tibber_pulse("en", import_w=1200, export_w=0)
        meter.read()
        assert meter.picks[:2] == (None, meter.eid["power_production"])


class TestWhichMeterIsTrusted:
    """(review) A trusted pair skips the counter check, so it must sit on the
    device the Energy Dashboard counts. Two Pulses (two homes) on one
    account, or counters with no device (Tibber's own statistics), must not
    hand SEM a trusted guess."""

    def _second_home(self, meter):
        for tk, key in (("power", "power"),
                        ("power_production", "powerProduction")):
            eid = meter.eid[tk].replace("pulse_home", "pulse_cabin")
            meter.states[eid] = _state(0, "W", "power")
            meter.registry.entities[eid] = _entry(
                eid, "tibber", tk, f"other-home_rt_{key}", "Tibber Pulse Cabin")
        return {tk: meter.eid[tk].replace("pulse_home", "pulse_cabin")
                for tk in ("power", "power_production")}

    def test_the_counted_home_wins(self):
        meter = _tibber_pulse("en", import_w=900, export_w=0)
        cabin = self._second_home(meter)
        power = meter.read()
        assert meter.picks == (meter.eid["power"],
                               meter.eid["power_production"], "declared")
        assert cabin["power"] not in meter.picks
        assert power.grid_power == pytest.approx(-900.0)

    def test_counters_with_no_device_are_checked_first(self):
        meter = _tibber_pulse("de", import_w=900, export_w=0)
        meter.reader._get_device_for_entity = lambda eid: None
        with patch.object(sr_mod.er, "async_get", return_value=meter.registry):
            imp, exp, on_device = meter.reader._declared_split_grid_power(
                meter.reader._energy_dashboard_config)
        assert (imp, exp) == (meter.eid["power"], meter.eid["power_production"])
        assert on_device is False          # "declared-elsewhere": counters check it


class TestOtherBrandsKeepTheirWords:
    """The words are a meter in these two brands only. A heat pump on the
    counters' own device that says the same keys is not the grid: the
    shipped roster gives its integration no grid keys."""

    def test_a_heat_pump_with_the_same_keys_is_not_declared(self):
        meter = _p1_monitor("nl", import_w=0, export_w=0)
        for tk in ("power_consumption", "power_production"):
            e = meter.registry.entities[meter.eid[tk]]
            e.platform = "lambda_heat_pumps"
            e.unique_id = f"heatpump_1_{tk}"
        with patch.object(sr_mod.er, "async_get", return_value=meter.registry):
            imp, exp, _ = meter.reader._declared_split_grid_power(
                meter.reader._energy_dashboard_config)
        assert (imp, exp) == (None, None)

    def test_a_pulse_average_is_not_its_power(self):
        """Tibber's ``power`` is a segment-end of ``average_power``: it may
        only match by translation_key, never by a unique_id that ends in
        ``_power``."""
        body = roster_mod.ROLE_VOCAB["tibber"]["grid_import_power"]
        assert "power" in body.get("exact_only", ())
        meter = _tibber_pulse("en", import_w=0, export_w=0)
        pulse = meter.registry.entities[meter.eid["power"]]
        pulse.translation_key = None          # an older HA: no key
        avg = meter.registry.entities[meter.eid["average_power"]]
        avg.unique_id = f"{_PULSE_HOME}_rt_average_power"
        with patch.object(sr_mod.er, "async_get", return_value=meter.registry):
            imp, _, _ = meter.reader._declared_split_grid_power(
                meter.reader._energy_dashboard_config)
        assert imp is None

    def test_role_for_needs_the_brand(self):
        assert lex.role_for("sensor", "power_consumption") is None
        assert lex.role_for("sensor", "power_production") is None
        assert lex.role_for("sensor", "power") is None
        assert lex.role_for("sensor", "power_consumption",
                            "p1_monitor") == "grid_import_power"
        assert lex.role_for("sensor", "power_production",
                            "p1_monitor") == "grid_export_power"
        assert lex.role_for("sensor", "power", "tibber") == "grid_import_power"
        assert lex.role_for("sensor", "power_consumption", "tibber") is None


def _crawler():
    spec = importlib.util.spec_from_file_location(
        "crawler_1222", ROOT / "scripts" / "crawl_integration_roster.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _strings_vocab(domain: str) -> dict:
    """What the crawler reads: strings.json's sensor keys plus the
    ``translation_key=`` literals in sensor.py (#1313: HA 2026.11 drops a
    name from strings.json when it equals the sensor type's own name)."""
    keys = set(json.loads((_ha_component(domain) / "strings.json").read_text())[
        "entity"]["sensor"])
    src = _ha_component(domain) / "sensor.py"
    if src.exists():
        keys |= set(re.findall(
            r'(?:^|\s)translation_key\s*=\s*["\']([a-z0-9_]{3,60})["\']',
            src.read_text()))
    return {"sensor": {k: {"options": ()} for k in sorted(keys)}}


class TestTheRosterCarriesThePair:
    def test_the_shipped_roster_declares_both_halves(self):
        vocab = roster_mod.ROLE_VOCAB["p1_monitor"]
        assert vocab["grid_import_power"]["keys"] == ("power_consumption",)
        assert vocab["grid_export_power"]["keys"] == ("power_production",)
        assert set(vocab) == {"grid_import_power", "grid_export_power"}
        assert roster_mod.ROSTER["p1_monitor"]["kind_from"] == "vocabulary"
        tibber = roster_mod.ROLE_VOCAB["tibber"]
        assert "power" in tibber["grid_import_power"]["keys"]
        assert "power_production" in tibber["grid_export_power"]["keys"]

    def test_p1_monitor_reads_as_energy_with_its_pair_only(self):
        """HA core's own P1 Monitor keys. Without the domain the crawler
        sees no anchor and no pair; with it, the pair and nothing beside it
        — not the phase rows, not the counters, not the prices."""
        crawler = _crawler()
        lexicon = crawler._lexicon()
        vocab = _strings_vocab("p1_monitor")
        assert crawler.classify_kind(vocab, lexicon, domain="x") == "other"
        assert crawler.classify_kind(vocab, lexicon,
                                     domain="p1_monitor") == "energy"
        roles = crawler.roles_from_vocabulary(vocab, lexicon, "energy",
                                              "p1_monitor")
        assert {r: v["keys"] for r, v in roles.items()} == {
            "grid_import_power": ("power_consumption",),
            "grid_export_power": ("power_production",),
        }

    def test_the_same_keys_in_another_brand_give_no_grid_role(self):
        crawler = _crawler()
        lexicon = crawler._lexicon()
        vocab = {"sensor": {k: {"options": ()} for k in (
            "power_consumption", "power_production", "power",
            "compressor_power", "flow_temperature")}}
        for domain in ("", "lambda_heat_pumps", "kia_uvo", "enphase_envoy"):
            roles = crawler.roles_from_vocabulary(vocab, lexicon, "energy",
                                                  domain)
            assert not {"grid_import_power", "grid_export_power",
                        "grid_power"} & set(roles), domain

    def test_the_tibber_pulse_pair_from_has_own_keys(self):
        crawler = _crawler()
        lexicon = crawler._lexicon()
        vocab = _strings_vocab("tibber")
        roles = crawler.roles_from_vocabulary(vocab, lexicon, "energy", "tibber")
        # Tibber's own strings.json also declares ``power_flow_from_grid``
        # (its home-battery flow sensor, a pre-#1222 "any" pattern) beside
        # the Pulse pair's ``power`` (the new #1222 brand_any match) — both
        # are real candidate keys, so ``keys`` carries both. ``exact_only``
        # stays just ``power``: nothing else ends in "_power_flow_from_grid".
        assert roles["grid_import_power"]["keys"] == (
            "power", "power_flow_from_grid")
        assert roles["grid_import_power"]["exact_only"] == ("power",)
        # Same shape the other way: Tibber's own ``power_flow_to_grid``
        # (pre-#1222 "any" pattern) sits beside ``power_production`` (the
        # new #1222 brand_any match).
        assert roles["grid_export_power"]["keys"] == (
            "power_flow_to_grid", "power_production")

    def test_the_names_are_has_own(self):
        """The premise, read from the installed core integrations: the keys
        are their own, and the translated names hold none of the English
        words the name search looks for."""
        words = sr_mod.IMPORT_PATTERNS + sr_mod.EXPORT_PATTERNS
        for domain, langs, keys in (
                ("p1_monitor", ("nl", "de", "fy"),
                 ("power_consumption", "power_production")),
                ("tibber", ("de", "sv"), ("power", "power_production"))):
            # the keys the integration declares, as the crawler reads them
            assert set(keys) <= set(_strings_vocab(domain)["sensor"]), domain
            for lang in langs:
                for key, name in _names(domain, lang, keys).items():
                    assert not any(w in _slug(name) for w in words), (
                        domain, lang, key, name)


class TestTheBrandRuleGuard:
    """``brand_any`` is a word that is the role in one brand only. Each one
    is a whole key, sits on a rule the crawler and ``role_for`` read
    through ``rule_any``, and names a brand the roster carries the role
    for — a rule nobody reads is a rule that silently does nothing."""

    def _brand_rules(self):
        for table in ("ROLE_RULES", "READ_ROLE_RULES"):
            for role, rule in getattr(lex, table).items():
                for domain, pats in (rule.get("brand_any") or {}).items():
                    yield table, role, domain, pats

    def test_every_brand_word_is_a_whole_key(self):
        found = list(self._brand_rules())
        assert found, "the guard must see the #1222 rules"
        for _, role, domain, pats in found:
            assert pats, (role, domain)
            for p in pats:
                assert p.startswith("^") and p.endswith("$"), (role, domain, p)

    def test_every_brand_word_reaches_the_roster(self):
        for _, role, domain, pats in self._brand_rules():
            keys = roster_mod.ROLE_VOCAB[domain][role]["keys"]
            assert any(re.search(p, k, re.I) for p in pats for k in keys), (
                role, domain)

    def test_only_the_tables_rule_any_reads_carry_brand_words(self):
        """Every other rule table is matched by code that never asks
        ``rule_any`` (hardware_detection's charger tables, the services)."""
        for name in dir(lex):
            table = getattr(lex, name)
            if name in ("ROLE_RULES", "READ_ROLE_RULES") or not isinstance(table, dict):
                continue
            for rule in table.values():
                if isinstance(rule, dict):
                    assert "brand_any" not in rule, name

    def test_no_matcher_reads_any_by_hand(self):
        """In the lexicon and the crawler, a regex loop over a rule's
        ``any`` goes through ``rule_any``; a loop that reads ``["any"]``
        itself would drop the brand words."""
        for path in (ROOT / "consts" / "role_lexicon.py",
                     ROOT / "scripts" / "crawl_integration_roster.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, (ast.comprehension, ast.For)):
                    continue
                it = node.iter
                if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) \
                        and it.func.attr == "get" and it.args \
                        and isinstance(it.args[0], ast.Constant):
                    key = it.args[0].value
                elif isinstance(it, ast.Subscript) and isinstance(it.slice, ast.Constant):
                    key = it.slice.value
                else:
                    continue
                assert key != "any", (path.name, getattr(node, "lineno", it.lineno))


class TestHA2611DroppedNames:
    """(#1313) HA 2026.11 drops a name from strings.json when it equals the
    sensor type's own name; the key lives on only as ``translation_key=`` in
    the platform module. The crawler must still see it, or the next roster
    built against 2026.11 loses Tibber's grid pair."""

    def test_a_key_only_in_the_code_is_still_in_the_vocabulary(self, monkeypatch):
        crawler = _crawler()
        strings = json.dumps({"entity": {"sensor": {
            "power_production": {"name": "Power production"}}}}).encode()
        sensor_py = (b'SensorEntityDescription(key="power", '
                     b'translation_key="power", native_unit_of_measurement="W")\n'
                     b'SensorEntityDescription(key="internal_only")\n')

        def fake_get(url, key, *, offline, ttl_s=0.0):
            if url.endswith("/strings.json"):
                return strings
            if url.endswith("/sensor.py"):
                return sensor_py
            return None

        monkeypatch.setattr(crawler, "_get", fake_get)
        vocab = crawler._mine_entity_vocabulary_raw("", "tibber", "core", offline=True)
        assert {"power", "power_production"} <= set(vocab["sensor"])
        # only translation_key literals join, never a bare key=
        assert "internal_only" not in vocab["sensor"]
