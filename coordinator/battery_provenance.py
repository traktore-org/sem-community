"""#770 — where the energy in the battery came from, and what it cost.

``daily_battery_charge`` is one number for two different things. A kWh that
came off the roof is free; a kWh bought in the cheap valley cost money. SEM
discharged both against the full import price and called the difference
savings — which was near enough while grid charging was rare, and stopped
being near enough the moment the joint planner started force-charging the
battery on any night with a deficit.

The fix is to treat the battery as what it is: **inventory with a cost
basis.** Energy goes in tagged by origin; energy comes out drawn from what is
stored, in proportion — because electrons are not tagged and pretending
otherwise would be a fiction dressed as a measurement.

Three deliberate choices:

* **Weighted average, not FIFO.** A pool has one blended price. FIFO would
  imply SEM knows which kWh left first, which it does not.
* **Unknown is its own bucket.** A discharge with nothing in the pool (fresh
  install, restored-from-nothing, another controller charging the battery)
  yields ``unknown_kwh``, never ``solar_kwh``. Assuming solar is the
  optimistic answer and #755 contract 1 forbids recording an assumption as a
  measurement. Downstream keeps the legacy credit for unknown energy — the
  number does not move until SEM actually knows better — but the kWh is
  counted, so #773 can audit how much of the ledger still rests on it.
* **Tied back to a measurement.** Integrated power drifts; SOC is measured.
  ``reconcile_to_stored`` scales the pool to the measured contents, so a
  month of rounding cannot invent stored energy — and when the pool is SHORT
  the difference arrives as unknown, not as a windfall of free solar.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

# One battery with no per-battery sensors — the common install. Named so the
# single-battery pool has a stable key across restarts and never collides
# with a real battery id.
FLEET_KEY = "fleet"


@dataclass
class DischargeMix:
    """What one discharge was made of.

    ``grid_cost`` is currency, not a rate: it is what the grid part of THIS
    discharge originally cost. Keeping the money rather than the price avoids
    re-deriving an average that has already been blended.
    """

    solar_kwh: float = 0.0
    grid_kwh: float = 0.0
    grid_cost: float = 0.0
    unknown_kwh: float = 0.0

    @property
    def total_kwh(self) -> float:
        return self.solar_kwh + self.grid_kwh + self.unknown_kwh


@dataclass
class _Pool:
    """One battery's contents, by origin."""

    solar_kwh: float = 0.0
    grid_kwh: float = 0.0
    grid_cost: float = 0.0      # currency still tied up in the grid part
    unknown_kwh: float = 0.0

    @property
    def total(self) -> float:
        return self.solar_kwh + self.grid_kwh + self.unknown_kwh


def allocate_fleet_charge(
    charge_power_w: Mapping[str, float], solar_kwh: float, grid_kwh: float,
) -> Dict[str, Tuple[float, float]]:
    """Split the FLEET's solar/grid charge across the batteries taking it.

    The flow layer attributes solar vs grid for the whole house; which
    physical battery received the solar electrons is unknowable. So the split
    follows the only evidence there is — how hard each battery was charging
    this cycle. Same honesty as the discharge draw.

    Returns ``{battery_id: (solar_kwh, grid_kwh)}``. An install with no
    per-battery power sensors gets one ``fleet`` pool holding the lot.
    """
    if not charge_power_w:
        return {FLEET_KEY: (float(solar_kwh), float(grid_kwh))}

    total_w = sum(max(0.0, float(w or 0.0)) for w in charge_power_w.values())
    if total_w <= 0:
        return {bid: (0.0, 0.0) for bid in charge_power_w}

    out: Dict[str, Tuple[float, float]] = {}
    for bid, w in charge_power_w.items():
        share = max(0.0, float(w or 0.0)) / total_w
        out[bid] = (float(solar_kwh) * share, float(grid_kwh) * share)
    return out


def discharge_savings(mix: DischargeMix, import_rate: float) -> float:
    """What this discharge actually saved.

    A solar kWh displaces a purchase, so it saves the whole import rate. A
    grid kWh only saves the SPREAD — it was bought, and that purchase already
    appears in the import cost. Unknown energy keeps the legacy credit: we do
    not know, so we do not move the number.

    A negative result is returned as-is. A battery bought at 0.30 and
    discharged against 0.20 lost money, and clamping that to zero would hide
    exactly the mistake the user needs to see.
    """
    rate = float(import_rate or 0.0)
    return (
        (mix.solar_kwh + mix.unknown_kwh) * rate
        + mix.grid_kwh * rate
        - mix.grid_cost
    )


class BatteryProvenance:
    """Per-battery inventory of stored energy and what it cost."""

    def __init__(self) -> None:
        self._pools: Dict[str, _Pool] = {}

    # ── writes ────────────────────────────────────────────────────────

    def charge(
        self, battery_id: str, solar_kwh: float, grid_kwh: float,
        import_rate: float,
    ) -> None:
        """Put energy in, tagged by where it came from."""
        solar_kwh = max(0.0, float(solar_kwh or 0.0))
        grid_kwh = max(0.0, float(grid_kwh or 0.0))
        if not solar_kwh and not grid_kwh:
            return
        pool = self._pools.setdefault(battery_id, _Pool())
        pool.solar_kwh += solar_kwh
        pool.grid_kwh += grid_kwh
        pool.grid_cost += grid_kwh * max(0.0, float(import_rate or 0.0))

    def discharge(self, battery_id: str, kwh: float) -> DischargeMix:
        """Take energy out, drawn from the pool in proportion.

        More than the pool holds means SEM missed some charging; the excess
        is ``unknown``, and the pool empties rather than going negative.
        """
        kwh = max(0.0, float(kwh or 0.0))
        if not kwh:
            return DischargeMix()

        pool = self._pools.get(battery_id)
        if pool is None or pool.total <= 0:
            return DischargeMix(unknown_kwh=kwh)

        drawn = min(kwh, pool.total)
        share = drawn / pool.total

        solar = pool.solar_kwh * share
        grid = pool.grid_kwh * share
        unknown = pool.unknown_kwh * share
        cost = pool.grid_cost * share

        pool.solar_kwh -= solar
        pool.grid_kwh -= grid
        pool.unknown_kwh -= unknown
        pool.grid_cost -= cost

        return DischargeMix(
            solar_kwh=solar, grid_kwh=grid, grid_cost=cost,
            unknown_kwh=unknown + (kwh - drawn),
        )

    def discharge_fleet(self, kwh: float) -> DischargeMix:
        """Take energy out of the FLEET, drawn from every pool in proportion.

        SEM measures one ``battery_discharge_power`` for the whole house.
        Which physical unit supplied it is not observable, so the draw
        follows the only evidence there is — what each pool holds. Same
        honesty as :func:`allocate_fleet_charge` on the way in.
        """
        kwh = max(0.0, float(kwh or 0.0))
        if not kwh:
            return DischargeMix()

        total = sum(p.total for p in self._pools.values())
        if total <= 0:
            return DischargeMix(unknown_kwh=kwh)

        drawn = min(kwh, total)
        out = DischargeMix(unknown_kwh=kwh - drawn)
        for bid, pool in self._pools.items():
            if pool.total <= 0:
                continue
            part = self.discharge(bid, drawn * (pool.total / total))
            out.solar_kwh += part.solar_kwh
            out.grid_kwh += part.grid_kwh
            out.grid_cost += part.grid_cost
            out.unknown_kwh += part.unknown_kwh
        return out

    def reconcile_fleet_to_stored(self, stored_kwh: Optional[float]) -> None:
        """Pin the WHOLE fleet to the measured SOC.

        The per-battery twin needs a per-battery capacity SEM rarely knows;
        the fleet SOC it always has. Long → every pool scales down, ratios
        preserved. Short → the difference is unknown energy, parked on the
        fleet pool rather than credited to any unit.
        """
        if stored_kwh is None:
            return
        try:
            target = max(0.0, float(stored_kwh))
        except (TypeError, ValueError):
            return

        total = sum(p.total for p in self._pools.values())
        if total <= 0:
            self.reconcile_to_stored(FLEET_KEY, target)
            return

        if target < total:
            scale = target / total
            for pool in self._pools.values():
                pool.solar_kwh *= scale
                pool.grid_kwh *= scale
                pool.grid_cost *= scale
                pool.unknown_kwh *= scale
        else:
            self._pools.setdefault(FLEET_KEY, _Pool()).unknown_kwh += target - total

    def reconcile_to_stored(
        self, battery_id: str, stored_kwh: Optional[float]
    ) -> None:
        """Pin the pool to what the battery actually holds.

        ``stored_kwh`` comes from SOC × capacity — a measurement. When the
        pool is LONG it is scaled down and the origin ratio (and therefore
        the per-kWh cost) is preserved. When it is SHORT the difference is
        energy SEM did not see arrive, which is unknown, not free solar.

        A missing SOC does nothing at all — silence is not a measurement of
        zero (#755 contract 1).
        """
        if stored_kwh is None:
            return
        try:
            target = max(0.0, float(stored_kwh))
        except (TypeError, ValueError):
            return

        pool = self._pools.setdefault(battery_id, _Pool())
        total = pool.total
        if total <= 0:
            pool.unknown_kwh = target
            pool.solar_kwh = pool.grid_kwh = pool.grid_cost = 0.0
            return

        if target < total:
            scale = target / total
            pool.solar_kwh *= scale
            pool.grid_kwh *= scale
            pool.grid_cost *= scale
            pool.unknown_kwh *= scale
        else:
            pool.unknown_kwh += target - total

    # ── reads ─────────────────────────────────────────────────────────
    #
    # Deliberately fleet-level only. The per-battery twins (``stored_kwh``,
    # ``grid_fraction``, ``avg_grid_cost``) were written alongside these and
    # had no caller anywhere in production — SEM measures one fleet SOC and
    # publishes one fleet share, so nothing could ask a single unit. The #653
    # orphan guard caught them the day they were added, which is exactly what
    # it is for; they are deleted rather than kept "for later". The pools stay
    # per battery because CHARGING is per battery (#523), and what one pool
    # holds is observable through :meth:`get_state`.

    def fleet_grid_fraction(self) -> float:
        """Share of ALL stored energy that was bought.

        This is what autarky needs: the house has one battery experience even
        when it has three physical units.
        """
        total = sum(p.total for p in self._pools.values())
        if total <= 0:
            return 0.0
        return sum(p.grid_kwh for p in self._pools.values()) / total

    def fleet_grid_share_measured(self) -> Optional[float]:
        """The published twin of :meth:`fleet_grid_fraction` — honest about
        not knowing.

        ``None`` until the pool holds energy whose origin SEM actually
        watched arrive (the ATTRIBUTED content, solar or grid). A pool that
        is empty, or holds only SOC-pinned UNKNOWN energy, has no opinion:
        0.0 from it would publish "nothing was bought" with the confidence
        of a measurement — which the .175 soak caught on the arc's own
        first night (#755 contract 1: silence is not a measurement of
        zero).

        Autarky keeps :meth:`fleet_grid_fraction`'s 0.0 on purpose — its
        degrade path IS the legacy full-credit answer, and the rate math
        cannot take an ``unknown``. Only the published share may say so.
        """
        attributed = sum(
            p.solar_kwh + p.grid_kwh for p in self._pools.values()
        )
        if attributed <= 0:
            return None
        return self.fleet_grid_fraction()

    def implied_savings_rate(self, import_rate: float) -> float:
        """Currency saved per kWh discharged from what is stored RIGHT NOW.

        The whole pool displaces an import, so it earns ``import_rate``;
        what the bought part originally cost has to come back off. An empty
        pool returns the rate unchanged — SEM knows nothing, so the number
        does not move.
        """
        rate = float(import_rate or 0.0)
        total = sum(p.total for p in self._pools.values())
        if total <= 0:
            return rate
        return rate - (sum(p.grid_cost for p in self._pools.values()) / total)

    # ── persistence ───────────────────────────────────────────────────

    def get_state(self) -> Dict[str, Any]:
        return {
            "pools": {
                bid: {
                    "solar_kwh": round(p.solar_kwh, 4),
                    "grid_kwh": round(p.grid_kwh, 4),
                    "grid_cost": round(p.grid_cost, 5),
                    "unknown_kwh": round(p.unknown_kwh, 4),
                }
                for bid, p in self._pools.items()
            }
        }

    def restore_state(self, state: Optional[Mapping[str, Any]]) -> None:
        """Load a persisted inventory. Junk is dropped, never fatal — a
        corrupt store must degrade to 'SEM knows nothing yet', which the
        unknown bucket already models honestly."""
        if not isinstance(state, Mapping):
            return
        pools = state.get("pools")
        if not isinstance(pools, Mapping):
            return
        for bid, raw in pools.items():
            if not isinstance(raw, Mapping):
                continue
            try:
                pool = _Pool(
                    solar_kwh=max(0.0, float(raw.get("solar_kwh", 0.0) or 0.0)),
                    grid_kwh=max(0.0, float(raw.get("grid_kwh", 0.0) or 0.0)),
                    grid_cost=max(0.0, float(raw.get("grid_cost", 0.0) or 0.0)),
                    unknown_kwh=max(0.0, float(raw.get("unknown_kwh", 0.0) or 0.0)),
                )
            except (TypeError, ValueError):
                _LOGGER.debug("Dropping unreadable battery pool %s", bid)
                continue
            self._pools[bid] = pool
