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
``_energy`` suffix) and are fixed. The remaining 33 name entities that do not
exist anywhere — renamed, never built, or superseded by a per-device dynamic
key — and each needs an individual verdict: repoint, build, or delete. Some are
near-misses of a *different* shape (``daily_ev_consumption`` vs the working
``daily_ev_energy``) and are probably duplicate intent that should be deleted,
not repointed, or the entity ends up double-labelled.

So this is a **ratchet**, not a ban: the allowlist below is the debt, it may
only shrink, and a newly-typo'd label key fails immediately.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from custom_components.solar_energy_management.consts.labels import (
    SENSOR_LABEL_MAPPING,
)

_ROOT = Path(__file__).resolve().parent.parent

# Every platform that can declare an EntityDescription key.
_PLATFORMS = (
    "sensor.py", "binary_sensor.py", "number.py", "select.py",
    "switch.py", "button.py", "text.py", "time.py",
)

# Label keys with no entity anywhere, as of #667. MAY ONLY SHRINK.
# Do NOT add to this list — a new entry means a label that labels nothing.
KNOWN_ORPHAN_LABELS = frozenset({
    "autarky_rate_daily", "automation_decision_reason", "battery_current",
    "battery_cycles", "battery_efficiency", "battery_health",
    "battery_voltage", "charging_automation_status",
    "controlled_tariff_status", "daily_ev_consumption", "daily_solar_yield",
    "energy_balance_check", "energy_data_quality", "energy_tracking_mode",
    "ev_charging_power", "ev_max_current", "ev_max_current_available",
    "ev_session_energy", "ev_total_energy", "grid_frequency",
    "grid_management_status", "inverter_efficiency", "inverter_load_ratio",
    "last_update", "load_balancer_l1", "load_balancer_l2", "load_balancer_l3",
    "load_balancer_total", "power_factor", "self_consumption_rate_daily",
    "solar_efficiency", "solar_optimization_status", "solar_utilization",
})


def _entity_keys() -> set[str]:
    keys: set[str] = set()
    for name in _PLATFORMS:
        path = _ROOT / name
        if path.exists():
            keys |= set(re.findall(r'key="([a-z0-9_]+)"', path.read_text()))
    return keys


@pytest.mark.unit
class TestLabelRegistry667:
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
