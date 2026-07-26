"""#667 — every label key must name a real entity.

``consts/labels.py`` maps entity-description keys to HA entity-registry labels.
``sensor.py:_apply_labels_to_sensors`` applies them with an exact-match dict
lookup on the FULL description key::

    labels = SENSOR_LABEL_MAPPING.get(sensor.entity_description.key, set())

A miss returns an empty set and the code moves on, so a registry whose lookup
failure mode is "no labels applied" cannot report its own rot. 44 of 116 keys
(38%) had drifted — including **every** ``sem_monthly`` entity, so filtering the
HA entity list by that label returned nothing at all while all six monthly
sensors existed and held data.

Eleven were pure suffix drift (the label key was the entity key minus its
``_energy`` suffix). The other 33 were triaged individually and came back as
one class, not thirty-three judgement calls: **the sensor was deleted and the
label was left behind.** ``sensor.py`` names 26 of them outright in its own
``# Removed:`` comments, so the file that dropped the entities is the file that
documents which labels went stale — nobody just re-read it. Two were live
entities under a drifted name and were repointed; the rest are gone.

The mapping went 116 → 85 keys and the allowlist is now **empty**, so this is a
plain ban with a ratchet's paperwork: a newly-typo'd or newly-orphaned label
key fails immediately.

Worth recording, because it bounds what this registry can ever do: the lookup
is exact-match on the FULL description key, so the per-device entities built in
``select.py``/``time.py`` (``charger_<id>_charge_mode``, ``battery_<id>_mode``)
can never be labelled by it at all. That is a design limit, not drift.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from custom_components.solar_energy_management.consts.labels import (
    SENSOR_LABEL_MAPPING,
)

_ROOT = Path(__file__).resolve().parent.parent

# Every platform SEM forwards a config entry to (__init__.py PLATFORMS).
# Derived below rather than trusted: a platform added there and forgotten here
# would make its real entities read as orphans.
_PLATFORMS = (
    "sensor.py", "binary_sensor.py", "number.py",
    "select.py", "switch.py", "time.py",
)

# EMPTY — and it must stay that way. The 33 were triaged individually in #667
# and every one turned out to be the same thing: a sensor that was DELETED
# while its label was left behind. 26 of them are named in `# Removed:`
# comments in ``sensor.py`` (lines 125, 197-198, 231-234, 254, 721, 729-731,
# 874-879), which is how the verdicts are evidenced rather than guessed.
#
# Two were real entities under a drifted name and were repointed
# (battery_cycles → battery_cycles_estimated, battery_health →
# battery_health_score). The rest were deleted, including the near-misses of a
# working label (daily_solar_yield vs daily_solar_energy, daily_ev_consumption
# vs daily_ev_energy) — repointing those would have double-labelled one entity.
#
# battery_voltage / battery_current deserve their own note: they DO appear in
# ``hardware_detection.py``, but only as patterns for finding a *user's*
# sensors. SEM never republishes them, so there is nothing to label.
KNOWN_ORPHAN_LABELS: frozenset[str] = frozenset()


def _entity_keys() -> set[str]:
    keys: set[str] = set()
    for name in _PLATFORMS:
        path = _ROOT / name
        if path.exists():
            keys |= set(re.findall(r'key="([a-z0-9_]+)"', path.read_text()))
    return keys


@pytest.mark.unit
class TestLabelRegistry667:
    def test_the_scan_covers_every_platform_sem_forwards_to(self):
        """The scan's blind spot is the dangerous direction of this guard.

        A platform added to ``__init__.py`` PLATFORMS but not to ``_PLATFORMS``
        makes its real entities read as orphans, and the natural repair under
        deadline is to allowlist them — which is exactly the rot #667 is about.
        (It fails loudly rather than silently, but it fails for the wrong
        reason, and a wrong reason is what gets allowlisted.)
        """
        declared = set(re.findall(
            r"Platform\.([A-Z_]+)", (_ROOT / "__init__.py").read_text()
        ))
        scanned = {name[:-3].upper() for name in _PLATFORMS}
        assert declared <= scanned, (
            f"{sorted(declared - scanned)} forwarded in __init__.py but not "
            "scanned here — their entities would read as orphan labels (#667)."
        )

    def test_the_scan_actually_finds_entities(self):
        """Bug class 8, applied at birth: if the regex silently matched
        nothing, every assertion below would pass vacuously and this guard
        would be worthless. Pin a floor well under the real count (224)."""
        keys = _entity_keys()
        assert len(keys) > 150, f"only found {len(keys)} entity keys — scan broke"
        assert "monthly_solar_yield_energy" in keys

    def test_no_new_orphan_labels(self):
        orphans = set(SENSOR_LABEL_MAPPING) - _entity_keys()
        new = orphans - KNOWN_ORPHAN_LABELS
        assert not new, (
            f"label key(s) naming no entity: {sorted(new)}. "
            "SENSOR_LABEL_MAPPING is an exact-match lookup on the full "
            "EntityDescription key — a miss applies no labels and reports "
            "nothing. Fix the key, or the label labels nothing (#667)."
        )

    def test_the_allowlist_only_shrinks(self):
        """Anti-rot: once an orphan is resolved its allowlist entry must go,
        otherwise the ratchet quietly stops ratcheting."""
        stale = KNOWN_ORPHAN_LABELS & _entity_keys()
        assert not stale, (
            f"{sorted(stale)} now name real entities — remove them from "
            "KNOWN_ORPHAN_LABELS so the ratchet keeps its teeth (#667)."
        )

    def test_the_allowlist_entries_are_all_real_label_keys(self):
        """A leftover entry for a label key that no longer exists would mask a
        future orphan of the same name."""
        ghosts = KNOWN_ORPHAN_LABELS - set(SENSOR_LABEL_MAPPING)
        assert not ghosts, (
            f"{sorted(ghosts)} are not in SENSOR_LABEL_MAPPING at all — drop "
            "them from the allowlist (#667)."
        )

    def test_the_monthly_group_is_no_longer_entirely_dead(self):
        """THE closure. Every ``sem_monthly`` label key missed its entity, so
        filtering by that label in HA returned nothing while all six sensors
        existed and held data (live-checked on HA-TEST: monthly solar 8.14,
        monthly home 13.05)."""
        keys = _entity_keys()
        monthly = [
            k for k, labels in SENSOR_LABEL_MAPPING.items()
            if "sem_monthly" in labels
        ]
        assert monthly, "no sem_monthly labels at all — did the group vanish?"
        assert not [k for k in monthly if k not in keys and k not in KNOWN_ORPHAN_LABELS]

    def test_the_rule_can_actually_fire(self):
        """The check must reject a plausible typo, not just pass on clean
        input — otherwise it is a green light with nothing behind it."""
        orphans = ({"monthly_solar_yield"} | set(SENSOR_LABEL_MAPPING)) - _entity_keys()
        assert "monthly_solar_yield" in orphans - KNOWN_ORPHAN_LABELS, (
            "the suffix-drift shape this issue is about would not be caught"
        )

@pytest.mark.unit
class TestConstsRegistriesDoNotRot669:
    """#669 — the same rule, pointed at every ``consts/`` key→entity map.

    #667 fixed one registry. Sweeping its siblings found a second: a 64-entry
    ``SEM_SENSORS`` map in ``consts/sensors.py``, **45% drifted** (29 keys named
    no entity), with zero production readers and one tautological test asserting
    a dict literal against itself. It was deleted rather than repaired — a map
    nothing reads is not an API, and a plausible-looking map to entity IDs that
    mostly do not exist is worse than no map: anyone reaching for it got
    ``sensor.sem_home_consumption``, which never existed.

    That registry was still accreting rot right up to the end — ``consts/
    sensors.py:95`` mapped ``ev_max_current_available`` to a non-existent
    entity_id, arriving *after* the 45% was measured. So the closure cannot be a
    one-time repair; it has to be a rule that fires on the next one.

    This class is that rule. It fails if a NEW module under ``consts/`` grows a
    dict of ``key -> "sensor.sem_*"`` strings without a guard, which is exactly
    the shape that rotted twice.
    """

    _CONSTS = _ROOT / "consts"

    def test_the_scan_sees_the_consts_package(self):
        """Bug class 8 again: if the glob found nothing this whole class would
        pass vacuously."""
        modules = list(self._CONSTS.glob("*.py"))
        assert len(modules) >= 4, f"only {len(modules)} consts modules — scan broke"

    def test_every_sem_entity_id_in_consts_names_a_real_entity(self):
        """The rule, derived rather than listed.

        Any ``<platform>.sem_<key>`` literal under ``consts/`` is a *claim that
        an entity exists*, and ``SEMSensor`` builds exactly
        ``sensor.sem_{description.key}`` (sensor.py:1942) — so the claim is
        checkable against the platform files that actually declare the keys.

        Deliberately about the **reference**, not the container. Whether the
        literal sits in a 64-entry map (``SEM_SENSORS``, 45% dead) or in a lone
        named constant (``ENTITY_SOLAR_POWER``, live and used), a reference to
        an entity that does not exist is the same rot and fails the same silent
        way — a missing dict key, or ``states.get`` returning ``None``. Banning
        the *shape* would have flagged the three healthy constants and taught
        the next person to route around the rule.
        """
        keys = _entity_keys()
        assert len(keys) > 150, f"only found {len(keys)} entity keys — scan broke"

        dangling: dict[str, list[str]] = {}
        for path in sorted(self._CONSTS.glob("*.py")):
            bad = [
                ref for ref in re.findall(
                    r'"[a-z_]+\.sem_([a-z0-9_]+)"', path.read_text()
                )
                if ref not in keys
            ]
            if bad:
                dangling[path.name] = sorted(set(bad))
        assert not dangling, (
            f"{dangling} — consts/ names SEM entities that no platform file "
            "declares. This is how SEM_SENSORS reached 45% dead before it was "
            "deleted (#669): the reference is never resolved, so nothing "
            "reports the miss. Fix the key or drop the reference."
        )

    def test_the_deleted_registry_stays_deleted(self):
        """A revert or a merge could quietly restore it."""
        assert not (self._CONSTS / "sensors.py").exists(), (
            "consts/sensors.py is back. It was 180 lines, 45% drifted, read by "
            "no production code, and covered only by a test that asserted a "
            "dict against itself (#669)."
        )

    def test_the_rule_can_actually_fire(self):
        """Prove the rule rejects a real #669 entry and accepts a real live one.

        ``home_consumption`` is the exact key SEM_SENSORS carried — the real
        entity is ``home_consumption_power``, so it names nothing. Checking
        both directions matters: a rule that only ever passes, and a rule that
        flags everything, are equally useless.
        """
        keys = _entity_keys()
        pattern = r'"[a-z_]+\.sem_([a-z0-9_]+)"'

        dead = re.findall(pattern, 'X = {"a": "sensor.sem_home_consumption"}')
        assert dead and dead[0] not in keys, (
            "the drifted SEM_SENSORS entry #669 was about would not be caught"
        )

        live = re.findall(pattern, 'Y: Final = "sensor.sem_solar_power"')
        assert live and live[0] in keys, (
            "the rule would flag ENTITY_SOLAR_POWER, which is a real entity — "
            "a guard that cries wolf gets routed around"
        )
