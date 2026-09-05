#!/usr/bin/env python3
"""#915 — build SEM's integration roster from what the ecosystem publishes.

SEM has always learned hardware the same way: somebody installs a brand SEM
cannot place, the census names the gap on their screen, they file an issue, a
human writes a detection row. That works and it is slow, and it means a brand
nobody has reported is a brand SEM cannot recognise even when the integration
for it has thousands of installs.

This crawler removes the *waiting* from that loop, not the confirmation.

It reads five public indexes (HACS, HA analytics, HA core, the HA website) to
learn which integrations exist, what they are called and how many people run
them — and then, for the energy-shaped ones, it reads each integration's OWN
repository for the entity vocabulary it declares. An integration that ships

    "entity": {"number": {"storage_maximum_discharging_power": {...}}}

has told the world, in its own words, what it will create. SEM learned that
exact key from a live German Huawei install (#845/#848). The miner re-derives
it offline, and the same for Zaptec's phase-switch register (learned in #804)
and Sessy's ``api/eco/nom/idle`` strategy options (learned in #523). That
rediscovery is the oracle: an approach that re-finds what we know by hand has
earned the right to propose for hardware nobody has run yet.

WHAT THIS MAY AND MAY NOT PRODUCE
---------------------------------
It produces a PRIOR: a name for a domain, a rank by install count, and a set
of declared keys that MIGHT play a SEM role. Every runtime use of that prior
is an intersection with the local entity registry, so it can never invent
hardware — only mislabel a role, which the user then confirms or corrects.

It cannot produce a unit, a device class or a SIGN CONVENTION: those are
physical facts about one installation and are declared nowhere upstream. That
is the guardrail rather than the limitation — the one bug class this project
has shipped repeatedly cannot be reintroduced by a mechanism incapable of
expressing it. Support claims stay in ``consts/hardware_matrix.py``, where a
row needs a citation (the #530 rule).

USAGE
-----
    python3 scripts/crawl_integration_roster.py --refresh --write
    python3 scripts/crawl_integration_roster.py --backlog
    python3 scripts/crawl_integration_roster.py --offline --write   # cache only
    python3 scripts/crawl_integration_roster.py --refresh --baseline

Raw upstream snapshots are cached OUTSIDE the repo (~/.cache/sem-crawl) — they
are ten megabytes, they change daily, and committing them would guarantee rot.
The generated module and the ratchet are the committed record, and they are
deterministic given a cache.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import functools
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, Optional, Tuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = pathlib.Path(
    os.environ.get("SEM_CRAWL_CACHE", pathlib.Path.home() / ".cache" / "sem-crawl")
)
UA = "sem-community/roster-crawler (+https://github.com/traktore-org/sem-community)"

#: The five indexes. All static JSON, no auth, no rate limit — and all five
#: 403 without a User-Agent (the analytics CDN in particular).
SOURCES: Dict[str, str] = {
    "hacs": "https://data-v2.hacs.xyz/integration/data.json",
    "custom_installs": "https://analytics.home-assistant.io/custom_integrations.json",
    "core_analytics": "https://analytics.home-assistant.io/data.json",
    "core_index": ("https://raw.githubusercontent.com/home-assistant/core/dev/"
                   "homeassistant/generated/integrations.json"),
    "website": "https://www.home-assistant.io/integrations.json",
}

#: Signal 1 — the domain LOOKS energy-shaped. Never sufficient on its own;
#: see ``build_roster`` for the two-signal rule.
_KEYWORDS = re.compile(
    r"\b(solar|photovolta|\bpv\b|inverter|wallbox|evse|\bess\b|"
    r"heat ?pump|smart meter|power meter|energy meter|electricity price|"
    r"tariff|energy monitor|(home|house|energy) batter|batter(y|ie)s? "
    r"(storage|system|management)|(ev|car|vehicle) charg|charging station|"
    r"energy storage|grid (meter|price|power))", re.I)

#: Names that match the keywords for reasons that have nothing to do with
#: energy hardware — a battery-level helper, a Lovelace card, a blueprint.
_NOISE = re.compile(
    r"battery.?notes|battery.?sim|bms_ble|_card$|lovelace|blueprint|theme|"
    r"battery.?monitor|magic.?areas|notify|alarm|\bnas\b|sftp|e-?ink|"
    r"display|radio|propagation|backup|printer|vacuum|mower|\bcard\b", re.I)

_PLATFORMS = ("number", "select", "switch", "sensor", "binary_sensor")

#: An integration this widely installed is mined whatever it is called — a
#: brand name is not a description (Anker Solix, 5.7k installs, says "Power
#: devices" and nothing else).
POPULAR_FLOOR = 300


# ─────────────────────────── fetching ────────────────────────────────

def _url_key(url: str) -> str:
    """A STABLE cache key. ``hash()`` is randomised per process, so using it
    here meant an offline run could never find what an online run wrote —
    every invocation re-fetched everything and ``--offline`` mined nothing."""
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def _cache_path(key: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)
    return CACHE / f"{safe}.json"


def _get(url: str, key: str, *, offline: bool, ttl_s: float = 0.0) -> Optional[bytes]:
    """Fetch ``url`` into the cache and return its bytes. ``offline`` never
    touches the network; a cached miss (an empty file) is remembered so a
    404 is not re-asked on every run."""
    path = _cache_path(key)
    if path.exists():
        fresh = ttl_s <= 0 or (time.time() - path.stat().st_mtime) < ttl_s
        if offline or fresh:
            raw = path.read_bytes()
            return raw or None
    if offline:
        return None
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        raw = b""          # remember the miss
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw or None


def fetch_sources(*, offline: bool) -> Dict[str, Any]:
    """The five indexes, parsed. A source that cannot be read is an empty
    dict — the roster degrades, it never crashes."""
    out: Dict[str, Any] = {}
    for name, url in SOURCES.items():
        raw = _get(url, f"index_{name}", offline=offline)
        try:
            out[name] = json.loads(raw.decode("utf-8-sig")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            out[name] = {}
        if not out[name]:
            print(f"  ! source {name} unavailable", file=sys.stderr)
    return out


# ────────────────────── what SEM already knows ───────────────────────

#: Integrations SEM reads through a path that is not a detection row: the
#: solar-forecast providers (``coordinator/forecast_reader.py``) and the
#: dynamic-tariff providers (``tariff/tariff_provider.py``). Without these the
#: backlog's top entries are things SEM has supported for a year.
_KNOWN_BY_OTHER_PATHS: frozenset = frozenset({
    "forecast_solar", "solcast_solar", "open_meteo_solar_forecast",
    "nordpool", "tibber", "amber", "awattar", "entsoe", "energyzero",
    "epex_spot", "octopus_energy", "stromligning", "elprisetjustnu",
})


def sem_known_domains() -> set:
    """Every domain/token SEM can already place, read from the tree WITHOUT
    importing Home Assistant (the generator convention — see
    ``scripts/generate_hardware_doc.py``)."""
    known: set = set(_KNOWN_BY_OTHER_PATHS)
    src = (ROOT / "hardware_detection.py").read_text()
    m = re.search(r"KNOWN_INVERTER_DOMAINS[^{]*\{(.*?)\}", src, re.S)
    if m:
        known |= set(re.findall(r'"([a-z0-9_]{3,})"', m.group(1)))
    m = re.search(r"_EV_CHARGER_PLATFORMS\s*=\s*\[(.*?)\n\]", src, re.S)
    if m:
        known |= set(re.findall(r'\(\s*"([a-z0-9_]+)"', m.group(1)))
    spec = importlib.util.spec_from_file_location(
        "hardware_matrix", ROOT / "consts" / "hardware_matrix.py")
    hm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hm)
    for row in hm.ALL_ROWS:
        for field in ("domain_token", "integration", "soc_source"):
            val = row.get(field)
            if isinstance(val, str):
                known |= {t for t in re.split(r"[^a-z0-9_]+", val.lower())
                          if len(t) > 2}
    return known


def _lexicon():
    spec = importlib.util.spec_from_file_location(
        "role_lexicon", ROOT / "consts" / "role_lexicon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ───────────────────────── candidate rows ────────────────────────────

def _install_counts(sources: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for dom, v in (sources.get("custom_installs") or {}).items():
        if isinstance(v, dict) and isinstance(v.get("total"), int):
            counts[dom] = v["total"]
    core = ((sources.get("core_analytics") or {}).get("current") or {}).get(
        "integrations") or {}
    for dom, n in core.items():
        if isinstance(n, int):
            counts[dom] = max(counts.get(dom, 0), n)
    return counts


def candidate_rows(sources: Dict[str, Any]) -> Dict[str, dict]:
    """Every integration that looks energy-shaped by NAME (signal 1), from
    both HACS and core. The keyword filter is deliberately generous: signal 2
    (a mined role) is what earns a domain the right to route a proposal."""
    counts = _install_counts(sources)
    rows: Dict[str, dict] = {}

    for entry in (sources.get("hacs") or {}).values():
        dom = (entry.get("domain") or "").strip().lower()
        if not dom:
            continue
        name = ((entry.get("manifest") or {}).get("name")
                or entry.get("manifest_name") or dom)
        blob = " ".join(str(x) for x in (
            dom, name, entry.get("description") or "",
            " ".join(entry.get("topics") or [])))
        if not _KEYWORDS.search(blob) or _NOISE.search(f"{dom} {name}"):
            continue
        prev = rows.get(dom)
        row = {"name": str(name)[:60], "repo": entry.get("full_name"),
               "origin": "hacs", "installs": counts.get(dom, 0),
               "stars": entry.get("stargazers_count") or 0, "blurb": blob[:300]}
        if prev is None or row["stars"] > prev.get("stars", 0):
            rows[dom] = row

    # (#915) A name is a weak classifier: "Anker Solix" says nothing about
    # energy, and it has 5.7k installs. So every WIDELY installed integration
    # is a candidate regardless of its name — its declared vocabulary decides
    # (the two-signal rule, from the other direction).
    for entry in (sources.get("hacs") or {}).values():
        dom = (entry.get("domain") or "").strip().lower()
        if not dom or dom in rows or counts.get(dom, 0) < POPULAR_FLOOR:
            continue
        name = ((entry.get("manifest") or {}).get("name")
                or entry.get("manifest_name") or dom)
        if _NOISE.search(f"{dom} {name}"):
            continue
        rows[dom] = {"name": str(name)[:60], "repo": entry.get("full_name"),
                     "origin": "hacs", "installs": counts.get(dom, 0),
                     "stars": entry.get("stargazers_count") or 0,
                     "by": "popularity"}

    # (#915) Every domain SEM ALREADY supports is a candidate whatever it is
    # called — those are the oracle (can the miner re-find what we learned by
    # hand?) and their vocabulary widens the spec keys for brands SEM drives.
    # Sessy is the case that made this necessary: SEM learned its
    # ``api/eco/nom/idle`` strategy values from a live install in #523, and
    # the keyword filter had never heard of it.
    known = sem_known_domains()
    for entry in (sources.get("hacs") or {}).values():
        dom = (entry.get("domain") or "").strip().lower()
        if not dom or dom in rows or dom not in known:
            continue
        name = ((entry.get("manifest") or {}).get("name")
                or entry.get("manifest_name") or dom)
        rows[dom] = {"name": str(name)[:60], "repo": entry.get("full_name"),
                     "origin": "hacs", "installs": counts.get(dom, 0),
                     "stars": entry.get("stargazers_count") or 0}

    # (#915, found via #869) A FORK of an energy integration is energy-shaped
    # whatever its description says. ``anker_solix_official`` reports no
    # installs and describes itself as "local Modbus TCP" — no keyword, no
    # popularity, so it was invisible; meanwhile a reporter was running it.
    # Its sibling ``anker_solix`` is already a candidate, and a domain that
    # extends an accepted domain's name is the same hardware by another
    # maintainer. Mining it costs one fetch and risks nothing: the two-signal
    # rule still decides whether it may route anything.
    for entry in (sources.get("hacs") or {}).values():
        dom = (entry.get("domain") or "").strip().lower()
        if not dom or dom in rows or "_" not in dom:
            continue
        parent = next((r for r in rows if dom.startswith(f"{r}_")), None)
        if parent is None:
            continue
        name = ((entry.get("manifest") or {}).get("name")
                or entry.get("manifest_name") or dom)
        if _NOISE.search(f"{dom} {name}"):
            continue
        rows[dom] = {"name": str(name)[:60], "repo": entry.get("full_name"),
                     "origin": "hacs", "installs": counts.get(dom, 0),
                     "stars": entry.get("stargazers_count") or 0,
                     "by": f"sibling:{parent}"}

    core_index = (sources.get("core_index") or {}).get("integration") or {}
    website = sources.get("website") or {}

    # (#915) HA groups sub-integrations under their BRAND: `tesla` carries
    # `powerwall`, `tesla_wall_connector` and `tesla_fleet` in a nested
    # ``integrations`` dict, and none of the three appears at the top level.
    # Iterating the top level alone hid 241 core integrations — among them
    # Tesla Powerwall, a brand SEM has supported since the sign-convention
    # table was written. Found by checking the roster against the CLOSED
    # hardware-support issues (#75-#81), where seven human verdicts had
    # already named the integrations SEM should be able to name.
    flat = {}
    for dom, entry in core_index.items():
        if not isinstance(entry, dict):
            continue
        flat.setdefault(dom, entry)
        for sub, sub_entry in (entry.get("integrations") or {}).items():
            if isinstance(sub_entry, dict):
                flat.setdefault(sub, {"name": sub_entry.get("name") or sub,
                                      "brand": dom})

    for dom, entry in flat.items():
        if dom in rows or not isinstance(entry, dict):
            continue
        name = entry.get("name") or dom
        brand = entry.get("brand") or ""
        desc = ((website.get(dom) or {}).get("description", "")
                or (website.get(brand) or {}).get("description", ""))
        blob = f"{dom} {name} {brand} {desc}"
        # (#915) Popularity buys a QUESTION, never an answer — the same rule
        # the HACS loop has always had, which core never did. Tesla's Wall
        # Connector has 6555 installs and a name with no energy word in it
        # ("Wall Connector"), so it was never even asked what it declares.
        # It answers `grid_v`, `total_power_w`, `session_energy_wh` — and no
        # controllable role, which is #75's human verdict exactly.
        popular = counts.get(dom, 0) >= POPULAR_FLOOR
        if _NOISE.search(f"{dom} {name}"):
            continue
        if dom not in known and not popular and not _KEYWORDS.search(blob):
            continue
        rows[dom] = {"name": str(name)[:60], "repo": "home-assistant/core",
                     "origin": "core", "installs": counts.get(dom, 0),
                     "stars": 0, "blurb": blob[:300]}
    return rows


# ───────────────────────── vocabulary mining ─────────────────────────

def _strings_urls(repo: str, domain: str, origin: str) -> Iterable[str]:
    if origin == "core":
        base = "https://raw.githubusercontent.com/home-assistant/core/dev"
        yield f"{base}/homeassistant/components/{domain}/strings.json"
        return
    if not repo:
        return
    for branch in ("main", "master"):
        for path in (
            f"custom_components/{domain}/strings.json",
            f"custom_components/{domain}/translations/en.json",
            # content_in_root repos (SEM's own, wlcrs/huawei_solar) have no
            # custom_components wrapper — omitting these cost a third of the
            # hit rate in the measurement that sized this arc.
            "strings.json",
            "translations/en.json",
        ):
            yield f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def _source_urls(repo: str, domain: str, origin: str) -> Iterable[str]:
    """The fallback for integrations that hardcode entity names in Python."""
    if origin == "core":
        base = "https://raw.githubusercontent.com/home-assistant/core/dev"
        for plat in _PLATFORMS:
            yield f"{base}/homeassistant/components/{domain}/{plat}.py"
        return
    if not repo:
        return
    for branch in ("main", "master"):
        for prefix in (f"custom_components/{domain}/", ""):
            for plat in _PLATFORMS:
                yield f"https://raw.githubusercontent.com/{repo}/{branch}/{prefix}{plat}.py"


def mine_vocabulary(repo: str, domain: str, origin: str, *,
                    offline: bool) -> Dict[str, Dict[str, dict]]:
    """The entity vocabulary an integration DECLARES, per platform.

    Preferred source is its ``strings.json`` / ``translations/en.json``: a
    modern integration lists every entity's ``translation_key`` there, with
    the select options under ``state``. Older ones hardcode names in Python,
    so the fallback greps the component's platform modules for ``key=`` /
    ``translation_key=``. The fallback's platform attribution is weaker (it
    trusts the file name), which is why it runs second and never overwrites.
    """
    out: Dict[str, Dict[str, dict]] = {}
    for url in _strings_urls(repo, domain, origin):
        raw = _get(url, f"vocab_{domain}_{_url_key(url)}", offline=offline)
        if not raw:
            continue
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            continue
        entity = data.get("entity")
        if not isinstance(entity, dict):
            continue
        for platform, keys in entity.items():
            if platform not in _PLATFORMS or not isinstance(keys, dict):
                continue
            for key, body in keys.items():
                opts = ()
                if isinstance(body, dict) and isinstance(body.get("state"), dict):
                    opts = tuple(sorted(body["state"]))
                out.setdefault(platform, {})[key] = {"options": opts}
        if out:
            return out

    for url in _source_urls(repo, domain, origin):
        plat = url.rsplit("/", 1)[-1][:-3]
        raw = _get(url, f"src_{domain}_{_url_key(url)}", offline=offline)
        if not raw:
            continue
        try:
            text = raw.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        keys = set(re.findall(
            r'(?:^|\s)(?:key|translation_key)\s*=\s*["\']([a-z0-9_]{3,60})["\']',
            text))
        for key in keys:
            out.setdefault(plat, {}).setdefault(key, {"options": ()})
    return out


def _match_role(rules: Dict[str, Dict[str, Any]], platform: str,
                key: str) -> Optional[str]:
    """First rule whose platform, ``any`` and ``not`` clauses all agree."""
    for role, rule in rules.items():
        if rule["platform"] != platform:
            continue
        if any(re.search(p, key, re.I) for p in rule.get("not", ())):
            continue
        if any(re.search(p, key, re.I) for p in rule["any"]):
            return role
    return None


def sem_charger_domains() -> set:
    """The platforms SEM already knows are EV chargers — its own
    hand-maintained list, read the same way as ``sem_known_domains()``. A
    domain on this list is a charger whatever its vocabulary looks like."""
    src = (ROOT / "hardware_detection.py").read_text()
    m = re.search(r"_EV_CHARGER_PLATFORMS\s*=\s*\[(.*?)\n\]", src, re.S)
    return set(re.findall(r'\(\s*"([a-z0-9_]+)"', m.group(1))) if m else set()


@functools.lru_cache(maxsize=1)
def _charger_domains() -> frozenset:
    return frozenset(sem_charger_domains())


def classify_kind(vocab: Dict[str, Dict[str, dict]], lexicon,
                  *, known: bool = False, domain: str = "") -> str:
    """What the declared vocabulary says this integration IS.

    Necessary because a role name alone is ambiguous across kinds: a Porsche
    declares ``target_soc`` and a Midea air conditioner declares
    ``operation_mode``. Read as home-battery roles those are nonsense — the
    first pass of this crawler put a pet feeder in the roster with a
    discharge limit. The markers below decide which rule set may apply at
    all, so a car contributes vehicle roles and nothing else.
    """
    blob = " ".join(k for keys in vocab.values() for k in keys).lower()
    # (#915) The house wins. A single incidental marker must not outvote a
    # vocabulary that plainly describes a building's electrical system — see
    # HOUSE_MARKERS for the Victron GX case that made this necessary.
    # …and it wins on WEIGHT, not on being asked first. Victron's GX is 465
    # keys of inverter with one `ev_odometer`; Midea's cloud is 1095 keys of
    # fridges and dryers with one `inverter`. First-match got both wrong, in
    # opposite directions. Counting distinct markers gets both right.
    def _hits(markers) -> int:
        return sum(1 for m in markers if m in blob)

    house = _hits(getattr(lexicon, "HOUSE_MARKERS", ()))
    appliance, vehicle = _hits(lexicon.APPLIANCE_MARKERS), _hits(
        lexicon.VEHICLE_MARKERS)
    # A TIE goes to the house: `camera`, `pedal` and `lightbar` are gadget
    # words that a CAR also has, and on Teslemetry they tied with `grid_`,
    # `inverter` and `_grid_` — three words no gadget has. The house side is
    # what SEM would lose, so it needs the benefit of the doubt.
    if appliance > house:
        return "appliance"
    if vehicle > house:
        return "vehicle"
    # The anchor rule: without a key no non-energy device declares, this is
    # something else that happens to have a battery. Say so rather than
    # reading its `battery_level` as a home pack's state of charge.
    # A charger, unless it also runs the house. Wallbox and V2C declare a
    # ``state_of_charge`` / ``battery_power`` that belongs to the CAR; Anker
    # Solix declares an EV current limit beside a real PV input and is a
    # generator with a socket. The list SEM maintains by hand wins outright.
    if domain in _charger_domains():
        return "charger"
    if (any(m in blob for m in lexicon.CHARGER_MARKERS)
            and not any(m in blob for m in lexicon.GENERATOR_MARKERS)):
        return "charger"
    if not any(a in blob for a in lexicon.ENERGY_ANCHORS):
        # A domain SEM already supports has human evidence behind it (a
        # matrix row with a citation); a thin published vocabulary does not
        # override that. Sessy publishes three sensors and one select.
        return "energy" if known else "other"
    return "energy"


def _reports_electricity(vocab: Dict[str, Dict[str, dict]], lexicon) -> bool:
    """Does this vocabulary describe an ELECTRICAL device? A strong anchor
    plus two keys shaped like a watt, an amp or a kilowatt-hour. This is what
    admits Tesla's Wall Connector (`grid_v`, `total_power_w`, `energy_kwh`)
    and refuses a fitness watch that happens to charge from the sun."""
    keys = [k for ks in vocab.values() for k in ks]
    blob = " ".join(keys).lower()
    if not any(a in blob for a in lexicon.STRONG_ENERGY_ANCHORS):
        return False
    return sum(1 for k in keys if lexicon.UNIT_SHAPED_KEY.search(k)) >= 2


def roles_from_vocabulary(vocab: Dict[str, Dict[str, dict]], lexicon,
                          kind: str = "energy") -> Dict[str, dict]:
    """Declared keys -> SEM roles, via the hand-written lexicon. An appliance
    contributes nothing; a vehicle contributes only vehicle roles."""
    if kind in ("appliance", "other"):
        return {}
    if kind == "vehicle":
        rules = dict(lexicon.VEHICLE_ROLE_RULES)
    elif kind == "charger":
        # A CHARGER's "state of charge" is the CAR's, and its battery power
        # is the car's too. Feeding either into SEM's house-battery reads
        # would corrupt the energy balance every ten seconds — a far worse
        # outcome than proposing nothing. So a charger contributes its
        # controls and what it knows about the vehicle, and nothing about a
        # house it does not have. (Wallbox declares ``state_of_charge`` and
        # V2C declares ``battery_power`` — both the car's; SMA's EV charger
        # declares ``charge_power_limit``, which is the CAR's charge rate
        # and not the house pack's.)
        rules = {r: v for r, v in lexicon.ROLE_RULES.items()
                 if r.startswith("ev_")}
        rules.update(lexicon.VEHICLE_ROLE_RULES)
    else:
        # control roles AND the read roles: which entity is the solar
        # power sensor is the question a first install actually asks.
        rules = {**lexicon.ROLE_RULES, **lexicon.READ_ROLE_RULES}
        # (#915) …and an integration can be BOTH. Tesla's Fleet API speaks
        # for the car and the Powerwall through one vocabulary; a Victron GX
        # runs the house and reads the SOC of whatever is plugged into its EV
        # charger. Forcing a single verdict threw away one half or the other,
        # so a house that also knows a car contributes the car's READS too —
        # which is exactly what SEM's `vehicle_soc_entity` wants.
        blob = " ".join(k for keys in vocab.values() for k in keys).lower()
        if any(m in blob for m in lexicon.VEHICLE_MARKERS):
            rules.update(lexicon.VEHICLE_ROLE_RULES)
    roles: Dict[str, dict] = {}
    for platform, keys in sorted(vocab.items()):
        for key, body in sorted(keys.items()):
            role = _match_role(rules, platform, key)
            if not role:
                continue
            slot = roles.setdefault(
                role, {"platform": platform, "keys": [], "options": []})
            if slot["platform"] != platform:
                continue
            slot["keys"].append(key)
            for opt in body.get("options") or ():
                if opt not in slot["options"]:
                    slot["options"].append(opt)
    # (#810) A force-charge switch that ships a companion DURATION is a
    # timed boost, not a state SEM can hold. EG4 declares ``quick_charge``
    # beside ``quick_charge_duration``; its owner: "I don't think you want
    # Quick charge for general usage — it's a 60 minute long run of AC charge
    # mode intended for a quick battery boost before a storm." SEM's force
    # charge is meant to stay on for as long as the cheap hours last, so a
    # switch that expires on its own is the wrong shape, and offering none is
    # the right failure. Same shape as the AC-THOR setpoint that expires
    # unless it is re-sent (#880).
    # (#915) A battery role needs a battery somewhere in the vocabulary —
    # see BATTERY_CONTEXT. This is the two-signal rule one level down: the
    # key earns the role, the vocabulary earns the key.
    blob_all = " ".join(k for keys in vocab.values() for k in keys).lower()
    if not any(m in blob_all for m in getattr(lexicon, "BATTERY_CONTEXT", ())):
        for r in [r for r in roles if r.startswith("battery_")]:
            roles.pop(r)

    # Half a split pair is not a proposal (see PAIRED_ROLES).
    for pair in getattr(lexicon, "PAIRED_ROLES", ()):
        if not all(r in roles for r in pair):
            for r in pair:
                roles.pop(r, None)

    every_key = {k for keys in vocab.values() for k in keys}
    slot = roles.get("battery_force_charge")
    if slot:
        durable = [k for k in slot["keys"]
                   if not ({f"{k}_duration", f"{k}_time", f"{k}_timer"}
                           & every_key)]
        if durable:
            slot["keys"] = durable
        else:
            roles.pop("battery_force_charge")

    return {r: {"platform": v["platform"], "keys": tuple(v["keys"]),
                "options": tuple(v["options"])}
            for r, v in sorted(roles.items())}


# ────────────────────────── the roster ───────────────────────────────

def build_roster(sources: Dict[str, Any], *, offline: bool, floor: int,
                 workers: int = 8) -> Tuple[dict, dict, dict]:
    lexicon = _lexicon()
    known = sem_known_domains()
    rows = candidate_rows(sources)

    # Mine the candidates worth mining: anything above the install floor, plus
    # everything SEM already supports — the known ones are the ORACLE (can the
    # miner re-find what we learned by hand?) and their vocabulary widens the
    # spec keys for brands we do drive.
    # A SIBLING is mined whatever its install count says: a fork exists
    # precisely because the original did not fit somebody, and analytics has
    # not caught up with it (#869: 0 reported installs, a live reporter).
    to_mine = {d: r for d, r in rows.items()
               if r["installs"] >= floor or d in known
               or str(r.get("by", "")).startswith("sibling:")}
    to_mine = {d: r for d, r in to_mine.items()
               if d not in lexicon.OPAQUE_PLATFORMS}
    print(f"  candidates {len(rows)} · mining {len(to_mine)} "
          f"(floor {floor}, +{len(set(to_mine) & known)} known)", file=sys.stderr)

    def _one(item):
        dom, row = item
        vocab = mine_vocabulary(row.get("repo") or "", dom, row["origin"],
                                offline=offline)
        kind = (classify_kind(vocab, lexicon, known=dom in known, domain=dom)
                if vocab else "energy")
        return (dom, kind, roles_from_vocabulary(vocab, lexicon, kind),
                bool(vocab), _reports_electricity(vocab, lexicon))

    mined: Dict[str, dict] = {}
    kinds: Dict[str, str] = {}
    spoke: set = set()          # domains that published a vocabulary at all
    electrical: set = set()     # …and whose vocabulary reports watts/amps/kWh
    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        for dom, kind, roles, had_vocab, amps in ex.map(
                _one, sorted(to_mine.items())):
            kinds[dom] = kind
            if had_vocab:
                spoke.add(dom)
            if amps:
                electrical.add(dom)
            if roles:
                mined[dom] = roles

    roster: Dict[str, dict] = {}
    known_now = known
    for dom, row in sorted(rows.items()):
        if dom in lexicon.OPAQUE_PLATFORMS:
            continue
        has_roles = dom in mined
        # (#915) A vocabulary that ANSWERS the energy-anchor test is evidence
        # in its own right, even when no key maps to a SEM role. Tesla's Wall
        # Connector — 6555 installs, more than KEBA, Zaptec and Wallbox — was
        # dropped for having no energy word in "Tesla Wall Connector", while
        # its own source declares `vehicle_connected`, `session_energy_wh` and
        # `contactor_closed`. The crawler classifies it as a CHARGER with no
        # controllable role, which is exactly the verdict a human wrote by
        # hand in #75. Naming it costs nothing and is the whole point of the
        # naming half; proposing for it remains impossible, because it has no
        # role to propose. Spotify cannot arrive this way: it has to pass the
        # same ENERGY_ANCHORS test that gates every mined row.
        says_energy = (dom in spoke
                       and kinds.get(dom) in ("energy", "charger")
                       and dom in electrical)
        if not has_roles and not says_energy:
            # Nothing minable: the row may still carry a NAME, but only if the
            # domain or the brand name itself is energy-shaped. A keyword
            # found in prose ("...with battery backup") is not a brand.
            if row["installs"] < floor:
                continue
            # Judge it on what the FIRST gate judged — domain, name AND the
            # integration's own description. Checking the name alone dropped
            # NRGKick (#917), whose HA page says "mobile EV charger" while
            # its name says nothing at all: the ecosystem's own words are the
            # evidence, and a brand name is rarely one of them.
            if (not _KEYWORDS.search(f"{dom} {row['name']} {row.get('blurb', '')}")
                    and dom not in known_now):
                continue
        roster[dom] = {
            "name": row["name"],
            "repo": row["repo"],
            "origin": row["origin"],
            "installs": int(row["installs"]),
            "kind": kinds.get(dom, "energy"),
            # (#915) the two-signal rule, mirroring _census_energy_shaped():
            # a keyword match alone may supply a NAME and nothing else.
            # "vocabulary" is the two-signal claim: this row may route a
            # proposal. A row that only PASSED the anchor test says so
            # separately — it earned its name, not a role.
            "kind_from": ("vocabulary" if has_roles
                          else "vocabulary_name_only" if says_energy
                          else "keyword"),
        }
    meta = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": {k: SOURCES[k] for k in sorted(SOURCES)},
        "install_floor": floor,
        "candidates": len(rows),
        "kept": len(roster),
        "with_roles": len(mined),
        "roles_mined": sum(len(v) for v in mined.values()),
    }
    return roster, mined, meta


HEADER = '''"""GENERATED — do not edit. #915

    python3 scripts/crawl_integration_roster.py --refresh --write

This is a ROSTER, not a support matrix. A row means exactly one thing: an
integration with this domain exists upstream, it looks energy-shaped, and —
when ``kind_from`` is ``vocabulary`` — here is what its own repository says it
calls things.

It is NOT a claim that SEM supports the brand, has ever seen it, or knows its
sign convention. Support claims live in ``consts/hardware_matrix.py`` and need
a citation (the #530 rule: web-research "support" is a false-positive
generator). Nothing here may carry a status, an evidence string or a sign
pattern; ``tests/test_915_roster_is_not_a_claim.py`` enforces that
structurally rather than by convention.

Every runtime use is an INTERSECTION with the local entity registry: a key
here can only ever select an entity the user's own install already has, and
the role it suggests is a proposal the user confirms — never a binding.

Sources: HACS (data-v2.hacs.xyz), Home Assistant analytics
(analytics.home-assistant.io) and the Home Assistant core + website indexes.
Vocabulary is read from each integration's own repository.
"""

from __future__ import annotations

from typing import Any, Dict, Final

SCHEMA: Final = 1
'''


def render_module(roster: dict, role_vocab: dict, meta: dict) -> str:
    out = [HEADER, "", f"ROSTER_META: Final[Dict[str, Any]] = {meta!r}", "",
           "#: domain -> what the ecosystem says this integration is.",
           "ROSTER: Final[Dict[str, Dict[str, Any]]] = {"]
    for dom, row in sorted(roster.items()):
        out.append(f"    {dom!r}: {row!r},")
    out.append("}")
    out.append("")
    out.append("#: domain -> role -> the keys that integration DECLARES for it.")
    out.append("#: Only domains whose vocabulary was actually read appear here.")
    out.append("ROLE_VOCAB: Final[Dict[str, Dict[str, Dict[str, Any]]]] = {")
    for dom, roles in sorted(role_vocab.items()):
        out.append(f"    {dom!r}: {{")
        for role, body in sorted(roles.items()):
            out.append(f"        {role!r}: {body!r},")
        out.append("    },")
    out.append("}")
    out.append("")
    return "\n".join(out)


def backlog(roster: dict, role_vocab: dict) -> list:
    """The developer question: of the energy-shaped integrations people
    actually run, which can SEM not even NAME, and what would a row be
    worth? Ranked by installs. Not a roadmap — nothing here is promised."""
    known = sem_known_domains()
    rows = [(d, r["name"], r["installs"], "roles" if d in role_vocab else "name")
            for d, r in roster.items() if d not in known]
    return sorted(rows, key=lambda r: -r[2])


def write_baseline(roster: dict, role_vocab: dict, meta: dict, floor: int) -> dict:
    gap = backlog(roster, role_vocab)
    data = {
        "_comment": [
            "#915 shrink-only ratchet. `unnamed_over_floor` is how many",
            "energy-shaped integrations above the install floor SEM cannot",
            "even NAME. It shrinks when SEM learns a brand and grows only",
            "when the ecosystem does — a refresh commit must say which.",
            "Computed from the COMMITTED roster, never from the live",
            "network, so CI never depends on the internet.",
            "Regenerate: python3 scripts/crawl_integration_roster.py --refresh --baseline",
        ],
        "schema": 1,
        "install_floor": floor,
        "roster_rows": len(roster),
        "domains_with_roles": len(role_vocab),
        "roles_mined": sum(len(v) for v in role_vocab.values()),
        "unnamed_over_floor": sum(1 for r in gap if r[2] >= floor),
        "top_gap": [r[0] for r in gap[:12]],
    }
    (ROOT / "tests" / "roster_coverage_baseline.json").write_text(
        json.dumps(data, indent=2) + "\n")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true",
                    help="re-fetch the indexes (vocabulary is cached forever)")
    ap.add_argument("--offline", action="store_true",
                    help="cache only; never touch the network")
    ap.add_argument("--write", action="store_true",
                    help="regenerate consts/integration_roster.py")
    ap.add_argument("--backlog", action="store_true",
                    help="print the ranked coverage gap")
    ap.add_argument("--baseline", action="store_true",
                    help="rewrite tests/roster_coverage_baseline.json")
    ap.add_argument("--floor", type=int, default=50,
                    help="minimum installs for a name-only row (default 50)")
    args = ap.parse_args()

    if args.refresh and not args.offline:
        for name in SOURCES:
            _cache_path(f"index_{name}").unlink(missing_ok=True)

    print("fetching indexes…", file=sys.stderr)
    sources = fetch_sources(offline=args.offline)
    if not sources.get("hacs") and not sources.get("core_index"):
        print("no index available — run once online first", file=sys.stderr)
        return 2

    print("mining vocabulary…", file=sys.stderr)
    roster, role_vocab, meta = build_roster(
        sources, offline=args.offline, floor=args.floor)
    print(f"  roster {meta['kept']} rows · {meta['with_roles']} with vocabulary "
          f"· {meta['roles_mined']} roles", file=sys.stderr)

    if args.write:
        target = ROOT / "consts" / "integration_roster.py"
        target.write_text(render_module(roster, role_vocab, meta))
        print(f"wrote {target.relative_to(ROOT)}", file=sys.stderr)
    if args.baseline:
        data = write_baseline(roster, role_vocab, meta, args.floor)
        print(f"wrote tests/roster_coverage_baseline.json "
              f"(unnamed_over_floor={data['unnamed_over_floor']})", file=sys.stderr)
    if args.backlog:
        print(f"\n{'domain':32} {'installs':>9}  {'has':5} name")
        for dom, name, installs, kind in backlog(roster, role_vocab)[:40]:
            print(f"{dom:32} {installs:>9}  {kind:5} {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
