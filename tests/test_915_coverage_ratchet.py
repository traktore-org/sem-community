"""#915 — the coverage ratchet: how many energy-shaped integrations can SEM
not even NAME?

`unnamed_over_floor` is the number this arc exists to move. It shrinks when
SEM learns a brand and grows only when the ecosystem does — and a refresh
commit has to say which. The number is computed from the COMMITTED roster,
never from the live network, so CI never depends on the internet and the
board can never go red on a day nobody touched the code.

Same shape as the other shrink-only ratchets in this repo
(`tests/brand_footprint_baseline.json`, `tests/option_surface_baseline.json`):
a shrink also fails, because a win that nobody records is a win nobody can
see.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = json.loads((ROOT / "tests" / "roster_coverage_baseline.json").read_text())


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


roster = _load("integration_roster", "consts/integration_roster.py")
crawler = _load("crawler", "scripts/crawl_integration_roster.py")


def _gap() -> list:
    return crawler.backlog(roster.ROSTER, roster.ROLE_VOCAB)


@pytest.mark.unit
class TestTheRatchet:
    def test_the_baseline_describes_the_committed_roster(self):
        assert BASELINE["roster_rows"] == len(roster.ROSTER)
        assert BASELINE["domains_with_roles"] == len(roster.ROLE_VOCAB)
        assert BASELINE["roles_mined"] == sum(
            len(v) for v in roster.ROLE_VOCAB.values())

    def test_the_unnamed_count_matches_the_roster(self):
        floor = BASELINE["install_floor"]
        live = sum(1 for row in _gap() if row[2] >= floor)
        assert live == BASELINE["unnamed_over_floor"], (
            f"the gap is {live}, the baseline says "
            f"{BASELINE['unnamed_over_floor']} — regenerate with "
            "`python3 scripts/crawl_integration_roster.py --refresh --baseline` "
            "and say in the commit whether SEM learned a brand or the "
            "ecosystem grew one"
        )

    def test_the_top_gap_is_still_unknown_to_sem(self):
        """Every domain the backlog names must genuinely be one SEM cannot
        place — if one of them became supported, the ratchet is stale."""
        known = crawler.sem_known_domains()
        still_unknown = [d for d in BASELINE["top_gap"] if d not in known]
        assert still_unknown == BASELINE["top_gap"], (
            f"{set(BASELINE['top_gap']) - set(still_unknown)} is supported now "
            "— regenerate the baseline, the ratchet shrank"
        )

    def test_the_backlog_is_not_a_roadmap(self):
        """It is developer output: a ranked question, never a promise. It is
        printed on demand and only the count is committed — there is no
        generated docs page for it."""
        assert not (ROOT / "docs" / "COVERAGE_BACKLOG.md").exists()
        assert "shrink-only" in " ".join(BASELINE["_comment"]).lower()


@pytest.mark.unit
class TestTheCrawlerNeverRunsInCI:
    def test_offline_is_the_default_for_every_reader(self):
        """Nothing in the test suite may reach the network. The crawler's
        network calls live behind `_get(..., offline=...)`, and every test
        here reads the committed artefact instead."""
        src = (ROOT / "scripts" / "crawl_integration_roster.py").read_text()
        assert "urlopen" in src, "premise: the crawler is the networked file"
        net = ("urlopen", "requests.", "aiohttp", "httpx")
        for path in ("tests/test_915_roster_rediscovery.py",
                     "tests/test_915_roster_is_not_a_claim.py"):
            text = (ROOT / path).read_text()
            assert not any(t in text for t in net), path
            assert "fetch_sources" not in text, path


@pytest.mark.unit
class TestAForkIsTheSameHardware:
    """(#869) `anker_solix_official` reports ZERO installs and describes
    itself as "local Modbus TCP" — no energy keyword, no popularity, so both
    candidate gates missed it while a reporter was running it. A domain that
    extends an accepted domain's name is that brand by another maintainer,
    and it is mined regardless of what analytics says about it.
    """

    def _sources(self):
        def hacs(dom, name, desc, full_name):
            return {"domain": dom, "manifest": {"name": name},
                    "description": desc, "full_name": full_name,
                    "topics": [], "stargazers_count": 1}
        # The parent qualifies on its DESCRIPTION; the fork's domain, name
        # and description carry no energy word at all — which is the whole
        # reason it was invisible. Anything that reaches it here reached it
        # through the sibling rule and nothing else.
        return {"hacs": {
            "1": hacs("acme_x", "Acme X", "a solar inverter", "acme/ha-acme"),
            "2": hacs("acme_x_official", "Acme X Official",
                      "local Modbus TCP", "acme/ha-acme-official"),
            "3": hacs("unrelated_thing", "Unrelated", "a doorbell", "x/y"),
        }}

    def test_a_fork_of_a_candidate_becomes_one(self):
        rows = crawler.candidate_rows(self._sources())
        assert "acme_x" in rows, "the parent must qualify on its own"
        assert rows["acme_x_official"]["by"] == "sibling:acme_x"

    def test_it_does_not_drag_in_the_rest_of_the_index(self):
        assert "unrelated_thing" not in crawler.candidate_rows(self._sources())

    def test_a_bare_prefix_is_not_a_sibling(self):
        """`acme_x` must not adopt `acme_xylophone` by string luck — the
        boundary is a domain SEGMENT, so the parent's name plus `_`."""
        src = self._sources()
        src["hacs"]["4"] = {"domain": "acme_xylophone", "manifest": {
            "name": "Acme Xylophone"}, "description": "tanning beds",
            "full_name": "x/z", "topics": [], "stargazers_count": 0}
        assert "acme_xylophone" not in crawler.candidate_rows(src)

    def test_the_reporters_integration_is_in_the_shipped_roster(self):
        """The whole point, pinned: #869 runs this one."""
        assert "anker_solix_official" in roster.ROSTER
        assert roster.ROSTER["anker_solix_official"]["kind_from"] == "vocabulary"


@pytest.mark.unit
class TestAChargerIsNotAHouse:
    """A wallbox's ``state_of_charge`` is the CAR's. Read as the house pack's
    it would feed SEM's energy balance a number that has nothing to do with
    the building — every ten seconds, silently, and plausibly enough that
    nobody would look. So a charger contributes its own controls and what it
    knows about the vehicle, and no house reads at all.
    """

    lexicon = _load("role_lexicon", "consts/role_lexicon.py")

    def _roles(self, vocab, kind):
        return crawler.roles_from_vocabulary(vocab, self.lexicon, kind)

    def test_sems_own_charger_list_decides(self):
        doms = crawler.sem_charger_domains()
        assert {"wallbox", "zaptec", "keba", "easee"} <= doms
        assert crawler.classify_kind(
            {"sensor": {"state_of_charge": {}}}, self.lexicon,
            domain="wallbox") == "charger"

    def test_an_unlisted_box_is_read_from_its_own_vocabulary(self):
        vocab = {"sensor": {"charging_session_energy": {}},
                 "number": {"charge_current_limit": {}}}
        assert crawler.classify_kind(
            vocab, self.lexicon, domain="brand_new_evse") == "charger"

    def test_a_generator_with_a_socket_is_still_a_generator(self):
        """Anker Solix declares an EV current limit beside a real PV input
        and a real pack. Calling it a charger would throw away the house
        reads that are the reason SEM wants it."""
        vocab = {"sensor": {"pv_power": {}, "state_of_charge": {}},
                 "number": {"max_evcharge_current": {}}}
        assert crawler.classify_kind(
            vocab, self.lexicon, domain="anker_solix") == "energy"

    def test_a_chargers_state_of_charge_is_the_cars(self):
        roles = self._roles({"sensor": {"state_of_charge": {}}}, "charger")
        assert "battery_soc" not in roles
        assert roles["vehicle_soc"]["keys"] == ("state_of_charge",)

    def test_a_charger_offers_no_house_battery_control(self):
        """SMA's EV charger declares ``charge_power_limit`` — the CAR's
        charge rate, one word away from the house pack's."""
        roles = self._roles({"number": {"charge_power_limit": {},
                                        "charge_current_limit": {}}},
                            "charger")
        assert "battery_charge_limit" not in roles
        assert roles["ev_current_control"]["keys"] == ("charge_current_limit",)

    def test_the_shipped_roster_has_no_house_reads_on_a_charger(self):
        house = {"battery_soc", "battery_power", "solar_power", "grid_power",
                 "battery_charge_limit", "battery_discharge_limit",
                 "battery_target_soc", "battery_strategy",
                 "battery_force_charge"}
        for dom, row in roster.ROSTER.items():
            if row.get("kind") != "charger":
                continue
            assert not (set(roster.ROLE_VOCAB.get(dom, {})) & house), dom

    def test_range_added_is_not_range_remaining(self):
        """``added_range`` is what THIS session put in; SEM asks what the car
        has LEFT and would read the first as an almost-empty battery."""
        roles = self._roles({"sensor": {"added_range": {},
                                        "remaining_range": {}}}, "vehicle")
        assert roles["vehicle_range"]["keys"] == ("remaining_range",)

    def test_a_switch_that_expires_is_not_a_force_charge(self):
        """EG4 declares ``quick_charge`` beside ``quick_charge_duration`` —
        a 60-minute boost. SEM's force charge has to hold for as long as the
        cheap hours last, so a switch that turns itself off is the wrong
        shape and proposing nothing is the right answer."""
        timed = {"switch": {"quick_charge": {}},
                 "number": {"quick_charge_duration": {}}}
        assert "battery_force_charge" not in self._roles(timed, "energy")
        durable = {"switch": {"ac_charge": {}}}
        assert self._roles(durable, "energy")["battery_force_charge"][
            "keys"] == ("ac_charge",)

    def test_an_ev_chargers_nameplate_is_not_the_systems(self):
        """Huawei declares ``charger_rated_power`` beside
        ``inverter_rated_power``; sorted first, it would have reported a 7 kW
        house on a 10 kW inverter."""
        roles = self._roles({"sensor": {"charger_rated_power": {},
                                        "inverter_rated_power": {}}}, "energy")
        assert roles["system_size_spec"]["keys"] == ("inverter_rated_power",)
