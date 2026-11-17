"""#915 — the crawler, run on every listed brand's OWN entity names.

``consts/hardware_matrix.py`` says what SEM supports. ``consts/integration_roster.py``
carries, per HA integration, the entity keys the integration publishes in its
own repository. This test joins the two and asks, per listed brand: do the
roles this KIND of device needs come out of the real role rules when they are
fed those keys?

* join: a matrix row names its HA domains (``domains`` / ``domain_token`` /
  ``also_domains``); a row with none is mapped by ``_DOMAIN_FOR_ROW`` below
  or has no names to test.
* names: a domain has names when the roster holds role-matched keys for it or
  read its repository vocabulary. Transport platforms, cloud-only rows and
  integrations nobody mined are COUNTED as "no names", never failed.
* roles: every mined ``(platform, key)`` goes through the lexicon rules
  (``role_for`` + the charger, vehicle and service tables), whatever role the
  roster stored for it — the roster is not trusted to mark its own homework.
* ratchet: ``tests/crawler_brand_coverage_baseline.json`` lists the brands
  that find everything they need. A brand may move missing -> found (update
  the baseline); never back.

Brands appear here as DATA only. Nothing in a generic file names one.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re


from .ratchet_guard import assert_not_loosened

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "crawler_brand_coverage_baseline.json"
REGEN = ("Regenerate with: SEM_WRITE_CRAWLER_COVERAGE=1 semtest "
         "tests/test_crawler_every_listed_brand.py")


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


matrix = _load("hardware_matrix", "consts/hardware_matrix.py")
roster = _load("integration_roster", "consts/integration_roster.py")
lex = _load("role_lexicon", "consts/role_lexicon.py")

#: Rows that carry no domain but are reached through one integration. Empty
#: on purpose: every row without a domain says why in ``ROWS_WITH_NO_DOMAIN``
#: (MQTT, ESPHome, a local integration) — none is an integration of the
#: roster, and guessing one would test the wrong names.
_DOMAIN_FOR_ROW: dict = {}

#: Domains that are only a transport: there is no brand vocabulary in them.
_TRANSPORT = frozenset({"mqtt", "modbus", "esphome", "homekit_controller"})

#: Rows that are a battery, not an inverter: they need the pack, not the PV.
_BATTERY_ROWS = frozenset({"Sessy (battery)", "Victron Multiplus II BESS"})

#: Rows read through the Energy Dashboard map, whose names are the user's own.
_ENERGY_DASHBOARD = "ED"

_GRID = ({"grid_power"}, {"grid_import_power", "grid_export_power"})


def _needs(table: str, row: dict) -> list:
    """Role groups a kind needs; each group is satisfied by ANY alternative
    (a set of roles that must ALL be found)."""
    if table == "INVERTERS" and row["brand"] in _BATTERY_ROWS:
        return [[{"battery_soc"}], [{"battery_power"}]]
    if table == "INVERTERS":
        return [[{"solar_power"}], list(_GRID)]
    if table == "CHARGERS":
        return [[{"ev_current_control"}]]
    if table == "VEHICLES":
        return [[{"vehicle_soc"}]]
    role = str(row.get("role", ""))
    if "heat pump" in role:
        return [[{"heat_pump_heat_energy"}]]
    if "meter" in role or "grid" in role:
        return [list(_GRID)]
    return []


def _domains(table: str, row: dict) -> tuple:
    ds = list(row.get("domains") or ())
    if row.get("domain_token"):
        ds.append(row["domain_token"])
    ds += list(row.get("also_domains") or ())
    ds += list(_DOMAIN_FOR_ROW.get(row["brand"], ()))
    return tuple(dict.fromkeys(ds))


def _resolve(platform: str, key: str, domain: str) -> set:
    """Every role the lexicon gives a published key. Mirrors the crawler's
    own order: entity rules, charger-only words, vehicle rules, services."""
    roles = set()
    if platform == "service":
        for role, rule in lex.SERVICE_ROLE_RULES.items():
            if any(re.search(p, key, re.I) for p in rule["any"]):
                roles.add(role)
        return roles
    hit = lex.role_for(platform, key, domain)
    if hit:
        roles.add(hit)
    tables = (lex.VEHICLE_ROLE_RULES, {r: v for r, v in lex.ROLE_RULES.items()
                                       if r.startswith("ev_")})
    for rules in tables:
        for role, rule in rules.items():
            if rule["platform"] != platform:
                continue
            pats = tuple(lex.rule_any(rule, domain)) + tuple(rule.get("charger_only_any", ()))
            if any(re.search(p, key, re.I) for p in rule.get("not", ())):
                continue
            if any(re.search(p, key, re.I) for p in pats):
                roles.add(role)
    return roles


def found_roles(vocab: dict, domain: str = "") -> set:
    """Roles the crawler finds in ``{role: {platform, keys}}`` mined keys."""
    out: set = set()
    for body in vocab.values():
        for key in body.get("keys", ()):
            out |= _resolve(body["platform"], key, domain)
    return out


def _satisfied(needs: list, found: set) -> list:
    """The need groups with no alternative fully found."""
    return [[sorted(a) for a in alts] for alts in needs
            if not any(a <= found for a in alts)]


def _has_names(domain: str) -> bool:
    if domain in _TRANSPORT:
        return False
    row = roster.ROSTER.get(domain)
    if not row:
        return False
    return bool(roster.ROLE_VOCAB.get(domain)) or \
        str(row.get("kind_from", "")).startswith("vocabulary")


def evaluate() -> dict:
    """{key: {...}} for every listed row, plus a verdict."""
    out: dict = {}
    for table, rows in matrix.TABLES.items():
        for row in rows:
            key = f"{table}/{row['brand']}"
            needs = _needs(table, row)
            doms = _domains(table, row)
            named = [d for d in doms if _has_names(d)]
            entry = {"status": row["status"], "domains": list(doms)}
            if not needs:
                entry["verdict"] = "no_roles_needed"
            elif row.get("pattern") == _ENERGY_DASHBOARD and row["brand"] not in _BATTERY_ROWS:
                entry["verdict"] = "energy_dashboard"
            elif not named:
                entry["verdict"] = "no_names"
            else:
                found: set = set()
                for d in named:
                    found |= found_roles(roster.ROLE_VOCAB.get(d, {}), d)
                miss = _satisfied(needs, found)
                entry["verdict"] = "missing" if miss else "found"
                entry["missing"] = miss
            out[key] = entry
    return out


def _snapshot() -> dict:
    ev = evaluate()
    by = lambda v: sorted(k for k, e in ev.items() if e["verdict"] == v)  # noqa: E731
    return {
        "found": by("found"),
        "missing": {k: ev[k]["missing"] for k in by("missing")},
        "no_names": by("no_names"),
        "energy_dashboard": by("energy_dashboard"),
        "no_roles_needed": by("no_roles_needed"),
        "total": len(ev),
    }


# --- the join and the instrument ------------------------------------------

def test_every_matrix_row_is_joined_or_counted():
    snap = _snapshot()
    n = (len(snap["found"]) + len(snap["missing"]) + len(snap["no_names"])
         + len(snap["energy_dashboard"]) + len(snap["no_roles_needed"]))
    assert n == snap["total"] == len(matrix.ALL_ROWS)


def test_the_crawler_finds_the_confirmed_brands_roles():
    """Not vacuous: brands confirmed on real hardware whose roles the roster
    holds must come out found."""
    found = set(_snapshot()["found"])
    for brand in ("INVERTERS/Huawei Solar", "INVERTERS/SMA", "INVERTERS/SolarEdge",
                  "CHARGERS/KEBA P30/P40"):
        assert brand in found, brand


def test_a_broken_key_set_finds_nothing():
    junk = {"x": {"platform": "sensor", "keys": ("zzz_foo", "qwerty", "")},
            "y": {"platform": "number", "keys": ("lorem_ipsum",)},
            "z": {"platform": "service", "keys": ("nothing.at_all",)}}
    assert found_roles(junk, "huawei_solar") == set()
    assert _satisfied(_needs("INVERTERS", {"brand": "x"}), set()) != []


def test_the_instrument_does_find_a_role_it_is_given():
    vocab = {"a": {"platform": "number", "keys": ("charger_max_current",)}}
    assert "ev_current_control" in found_roles(vocab, "zaptec")
    assert _satisfied([[{"ev_current_control"}]], {"ev_current_control"}) == []


# --- the ratchet ----------------------------------------------------------

def test_brands_that_find_their_roles_never_stop_finding_them():
    snap = _snapshot()
    if os.environ.get("SEM_WRITE_CRAWLER_COVERAGE"):
        # semtest runs a COPY of the tree; write where the source lives
        dest = pathlib.Path(os.environ.get("SEM_SRC", ROOT)) / "tests" / BASELINE.name
        dest.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n")
        BASELINE.write_text(dest.read_text())
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    lost = sorted(set(base["found"]) - set(snap["found"]))
    assert not lost, (f"{lost} found every needed role before and no longer "
                      f"do: the crawler or the roster regressed. {REGEN}")
    gained = sorted(set(snap["found"]) - set(base["found"]))
    assert not gained, (f"{gained} now find their roles. Update the baseline "
                        f"so it cannot go back. {REGEN}")
    assert set(snap["missing"]) <= set(base["missing"]) | set(gained), (
        "a brand with names now misses roles it was not listed as missing; "
        + REGEN)
    assert_not_loosened(BASELINE, lambda d: len(d["missing"]), "crawler brand coverage")
