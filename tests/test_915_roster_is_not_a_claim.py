"""#915 — the roster is a prior, not a support claim, and it says so in its shape.

`consts/hardware_matrix.py` is a claim about SEM's relationship to hardware:
every `tested-live` row must cite the issue or discussion it was proven on
(the #530 rule — web-research "support" is a false-positive generator, and
`tests/test_814_hardware_matrix.py` is the guard).

`consts/integration_roster.py` is a claim about the world: an integration with
this domain exists upstream, and here is what its own repository says it calls
things. Those are different kinds of statement and they must not be able to
turn into each other. This file makes the difference STRUCTURAL rather than a
convention someone has to remember:

* a roster row cannot carry a status, an evidence string or a confirmation —
  so it can never be read as support;
* a roster row cannot carry a SIGN CONVENTION, which is the one bug class this
  project has shipped repeatedly. The crawl is incapable of producing one (a
  `strings.json` declares names, never units or directions), and this test
  keeps it that way if someone tries to add the field by hand;
* a domain with no mined vocabulary contributes a display name and nothing
  else — the two-signal rule, mirroring `_census_energy_shaped()`;
* the transport platforms (`modbus`, `mqtt`, `esphome`, …) are absent, because
  their entity names are the USER's, not the integration author's (#869 Anker
  on the official modbus integration, #887 OnStar over MQTT). A declared-key
  match there would be pure name-guessing.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


roster = _load("integration_roster", "consts/integration_roster.py")
lexicon = _load("role_lexicon", "consts/role_lexicon.py")
matrix = _load("hardware_matrix", "consts/hardware_matrix.py")

_FORBIDDEN_CLAIM_KEYS = {"status", "evidence", "confirmed", "tested",
                         "tested_live", "supported", "verified"}
_FORBIDDEN_SIGN_KEYS = {"pattern", "grid_sign", "battery_sign", "sign",
                        "convention", "discharge_control"}


def _all_row_keys():
    for row in roster.ROSTER.values():
        yield from row
    for roles in roster.ROLE_VOCAB.values():
        yield from roles
        for body in roles.values():
            yield from body


@pytest.mark.unit
class TestItCannotBecomeAClaim:
    def test_no_row_carries_a_status_or_evidence(self):
        found = _FORBIDDEN_CLAIM_KEYS & set(_all_row_keys())
        assert not found, (
            f"the roster grew {found} — a status belongs in hardware_matrix.py "
            "where it needs a citation (#530)"
        )

    def test_no_row_carries_a_sign_convention(self):
        found = _FORBIDDEN_SIGN_KEYS & set(_all_row_keys())
        assert not found, (
            f"the roster grew {found} — a sign convention is a physical fact "
            "about one installation, measured from a reporter's export. A "
            "crawl cannot know it, and guessing it is the bug class this "
            "project has shipped repeatedly."
        )

    def test_the_module_says_what_it_is_not(self):
        doc = (ROOT / "consts" / "integration_roster.py").read_text()[:2000]
        assert "not a support matrix" in doc
        assert "hardware_matrix" in doc

    def test_the_matrix_still_has_exactly_four_tables(self):
        assert set(matrix.TABLES) == {
            "INVERTERS", "CHARGERS", "VEHICLES", "OTHER_DEVICES"}
        assert len(matrix.ALL_ROWS) == sum(len(t) for t in matrix.TABLES.values())

    def test_the_matrix_does_not_import_the_roster(self):
        src = (ROOT / "consts" / "hardware_matrix.py").read_text()
        assert "integration_roster" not in src, (
            "the two must stay separate kinds of claim; the crawl reaches the "
            "matrix only through a human filing an issue"
        )


@pytest.mark.unit
class TestTheTwoSignalRule:
    def test_a_keyword_only_row_proposes_nothing(self):
        """Signal 1 (the name looks energy-shaped) buys a display name. Only
        signal 2 (the integration's own declared vocabulary) may route a
        role — otherwise 'Battery Notes' becomes a home battery."""
        for domain, row in roster.ROSTER.items():
            if row["kind_from"] == "keyword":
                assert domain not in roster.ROLE_VOCAB, domain

    def test_every_vocabulary_row_says_so(self):
        for domain in roster.ROLE_VOCAB:
            assert roster.ROSTER[domain]["kind_from"] == "vocabulary", domain

    def test_kind_comes_from_a_closed_set(self):
        kinds = {r["kind"] for r in roster.ROSTER.values()}
        assert kinds <= {"energy", "vehicle", "appliance", "other"}, kinds

    def test_a_car_never_carries_a_home_battery_role(self):
        """A Porsche declares `target_soc`; read as a home pack's target it is
        nonsense. Vehicles contribute vehicle roles only."""
        for domain, row in roster.ROSTER.items():
            if row["kind"] != "vehicle":
                continue
            roles = set(roster.ROLE_VOCAB.get(domain, {}))
            assert roles <= set(lexicon.VEHICLE_ROLE_RULES), (domain, roles)


    def test_a_non_energy_domain_contributes_nothing(self):
        for domain, row in roster.ROSTER.items():
            if row["kind"] in ("appliance", "other"):
                assert domain not in roster.ROLE_VOCAB, domain


@pytest.mark.unit
class TestTheBoundaries:
    def test_opaque_platforms_are_absent(self):
        """The official `modbus` integration names entities from the user's
        own YAML and `mqtt` is one transport carrying many brands. A key match
        there is guessing, so they may not be in the roster at all."""
        for platform in lexicon.OPAQUE_PLATFORMS:
            assert platform not in roster.ROSTER, platform

    def test_sem_is_not_in_its_own_roster(self):
        assert "solar_energy_management" not in roster.ROSTER

    def test_every_role_is_one_the_lexicon_defines(self):
        known = (set(lexicon.ROLE_RULES) | set(lexicon.READ_ROLE_RULES)
                 | set(lexicon.VEHICLE_ROLE_RULES))
        for domain, roles in roster.ROLE_VOCAB.items():
            assert set(roles) <= known, (domain, set(roles) - known)

    def test_every_role_body_has_keys_on_its_declared_platform(self):
        rules = {**lexicon.ROLE_RULES, **lexicon.READ_ROLE_RULES,
                 **lexicon.VEHICLE_ROLE_RULES}
        for domain, roles in roster.ROLE_VOCAB.items():
            for role, body in roles.items():
                assert body["keys"], (domain, role)
                assert body["platform"] == rules[role]["platform"], (domain, role)

    def test_the_roster_is_dated_and_names_its_sources(self):
        meta = roster.ROSTER_META
        assert meta["generated_at"].endswith("Z")
        assert meta["sources"], "a prior with no provenance is a rumour"
        assert roster.SCHEMA == 1
