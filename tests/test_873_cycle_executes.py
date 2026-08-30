"""#873 — RUN the coordinator's main cycle, don't just read it.

``_async_update_data`` is 2236 lines and publishes 325 values: every sensor
SEM exposes, every number its cards render, every input its decisions act on.
Thirteen test files mention it. Every one of them via
``inspect.getsource(...)``. Until this file, nothing ever ran it.

Nothing ran it indirectly either: ``conftest.py``'s ``async_refresh()`` is a
no-op mock, and ``scenario_harness.py`` PARALLELS the cycle — it calls the
same sub-functions (``_build_charging_context``, "which is what
coordinator._async_update_data also calls") rather than driving the
orchestration. A parallel structure can drift from what it mirrors, and the
harness's own comment records that it already has: *"Pre-arch-rewrite the
harness called the long-removed ``_determine_charging_strategy`` directly and
re-implemented the legacy→canonical mapping inline (the exact pattern v1.6.2
caught)."*

That is the structural cause behind three #778 defects (see #873): SEM tests
its PARTS thoroughly and its ASSEMBLY structurally. An AST guard proves a name
is in scope; it cannot see a wrong formula, and all three defects were wrong
formulas with every name in scope.

The barrier was never real. A cycle needs a hass whose ``states.get`` returns
states and a ``config`` carrying a currency — about fifteen lines. It simply
was never done.

What this file asserts is deliberately about the ASSEMBLY, not the parts:
the cycle completes, the energy balance closes, and every published number is
one the surface can actually render. That last class is what caught the two
defects this audit found in #778's own assembly — a refill of 35.5 kWh onto a
12.5 kWh pack, and a floor of 115.7 %.
"""
from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

WIRED = {
    "solar_production_sensor": "sensor.solar",
    "grid_power_sensor": "sensor.grid",
    "battery_power_sensor": "sensor.batt",
    "battery_soc_sensor": "sensor.soc",
    "ev_power_sensor": "sensor.ev",
    "battery_capacity_kwh": 15.0,
    "battery_reserve_soc": 20,
}


class _States:
    """A real state registry — ``get`` returns a state or None, never a mock.

    Handing the cycle a MagicMock states object is what made it look
    untestable: every read came back as a MagicMock and the first comparison
    raised, which the cycle's blanket handler turned into ``UpdateFailed``.
    """

    def __init__(self, mapping=None):
        self._m = dict(mapping or {})

    def get(self, entity_id):
        if entity_id not in self._m:
            return None
        return SimpleNamespace(entity_id=entity_id, state=str(self._m[entity_id]),
                               attributes={}, last_updated=None, last_reported=None)

    def async_all(self, *args, **kwargs):
        return []


def _hass(states=None):
    hass = MagicMock()
    hass.states = _States(states)
    hass.config = SimpleNamespace(
        time_zone="Europe/Zurich", language="en", currency="CHF", country="CH",
        units=SimpleNamespace(temperature_unit="°C"),
    )
    return hass


async def run_cycle(config=None, states=None, nights=None) -> dict:
    """One real turn of the main cycle.

    ``nights`` seeds #800's sealed night records. Without them the learned
    terms (measured capacity, overnight need) are None, ``spendable_budget``
    exits on the dark input, and the whole #778 verdict path is never
    reached — a scenario table that never seeds them is a smoke test wearing
    a scenario table's clothes. Proven the hard way: with no history seeded,
    removing the dynamic-floor clamp did not fail a single assertion here.
    """
    coord = SEMCoordinator(_hass(states), dict(config or {}))
    coord.config_entry = None      # skip the first-refresh storage restore
    if nights is not None:
        coord._battery_night = SimpleNamespace(sealed=lambda: nights)
    return await coord._async_update_data()


def sealed_nights(count=40, drain_kwh=6.5, soc_span=52.0):
    """``count`` qualifying nights: each drew ``drain_kwh`` over ``soc_span``
    percent, i.e. 0.125 kWh/% — a 12.5 kWh usable pack behind the 15 kWh
    nameplate. PROD measures 12.63 against the same nameplate."""
    import datetime
    today = datetime.date(2026, 8, 30)
    return [
        {"date": (today - datetime.timedelta(days=i + 1)).isoformat(),
         "soc_start": 90.0, "soc_morning": 90.0 - soc_span,
         "drain_kwh": drain_kwh, "surplus_kwh": 3.0,
         "held_s": 0, "clipped_s": 0,
         "usable": True, "trainable": True, "quality": "ok"}
        for i in range(count)
    ]


def _sensors(solar, grid, batt, soc, ev=0):
    return {"sensor.solar": solar, "sensor.grid": grid, "sensor.batt": batt,
            "sensor.soc": soc, "sensor.ev": ev}


#: sunny / night / flat / peak / evening / degraded — the shapes a real day
#: passes through, including the two that historically broke things: a FULL
#: pack, and inputs that went dark mid-cycle.
SCENARIOS = [
    ("bare install, nothing configured", {}, None, None),
    ("sunny, exporting, battery filling, SOC 100",
     WIRED, _sensors(6000, 2000, 1500, 100), None),
    ("night, importing, battery covering the house, SOC 45",
     WIRED, _sensors(0, -3000, -2000, 45), None),
    ("empty pack, heavy import, SOC 0",
     WIRED, _sensors(0, -8000, 0, 0), None),
    ("peak: 12 kW solar, EV drawing 7 kW, exporting",
     WIRED, _sensors(12000, 9000, 3000, 100, ev=7000), None),
    ("degraded: solar unavailable, grid unknown",
     WIRED, _sensors("unavailable", "unknown", 0, 55), None),
    # ── with a season of night history behind it: the learned terms exist,
    #    so the #778 verdict path actually runs.
    ("learned pack, full, evening",
     WIRED, _sensors(500, -1000, -400, 100), "SEALED"),
    ("learned pack, reserve 50 % — a night bigger than the pack",
     {**WIRED, "battery_reserve_soc": 50, "forecast_spending_enabled": True},
     _sensors(500, -1000, -400, 100), "SEALED"),
    ("learned pack, mid SOC, spend arc awake",
     {**WIRED, "forecast_spending_enabled": True},
     _sensors(0, -2000, -1500, 60), "SEALED"),
]

#: A key naming a BOUNDED proportion — something that is 0-100 of a whole.
_PCT_HINTS = ("_pct", "_percentage", "rate", "soc", "share", "efficiency", "score")
#: A quantity is never a percentage however it is spelled.
_QUANTITY_SUFFIXES = ("_kwh", "_w", "_power", "_wh", "_kw")
#: …and neither is a SIGNED DELTA. ``battery_capacity_drift_pct`` is -16.7 on
#: a pack measuring 12.5 kWh against a 15 kWh nameplate, and that minus sign
#: is the whole point of the number (PROD reports -15.8 % the same way).
#: Lumping deltas in with proportions made this guard cry wolf on correct
#: code the first time it was pointed at real night history — and a guard
#: that cries wolf gets deleted, which is how the gap in #873 opened.
_SIGNED_DELTA_HINTS = ("drift", "delta", "change", "offset", "error", "bias",
                       "trend", "diff", "vs_")


def _looks_like_a_percentage(key: str) -> bool:
    """True for a value that must land in 0-100."""
    if key.endswith(_QUANTITY_SUFFIXES):
        return False
    if any(hint in key for hint in _SIGNED_DELTA_HINTS):
        return False
    return any(hint in key for hint in _PCT_HINTS)


def _nights(marker):
    return sealed_nights() if marker == "SEALED" else None


@pytest.mark.asyncio
@pytest.mark.parametrize("label,config,states,nights", SCENARIOS,
                         ids=[s[0] for s in SCENARIOS])
class TestTheCycleRunsAndPublishesPhysicalNumbers:

    async def test_the_cycle_completes(self, label, config, states, nights):
        data = await run_cycle(config, states, _nights(nights))
        assert isinstance(data, dict) and data, (
            f"the main cycle produced nothing for: {label}"
        )

    async def test_no_stub_leaks_into_published_data(self, label, config, states, nights):
        """A MagicMock reaching a published value means a collaborator was
        never really exercised — the test would be passing on scaffolding."""
        data = await run_cycle(config, states, _nights(nights))
        leaked = {k: v for k, v in data.items() if isinstance(v, MagicMock)}
        assert not leaked, f"mock objects published as data: {sorted(leaked)}"

    async def test_every_number_is_finite(self, label, config, states, nights):
        data = await run_cycle(config, states, _nights(nights))
        bad = {k: v for k, v in data.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)
               and not math.isfinite(float(v))}
        assert not bad, f"non-finite published values: {bad}"

    async def test_a_percentage_is_a_percentage(self, label, config, states, nights):
        """The class that caught ``battery_dynamic_floor_pct = 115.7`` — a
        true statement about an impossible night, but not a number any gauge
        can render, and read downstream as a floor SOC no SOC can reach."""
        data = await run_cycle(config, states, _nights(nights))
        bad = {k: v for k, v in data.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)
               and _looks_like_a_percentage(k)
               and not (-0.001 <= float(v) <= 100.001)}
        assert not bad, f"published outside 0-100 while naming a percentage: {bad}"

    async def test_the_house_never_draws_negative_power(self, label, config, states, nights):
        """``home_consumption_power`` is clamped at 0 on purpose and must
        never be None — the balance can go negative on a bad sign, and the
        answer is to fix the upstream sign, never to publish a negative
        house or an unknown."""
        home = (await run_cycle(config, states,
                                _nights(nights))).get("home_consumption_power")
        assert home is not None, "the house must always report a number"
        assert float(home) >= 0.0, f"home consumption published as {home}"


@pytest.mark.asyncio
async def test_the_energy_balance_closes():
    """solar − export − charge = house, through the REAL cycle.

    The pipeline tests prove this for ``SensorReader`` in isolation. This
    proves the assembly does not lose it on the way to the published dict.
    """
    data = await run_cycle(WIRED, _sensors(6000, 2000, 1500, 77))
    assert data["solar_power"] == 6000
    assert data["grid_export_power"] == 2000
    assert data["grid_import_power"] == 0
    assert data["battery_charge_power"] == 1500
    assert data["battery_soc"] == pytest.approx(77.0)
    assert data["home_consumption_power"] == pytest.approx(
        6000 - 2000 - 1500), "the balance the whole integration rests on"


@pytest.mark.asyncio
async def test_the_wiring_is_real_not_defaulted():
    """Guard against the vacuous pass: if the configured sensors were not
    actually read, every scenario above would sweep a table of zeros and
    report itself green."""
    data = await run_cycle(WIRED, _sensors(6000, 2000, 1500, 77))
    assert data["solar_power"] == 6000, (
        "the configured solar sensor never reached the published data — "
        "the scenarios above would then be asserting nothing"
    )
