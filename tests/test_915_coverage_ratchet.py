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
        # (06.09 audit) every #915 test file, not the two the guard began
        # with — a new file that fetched would have passed unnoticed
        me = pathlib.Path(__file__).name
        paths = sorted(p for p in (ROOT / "tests").glob("test_915_*.py")
                       if p.name != me)      # this file names the tokens
        assert len(paths) >= 4, "premise: the #915 suites exist"
        for path in paths:
            text = path.read_text()
            assert not any(t in text for t in net), path.name
            assert "fetch_sources" not in text, path.name


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


@pytest.mark.unit
class TestTheMatrixAndTheRosterAgree:
    """(#915) The matrix is what SEM CLAIMS; the roster is what the ecosystem
    PUBLISHES. Checking one against the other is the only way to notice that a
    supported brand has become unnameable — or that SEM detects a platform its
    own documentation never mentions.
    """

    matrix = _load("hardware_matrix", "consts/hardware_matrix.py")

    @staticmethod
    def _detected_platforms() -> set:
        import re
        src = (ROOT / "hardware_detection.py").read_text()
        body = re.search(r"_EV_CHARGER_PLATFORMS\s*=\s*\[(.*?)\n\]",
                         src, re.S).group(1)
        return set(re.findall(r'\(\s*"([a-z0-9_]+)"', body))

    def _documented_domains(self) -> set:
        out = set()
        for row in self.matrix.CHARGERS:
            if row.get("domain_token"):
                out.add(row["domain_token"])
            out |= set(row.get("also_domains") or ())
        return out

    def test_every_detected_charger_platform_is_documented(self):
        """A platform SEM drives that no brand row names is a user who cannot
        find their own hardware in the docs. `goecharger_api2` and the
        archived `openwbmqtt` were both in that state."""
        missing = sorted(self._detected_platforms() - self._documented_domains())
        assert not missing, (
            f"{missing} is detected by _EV_CHARGER_PLATFORMS but no charger "
            "row names it — add domain_token/also_domains to the brand's row")

    def test_every_documented_charger_domain_is_detected(self):
        """…and the other way: a row claiming a domain nothing detects is a
        support claim with no code behind it."""
        extra = sorted(self._documented_domains() - self._detected_platforms())
        assert not extra, f"{extra} is documented but never detected"

    def test_every_charger_row_carries_its_domain(self):
        """One row in twenty-one had a `domain_token`, so the brand table and
        the detection list could drift apart with nothing noticing. The
        exemptions are paths, not integrations."""
        bare = sorted(r["brand"] for r in self.matrix.CHARGERS
                      if not r.get("domain_token"))
        assert bare == sorted(self.matrix.UNTOKENED_CHARGER_ROWS), bare

    #: Matrix domains that no public index carries, with the reason and the
    #: install count HA analytics DOES see. Each is a HACS custom repo (added
    #: by URL, so it is not in the store index the crawl reads) or a
    #: transport. All are brands SEM detects natively — the roster answers for
    #: hardware detection does NOT know, so their absence costs nothing at
    #: runtime. Shrink-only: see the test below.
    NOT_IN_ANY_PUBLIC_INDEX = {
        "alfen_wallbox": "HACS custom repo — 427 installs in analytics",
        "wattpilot": "HACS custom repo — 974 installs",
        "sonnenbatterie": "HACS custom repo — 577 installs",
        "e3dc_rscp": "HACS custom repo — 743 installs",
        "openwb2mqtt": "HACS custom repo — 374 installs",
        "openwbmqtt": "archived predecessor — 47 installs",
        "grott": "a Growatt MQTT proxy — 407 installs, no store entry",
        "mqtt": "a transport, opaque by construction",
        "homekit_controller": "a transport, opaque by construction",
    }

    def _claimed_domains(self) -> set:
        """Every HA domain the matrix says SEM is reached through — from the
        machine-readable fields only. The prose in `integration` is not
        parsed: "SolaX Modbus / Grott behind an ESPHome" yields `behind` and
        `an`, and a test that has to filter those cannot tell a missing brand
        from a stray word."""
        out = set(self._documented_domains())
        for row in self.matrix.ALL_ROWS:
            out |= set(row.get("domains") or ())
        return out

    def test_a_supported_brand_that_is_in_a_public_index_is_nameable(self):
        """Every domain the matrix claims must be in the roster, or listed
        above with the reason it cannot be. No shape filter: `sma`, `fronius`
        and `sessy` are one word each and are the rows most worth checking."""
        claimed = self._claimed_domains()
        assert len(claimed) > 40, (
            f"only {len(claimed)} domains parsed out of the matrix — the "
            "fields changed and this test stopped checking anything")
        unnameable = sorted(d for d in claimed
                            if d not in roster.ROSTER
                            and d not in self.NOT_IN_ANY_PUBLIC_INDEX)
        assert not unnameable, (
            f"{unnameable}: the matrix says SEM supports these and the roster "
            "cannot name them. Either the crawl regressed, or they left the "
            "public index — add them above WITH the reason, never bare.")

    def test_the_exemptions_are_still_needed(self):
        """Shrink-only: the day one of these reaches a public index, the
        exemption goes rather than quietly hiding a working row."""
        stale = sorted(d for d in self.NOT_IN_ANY_PUBLIC_INDEX
                       if d in roster.ROSTER)
        assert not stale, (
            f"{stale} is in the roster now — drop it from "
            "NOT_IN_ANY_PUBLIC_INDEX")

    def test_every_row_is_either_addressable_or_explained(self):
        """A row with no domain is reached some other way — generically
        through the Energy Dashboard, through MQTT discovery, through a car
        integration no index carries. That is fine, and it has to be SAID:
        otherwise a row whose integration quietly disappeared looks the same
        as one that never had a domain."""
        bare = sorted(r["brand"] for r in self.matrix.ALL_ROWS
                      if not r.get("domains") and not r.get("domain_token"))
        explained = (set(self.matrix.ROWS_WITH_NO_DOMAIN)
                     | set(self.matrix.UNTOKENED_CHARGER_ROWS))
        assert not set(bare) - explained, (
            f"{sorted(set(bare) - explained)} carries no domain and no reason")

    def test_the_claimed_domains_are_real(self):
        """A domain in the matrix that no index and no roster row knows is a
        typo, and a typo here silently switches a check off."""
        known = set(roster.ROSTER) | set(self.NOT_IN_ANY_PUBLIC_INDEX)
        assert not sorted(self._claimed_domains() - known)


@pytest.mark.unit
class TestNoBrandLosesARoleUnnoticed:
    """(#915) The guard the count ratchet is not.

    `--write --baseline` regenerates the counts in the same breath as the
    roster, so that ratchet cannot catch a regression its author introduces.
    Five times in one afternoon a new classifier marker deleted a working
    brand's roles — `brightness` took Zaptec, Peblar, SMA and Anker;
    `load_percent` took Growatt; `ups_` took Victron — and each was caught
    by diffing the roster BY HAND. This file is written only by
    `--roles-baseline`, so the roster can move and this cannot.
    """

    ROLES = json.loads((ROOT / "tests" / "roster_roles_baseline.json").read_text())["roles"]

    def test_every_domain_in_the_baseline_is_still_in_the_roster(self):
        gone = sorted(set(self.ROLES) - set(roster.ROLE_VOCAB))
        assert not gone, (
            f"{gone} had roles and now has none. If that is right, run "
            "`python3 scripts/crawl_integration_roster.py --roles-baseline` "
            "and say in the commit WHY the brand lost its vocabulary.")

    def test_no_role_vanished(self):
        lost = []
        for dom, roles in self.ROLES.items():
            now = roster.ROLE_VOCAB.get(dom, {})
            for role in roles:
                if role not in now:
                    lost.append(f"{dom}.{role}")
        assert not lost, (
            f"{lost} — a role a brand had is gone. Regenerate the roles "
            "baseline on purpose and say in the commit why.")

    def test_no_key_vanished_from_a_role(self):
        """A role may GAIN keys silently — that is the point of a refresh.
        Losing one is a lexicon edit that narrowed a brand, and it has to be
        said (the #810 narrowing was right, and it was said)."""
        lost = []
        for dom, roles in self.ROLES.items():
            for role, keys in roles.items():
                now = set(roster.ROLE_VOCAB.get(dom, {}).get(role, {}).get("keys", ()))
                missing = sorted(set(keys) - now)
                if missing:
                    lost.append(f"{dom}.{role}: {missing}")
        assert not lost, (
            f"{lost} — keys a brand's role had are gone. Regenerate the "
            "roles baseline on purpose and say in the commit why.")

    def test_the_baseline_is_not_written_by_write(self):
        """The whole value of this file is that `--write` cannot touch it."""
        src = (ROOT / "scripts" / "crawl_integration_roster.py").read_text()
        body = src[src.index("if args.roles_baseline"):]
        assert "write_roles_baseline" in body.split("if args.baseline")[0]
        assert "write_roles_baseline" not in src.split("if args.roles_baseline")[0].split("def main")[-1]


@pytest.mark.unit
class TestTheMatrixControlClaimsAgreeWithTheRoster:
    """(#915) The challenge Guido asked for, made permanent: does what the
    roster OFFERS agree with what the matrix CLAIMS about control?

    Run by hand on 06.09 it agreed on 3 of 14 inverter discharge-control
    claims and 2 of 14 charger current-control claims. The disagreements
    split cleanly: the matrix was stale twice (Fronius declares a discharge
    limit upstream; Zaptec declares `available_current`), the lexicon had
    missed three keys SEM's own discovery already drives (Wallbox, go-e
    APIv2, OpenEVSE), and the rest declare NOTHING control-shaped upstream —
    their control is a service, or a mechanism SEM's adapter implements
    itself. Each of those is listed below with the reason, and the list may
    only shrink: the day a brand declares its control, the exemption goes.
    """

    matrix = _load("hardware_matrix3", "consts/hardware_matrix.py")

    #: Inverter rows claiming discharge control whose integration declares
    #: no discharge-power-limit key upstream (checked 06.09.2026).
    DISCHARGE_NOT_DECLARED = {
        "Sungrow": "declares `charge_discharge_power` — a SIGNED forced "
                   "setpoint, not a limit; mapping it would write a limit "
                   "into a force register",
        "Enphase": "no control key declared (9 number/select keys, none "
                   "control-shaped)",
        "Tesla Powerwall": "core declares no number/select at all — control "
                           "is backup-reserve via the integration's own path",
        "Kostal Plenticore": "declares `battery_charge` and "
                             "`active_power_limitation`; neither is a "
                             "discharge limit",
        "SolarEdge": "solaredge_modbus_multi declares no keys; control is "
                     "storage_command_mode via its own path",
        "GoodWe": "declares `eco_mode_power` (a % of rated, adapter-specific) "
                  "and `battery_discharge_depth`; not a watt limit",
        "SolaX": "solax_modbus declares no keys (entity names set in code)",
        "DEYE / Sunsynk": "ha-solarman: entity names come from YAML "
                          "profiles, nothing declared",
        "Sofar": "ha-solarman, same",
        "Solis": "ha-solarman, same",
        "Sessy (battery)": "one declared control (the power strategy); the "
                           "setpoint is a service, not a number",
    }
    #: Charger rows saying "number entity" whose integration declares no
    #: current-control key upstream.
    CURRENT_NOT_DECLARED = {
        "JuiceBox 48": "JuiceBoxProxy over plain MQTT — opaque by construction",
        "Fronius / go-e Wattpilot": "HACS custom repo, not in the store index",
        "go-eCharger (HTTP)": "declares no number keys (names set in code)",
        "ChargePoint": "declares no number keys",
        "Heidelberg Energy Control": "declares `virtual_current` and "
                                     "`failsafe_current_command`; SEM's own "
                                     "discovery uses `requested_current`/"
                                     "`_amp` — no evidence which is the "
                                     "live control",
        "OpenWB 2.x": "HACS custom repo, not in the store index",
        "Ohme": "declares only `state_of_charge_input` as a number; current "
                "is set through its own path",
        "V2C Trydan": "declares 4 numbers, none current-shaped",
        "Alfen Eve": "HACS custom repo, not in the store index",
        "Blue Current": "core declares no numbers — power-only monitoring, "
                        "as SEM's own discovery says",
    }

    def _offers(self, doms, role):
        return any(role in roster.ROLE_VOCAB.get(d, {}) for d in doms)

    def test_every_inverter_discharge_claim_is_derived_or_explained(self):
        unexplained = []
        for row in self.matrix.INVERTERS:
            doms = row.get("domains") or []
            if not row.get("discharge_control") or not doms:
                continue
            if self._offers(doms, "battery_discharge_limit"):
                continue
            if row.get("discharge_control") == "declared":
                unexplained.append(f"{row['brand']} (declared, but the roster no longer offers it)")
                continue
            if row["brand"] not in self.DISCHARGE_NOT_DECLARED:
                unexplained.append(row["brand"])
        assert not unexplained, (
            f"{unexplained}: the matrix says SEM drives the discharge limit "
            "and the roster cannot derive it from what the integration "
            "declares — either the lexicon missed a declared key (add it, "
            "with the brand's own discovery as evidence) or nothing is "
            "declared (say so above)")

    def test_the_roster_never_offers_a_discharge_limit_the_matrix_denies(self):
        """The sharp direction. Both hits on 06.09 were the MATRIX being
        stale (Fronius), and it was corrected rather than exempted."""
        wrong = []
        for row in self.matrix.INVERTERS:
            doms = row.get("domains") or []
            if row.get("status") == "requested":
                continue          # a wish, not a claim either way
            # "declared" is the honest state for a roster-found key nobody
            # has confirmed live — it agrees with the roster by definition
            if not row.get("discharge_control") and self._offers(
                    doms, "battery_discharge_limit"):
                wrong.append(row["brand"])
        assert not wrong, (
            f"{wrong}: the roster offers a discharge limit the matrix says "
            "does not exist. If the key is real, the matrix is stale — fix "
            "the row; if it is not, the lexicon has a false positive")

    def test_every_charger_number_claim_is_derived_or_explained(self):
        unexplained = []
        for row in self.matrix.CHARGERS:
            doms = ([row["domain_token"]] if row.get("domain_token") else []
                    ) + list(row.get("also_domains") or ())
            if "number" not in row.get("control", "") or not doms:
                continue
            if self._offers(doms, "ev_current_control"):
                continue
            if row["brand"] not in self.CURRENT_NOT_DECLARED:
                unexplained.append(row["brand"])
        assert not unexplained, f"{unexplained}: see the inverter test"

    def test_the_roster_never_offers_a_current_control_the_matrix_denies(self):
        wrong = []
        for row in self.matrix.CHARGERS:
            doms = ([row["domain_token"]] if row.get("domain_token") else []
                    ) + list(row.get("also_domains") or ())
            if "number" not in row.get("control", "") and self._offers(
                    doms, "ev_current_control"):
                wrong.append(row["brand"])
        assert not wrong, f"{wrong}: Zaptec was this on 06.09 — the row was stale"

    def test_the_exemptions_are_still_needed(self):
        """Shrink-only: an exempted brand that now derives its control has
        to come off the list, so the list never hides a working brand."""
        by_brand = {r["brand"]: r for r in self.matrix.ALL_ROWS}
        stale = []
        for brand in self.DISCHARGE_NOT_DECLARED:
            doms = by_brand[brand].get("domains") or []
            if self._offers(doms, "battery_discharge_limit"):
                stale.append(brand)
        for brand in self.CURRENT_NOT_DECLARED:
            row = by_brand[brand]
            doms = ([row["domain_token"]] if row.get("domain_token") else []
                    ) + list(row.get("also_domains") or ())
            if self._offers(doms, "ev_current_control"):
                stale.append(brand)
        assert not stale, f"{stale} derives its control now — drop the exemption"

    def test_the_three_oracle_keys_are_derived(self):
        """The lexicon learned these from the matrix; pinned so the next
        tightening cannot silently unlearn them."""
        assert roster.ROLE_VOCAB["wallbox"]["ev_current_control"]["keys"] == (
            "maximum_charging_current",)
        assert "amp" in roster.ROLE_VOCAB["goecharger_api2"]["ev_current_control"]["keys"]
        assert "charge_rate" in roster.ROLE_VOCAB["openevse"]["ev_current_control"]["keys"]
        # …and the installation's contracted limit is NOT the charger's
        assert "maximum_icp_current" not in roster.ROLE_VOCAB["wallbox"][
            "ev_current_control"]["keys"]



@pytest.mark.unit
class TestOneBadUpstreamRowNeverKillsTheCrawl:
    """(06.09 audit) HACS aggregates thousands of independently maintained
    manifests. One malformed row used to raise out of ``candidate_rows`` and
    deny the whole refresh; a JSON ``NaN`` rendered as the bare name ``nan``
    in the generated module and made it unimportable; a long domain made a
    cache filename the filesystem refuses."""

    def _hacs(self, *rows):
        return {"hacs": {str(i): r for i, r in enumerate(rows)}}

    def test_a_malformed_manifest_or_topic_is_skipped_not_fatal(self):
        good = {"domain": "acme_x", "manifest": {"name": "Acme X"},
                "description": "a solar inverter", "full_name": "acme/x",
                "topics": [], "stargazers_count": 1}
        bad1 = {"domain": "bad_one", "manifest": ["not", "an", "object"],
                "description": "solar", "full_name": "x/y"}
        bad2 = {"domain": "bad_two", "manifest": {"name": "B"},
                "description": "solar", "full_name": "x/z", "topics": [123]}
        rows = crawler.candidate_rows(self._hacs(bad1, good, bad2))
        assert "acme_x" in rows
        assert "bad_one" not in rows and "bad_two" not in rows

    def test_json_nan_never_reaches_the_generated_module(self, tmp_path):
        """``json.loads`` accepts ``NaN``; ``repr(nan)`` is the bare name
        ``nan``, which is not a builtin — the module would raise NameError
        at import. The parser maps the token to None instead."""
        import json
        parsed = json.loads('{"full_name": NaN, "n": Infinity}',
                            parse_constant=lambda _c: None)
        assert parsed == {"full_name": None, "n": None}
        src = (ROOT / "scripts" / "crawl_integration_roster.py").read_text()
        assert src.count("parse_constant=lambda _c: None") == 2, (
            "both json.loads sites must reject NaN/Infinity")

    def test_a_long_domain_still_gets_a_valid_cache_name(self):
        path = crawler._cache_path("vocab_" + "x" * 5000 + "_abc")
        assert len(path.name) < 200
        # and it is stable
        assert path == crawler._cache_path("vocab_" + "x" * 5000 + "_abc")

    def test_mined_keys_and_options_are_bounded(self, monkeypatch):
        huge_key = "k" * (crawler._MAX_KEY_LEN + 1)
        raw = {"select": {"mode": {"options": [str(i) for i in range(100)]},
                          huge_key: {"options": ()}},
               "number": {"ok_key": {"options": ()}}}
        monkeypatch.setattr(crawler, "_mine_vocabulary_raw",
                            lambda *a, **k: raw)
        v = crawler.mine_vocabulary("r", "d", "hacs", offline=True)
        assert huge_key not in v["select"]
        assert len(v["select"]["mode"]["options"]) == crawler._MAX_OPTIONS
        assert "ok_key" in v["number"]
