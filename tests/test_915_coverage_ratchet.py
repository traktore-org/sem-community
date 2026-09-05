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
                 "number": {"quick_charge_duration": {}},
                 "sensor": {"battery_soc": {}}}
        assert "battery_force_charge" not in self._roles(timed, "energy")
        # (the battery sensor is not decoration: a battery role now needs a
        # battery in the vocabulary — see BATTERY_CONTEXT)
        durable = {"switch": {"ac_charge": {}},
                   "sensor": {"battery_soc": {}}}
        assert self._roles(durable, "energy")["battery_force_charge"][
            "keys"] == ("ac_charge",)

    def test_an_ev_chargers_nameplate_is_not_the_systems(self):
        """Huawei declares ``charger_rated_power`` beside
        ``inverter_rated_power``; sorted first, it would have reported a 7 kW
        house on a 10 kW inverter."""
        roles = self._roles({"sensor": {"charger_rated_power": {},
                                        "inverter_rated_power": {}}}, "energy")
        assert roles["system_size_spec"]["keys"] == ("inverter_rated_power",)


@pytest.mark.unit
class TestTheClosedHardwareIssuesAgree:
    """(#75-#81, #816) Seven closed hardware-support issues where a human
    read the integration and wrote down what it exposes. The crawler must
    reach the same verdicts from the source alone — and the sharp half is
    the NEGATIVE one: five of the seven say "no control exists", and a
    roster that invented one would be contradicting a person who looked.
    """

    def test_the_wall_connector_is_a_charger_with_nothing_to_drive(self):
        """#75: "No current control — no number entity, no service to set
        charging amps." The crawler classifies it as a CHARGER from
        `vehicle_connected` / `session_energy_wh` / `contactor_closed`, and
        proposes nothing. 6555 installs — more than KEBA, Zaptec or Wallbox
        — and it was invisible until core's nested brands were walked."""
        row = roster.ROSTER.get("tesla_wall_connector")
        assert row, "hidden again: core sub-integrations are nested by brand"
        assert row["kind"] == "charger"
        assert not roster.ROLE_VOCAB.get("tesla_wall_connector")

    def test_garo_is_named_and_still_manual(self):
        """#816: GARO proven live, still manual-only."""
        row = roster.ROSTER.get("garo_wallbox")
        assert row and row["kind"] == "charger"
        assert not roster.ROLE_VOCAB.get("garo_wallbox")

    def test_a_brands_sub_integrations_are_not_hidden(self):
        """Tesla carries `powerwall`, `tesla_wall_connector` and
        `tesla_fleet` in a nested dict and appears at top level as a name
        only. Iterating the top level alone hid 241 core integrations —
        including Tesla Powerwall, whose sign convention is in SEM's own
        table."""
        assert "powerwall" in roster.ROSTER
        assert roster.ROSTER["powerwall"]["origin"] == "core"

    def test_popularity_buys_a_question_not_an_answer(self):
        """A core integration above the install floor gets ASKED what it
        declares even when its name has no energy word in it ("Wall
        Connector"). What it answers still decides whether it may route
        anything — Tesla's answer is: nothing."""
        src = (ROOT / "scripts" / "crawl_integration_roster.py").read_text()
        assert "POPULAR_FLOOR" in src.split("core_index = ")[1][:2000], (
            "the core branch stopped consulting the install floor")


@pytest.mark.unit
class TestOneWordDoesNotDecideADevice:
    """Both directions of the same error, found on the same afternoon."""

    lexicon = _load("role_lexicon2", "consts/role_lexicon.py")

    def _kind(self, vocab, dom=""):
        return crawler.classify_kind(vocab, self.lexicon, domain=dom)

    def test_a_house_is_not_a_car_because_a_car_is_plugged_into_it(self):
        """Victron's GX declares `ev_odometer` for the vehicle at its EV
        charger — one key out of 465 — and that single word discarded 464
        keys of inverter and battery vocabulary."""
        vocab = {"sensor": {"ev_odometer": {}, "battery_power": {},
                            "grid_power": {}, "pv_power": {}},
                 "number": {"system_ess_max_charge_power": {}}}
        assert self._kind(vocab) == "energy"

    def test_a_marketplace_is_not_a_house_because_one_product_is(self):
        """Midea's cloud is 1095 keys of fridges, dryers and ice makers with
        a single `inverter` (an inverter air conditioner). First-match on
        the house side claimed the lot."""
        vocab = {"sensor": {"inverter": {}, "storage_door_state": {},
                            "dishwasher_state": {}, "oven_mode": {},
                            "kettle_status": {}}}
        assert self._kind(vocab) == "appliance"

    def test_a_ups_input_is_not_sunshine(self):
        """Network UPS Tools, 23568 installs, declares `input_power` — the
        MAINS feed. Read as solar it would have told SEM the sun shines out
        of a wall socket."""
        vocab = {"sensor": {"input_power": {}, "battery_runtime": {},
                            "battery_charge": {}}}
        assert self._kind(vocab) == "appliance"
        assert not crawler.roles_from_vocabulary(
            vocab, self.lexicon, self._kind(vocab))

    def test_a_battery_role_needs_a_battery(self):
        """`work_mode` is `work_mode`: no key-level pattern separates an air
        conditioner's from a battery's. The vocabulary around it does."""
        no_battery = {"select": {"operation_mode": {}},
                      "sensor": {"room_temperature": {}}}
        assert "battery_strategy" not in crawler.roles_from_vocabulary(
            no_battery, self.lexicon, "energy")
        with_battery = {"select": {"operation_mode": {}},
                        "sensor": {"battery_soc": {}}}
        assert "battery_strategy" in crawler.roles_from_vocabulary(
            with_battery, self.lexicon, "energy")

    def test_an_integration_may_be_both(self):
        """Tesla's Fleet API speaks for the car and the Powerwall through one
        vocabulary; forcing one verdict threw away a half either way."""
        vocab = {"sensor": {"solar_power": {}, "grid_power": {},
                            "battery_power": {}, "odometer": {},
                            "charge_state_battery_range": {}}}
        roles = crawler.roles_from_vocabulary(vocab, self.lexicon, "energy")
        assert roles["solar_power"]["keys"] == ("solar_power",)
        assert roles["vehicle_range"]["keys"] == ("charge_state_battery_range",)

    def test_a_cars_charge_limit_is_not_the_houses_target(self):
        """`charge_state_*` is Tesla's VEHICLE namespace."""
        assert self.lexicon.role_for(
            "number", "charge_state_charge_limit_soc") != "battery_target_soc"
