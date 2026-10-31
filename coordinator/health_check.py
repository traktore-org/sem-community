"""SEM Health Check — periodic validation of calculation integrity.

#660 — what this can and cannot see.

Most of what used to live here was **clamp-then-check**: verify ``0 ≤ x ≤ 100``
on a value whose only producer clamps it to ``[0, 100]`` three lines after
computing it, or ``≥ 0`` on a ``max(0, …)`` field. Those checks are
algebraically unfireable, so ``diag_health_violations: 0`` read as
"calculations verified" when it meant "nothing was actually examined". The
HA-PROD 2026-06-01 autarky bug (pinned at 0 % while self-consumption read
98 %) is an *in-range wrong number*: the instrument blessed it, and the whole
sign-bug family stayed invisible to it for a year.

The replacement instrument is **clamp engagement** — how much each guard
actually had to remove. The clamped output is definitionally clean; the
removal is the evidence. One engaged cycle is a rounding or transient
artefact, so a violation is only raised after the same clamp has engaged for
``_CLAMP_CYCLES`` consecutive cycles. See ``EnergyCalculator._record_clamp``
and ``PowerReadings.home_residual_clamped_w``.

The same rule applies to the flow checks: a greedy allocator that drains
``min(avail, need)`` cannot over-allocate a source or emit a negative flow, so
asserting those two things about its own output in the same cycle proves
nothing. What is NOT by construction is a cross-producer invariant — e.g. the
per-string sensors versus the inverter total — and that's what remains here.
"""
import logging
from typing import Iterable, Mapping, Optional

from .types import CostData, EnergyFlows, EnergyTotals, PowerFlows, PowerReadings

_LOGGER = logging.getLogger(__name__)


def sem_ev_chargers(coordinator) -> list:
    """(#1044) SEM's own EV chargers — both discovery shapes, deduped by
    identity.

    The multi-charger dict AND the legacy ``_ev_device`` single-charger
    slot (the walk ``_push_observer_mode_to_devices`` does, for the reason it
    gives). ``getattr`` throughout: the filing seam runs on bare stubs in
    tests, and a stub with no chargers simply has none.
    """
    devs = [d for d in (getattr(coordinator, "_ev_devices", None) or {}).values()
            if d is not None]
    single = getattr(coordinator, "_ev_device", None)
    if single is not None and not any(d is single for d in devs):
        devs.append(single)
    return devs


def chargers_outside_home(chargers, power) -> list:
    """(#1044) The chargers whose draw this cycle's ``ev_power`` holds.

    ``home`` takes ``ev_power`` out, so these are already out of it. A
    charger is in ``ev_power`` when its own sensor was summed, or when one
    fleet sensor (Energy Dashboard or the top-level sensor) was read for
    the whole EV side. A charger the reader never read — a second box with
    no sensor of its own, a late-found box with no power sensor (#1125
    hands over the one it has) — is still inside ``home``, and stays a
    member.
    """
    if getattr(power, "ev_power_fleet_entity", None):
        return [c for c in (chargers or ()) if c is not None]
    read = getattr(power, "ev_power_entities", None) or frozenset()
    return [c for c in (chargers or ())
            if c is not None and getattr(c, "power_entity_id", None) in read]


def home_members(devices, chargers) -> list:
    """(#1044) The devices whose draw is INSIDE the home row.

    The one answer for every reader that adds devices up against ``home``:
    the true-baseload mirror and its W twin, and the partition check below.
    ``chargers`` are SEM's own EV chargers that ``ev`` holds
    (``chargers_outside_home``); they are not inside it::

        home = max(0, solar + grid_import + batt_discharge
                      - ev - grid_export - batt_charge)

    and ``ev`` is read from those chargers' power sensors. #872 drew this
    line for the partition check alone; the baseload (#773) never drew it, so
    it took the car out of ``home`` a second time — RienduPre (#1044): a
    49 kWh night session, 6.29 kWh of home, a true baseload of −49.69 kWh.

    Matched by IDENTITY, not by type: a load the user put under current
    control (a heater on an amps number, a second box added as a load) is a
    ``CurrentControlDevice`` too, and its draw is not in ``ev`` — it stays.
    """
    outside = {id(c) for c in (chargers or ()) if c is not None}
    return [d for d in (devices or ()) if id(d) not in outside]


def home_member_totals(devices, chargers) -> dict:
    """(#872) The controlled loads that are genuinely members of the HOME row.

    EV chargers are not — see ``home_members``, which decides it. Counting a
    charger here puts its energy on one side of a comparison that removed it
    from the other, and every install charging a car reports a permanent
    "double count" that no amount of looking can resolve — the message even
    names a stale id, sending the user hunting for something that does not
    exist (#872, RienduPre: members 3.34 kWh against a 1.81 kWh home row,
    repeating for hours, every member live and real; without his
    ``ev_charger=1.10`` the sum is 2.24 and sits inside the band).

    Chargers are checked against the EV day instead, which is the row they
    are actually members of.
    """
    out = {}
    for dev in home_members(devices, chargers):
        device_id = getattr(dev, "device_id", None)
        if not device_id:
            continue
        out[device_id] = float(getattr(dev, "daily_energy_kwh", 0.0) or 0.0)
    return out


def home_member_evidence(devices) -> dict:
    """(#979) For each home member, WHERE its daily number came from.

    ``home_member_totals`` answers "how much"; when the reconciler below says
    two ids carry the same energy, the next question is always "which sensor
    told you that, and what does it read right now?" — and a bucket alone
    cannot answer it. RienduPre (#979, 2026-09-13) got ``heat_pump=1906.00kWh``
    against a home row a thousandth of that, and by the time anyone looked
    the violation had self-resolved with nothing on record: a day's bucket that
    size is a LIFETIME counter read as a day, which the source and its raw
    value say in one line and the bucket says not at all.

    Every term is already on the device (``daily_energy_source``,
    ``energy_entity_id``, the counter's last raw read). A device that has no
    evidence to give — a rated-power estimate, no source at all — is simply
    absent from the map; the reconciler then names it without a suffix.
    """
    out = {}
    for dev in devices or []:
        device_id = getattr(dev, "device_id", None)
        if not device_id:
            continue
        source = getattr(dev, "daily_energy_source", None)
        if source not in ("counter", "power"):
            continue
        entity = (getattr(dev, "energy_entity_id", None)
                  if source == "counter"
                  else getattr(dev, "power_entity_id", None))
        detail = f"{source} {entity}" if entity else str(source)
        if source == "counter":
            raw = getattr(dev, "_energy_counter_last_kwh", None)
            if isinstance(raw, (int, float)):
                detail += f" reads {float(raw):.2f}kWh"
        blind = float(getattr(dev, "daily_energy_blind_s", 0.0) or 0.0)
        if blind > 0:
            detail += f", blind {blind:.0f}s today"
        out[str(device_id)] = detail
    return out


def power_terms(power) -> str:
    """(#979) The six readings the home residual is computed FROM.

    ``PowerReadings.calculate_derived`` builds the residual out of these and
    nothing else, and every one of them is in hand at each site that reports a
    disagreement about it. Reporting only the aggregate (``clamped by 2887W``)
    sends the owner to reverse-engineer SEM's formula before they can even
    pick a sensor to suspect; naming the terms costs one f-string and turns
    the message into "look at this one".
    """
    # FLEET-READ: the residual is a FLEET quantity — the health check
    # reports the six terms the balance is built from and controls nothing.
    return (
        f"supply: solar={power.solar_power:.0f}W "
        f"grid_import={power.grid_import_power:.0f}W "
        f"battery_discharge={power.battery_discharge_power:.0f}W | "
        f"demand: ev={power.ev_power:.0f}W "  # FLEET-READ: fleet demand term
        f"grid_export={power.grid_export_power:.0f}W "
        f"battery_charge={power.battery_charge_power:.0f}W"
    )


def largest_demand_term(power) -> str:
    """(#979) The demand term to suspect first when the residual goes negative.

    A negative residual means the demand side outweighs everything coming in,
    so the biggest demand reading is where an inverted sign or a stale value
    does the most damage. Named as a suspect, never as a verdict — a house
    charging a car legitimately has ``ev`` on top.
    """
    # FLEET-READ: same quantity as power_terms — the fleet's EV draw as one
    # demand term of the residual, never a per-charger decision.
    terms = {
        "ev": float(power.ev_power or 0.0),  # FLEET-READ: fleet demand term
        "grid_export": float(power.grid_export_power or 0.0),
        "battery_charge": float(power.battery_charge_power or 0.0),
    }
    name, value = max(terms.items(), key=lambda kv: (kv[1], kv[0]))
    return f"{name}={value:.0f}W"


def balance_tolerance_w(power) -> float:
    """(#1234) Two meters never agree to the watt: 50 W, or 2 % of the largest
    demand term when that is more. A real sign error is thousands of watts."""
    # FLEET-READ: fleet demand terms sized against the whole-house balance.
    biggest = max(
        float(power.home_consumption_power or 0.0),
        float(power.ev_power or 0.0),  # FLEET-READ: fleet demand term
        float(power.grid_export_power or 0.0),
        float(power.battery_charge_power or 0.0),
    )
    return max(50.0, 0.02 * biggest)


class HealthCheck:
    """Validates energy balance and calculation integrity each cycle."""

    # After this many consecutive violating cycles the per-cycle WARNING
    # drops to debug until the violations clear (#487 triage logs: 413
    # near-identical lines drowned the log + diagnose ring buffer).
    _WARN_CYCLES = 6

    # (#660) A clamp must engage for this many CONSECUTIVE cycles before it
    # counts as a violation. At the 10 s coordinator cycle that's ~5 minutes
    # — long enough that a stale sensor or a rounding wobble has cleared,
    # short enough that a wrong formula is reported the same session.
    _CLAMP_CYCLES = 30

    # (#771) Tolerance for a per-device breakdown against the fleet row it
    # decomposes. See ``_reconcile_partition`` for why both numbers are what
    # they are — and why only the over-count direction is checked at all.
    _PARTITION_REL_TOL = 0.10
    _PARTITION_ABS_FLOOR_KWH = 0.5

    def __init__(self) -> None:
        self._violation_count: int = 0
        self._last_violations: list[str] = []
        self._violation_streak: int = 0
        # (#660) clamp name → consecutive cycles it has been engaged.
        self._clamp_streaks: dict[str, int] = {}

    def check_power_balance(
        self, power: PowerReadings, home_hold_active: bool = False,
    ) -> list[str]:
        """Verify energy balance: solar + import + discharge ≈ home + ev + export + charge.

        ``home_consumption_power`` is derived as the residual of the
        other readings (``calculate_derived``), so the balance is an
        identity unless the residual went negative — inputs sampled
        at different instants (stale solar/EV/grid sensor) — and got
        clamped to 0 and/or replaced by the coordinator's home-hold
        (``_smooth_home_consumption``). While that hold is active the
        gap is a KNOWN, already-handled input inconsistency: report
        it at debug only, not as a violation. RienduPre's #461 dump
        showed 69 "violations" that were all the hold bridging a
        Growatt solar sensor frozen for ~5 min. Once the hold window
        is exhausted the gap is a genuinely stuck sensor and warns.
        """
        violations: list[str] = []

        supply = power.solar_power + power.grid_import_power + power.battery_discharge_power
        demand = (
            power.home_consumption_power
            # FLEET-READ: whole-house energy balance check — needs the
            # fleet EV total to validate supply ≈ demand.
            + power.ev_power
            + power.grid_export_power
            + power.battery_charge_power
        )
        imbalance = abs(supply - demand)
        tolerance = balance_tolerance_w(power)

        # (#660) The residual the home-consumption clamp had to remove.
        #
        # These two are ONE fault reported two ways, so they are mutually
        # exclusive. When the residual went negative, ``home_consumption_power``
        # is 0 and the balance gap above is exactly the amount the clamp
        # removed — reporting both doubles ``diag_health_violations`` and logs
        # the same disagreement twice per cycle. The clamp record is the
        # sharper of the two (it names the direction: the inputs demand a
        # NEGATIVE house load), so it wins when it is engaged.
        #
        # The balance check is NOT redundant in general, which is why it
        # survives as the fallback: ``_smooth_home_consumption`` can replace
        # ``home_consumption_power`` AFTER ``calculate_derived`` has run, and
        # once the hold window is exhausted a held value that no longer
        # matches live inputs shows up here with the clamp record at 0.
        clamped = float(getattr(power, "home_residual_clamped_w", 0.0) or 0.0)
        if clamped > tolerance:
            if home_hold_active:
                _LOGGER.debug(
                    "Home-consumption residual clamped by %.0fW while the "
                    "hold is bridging — known input inconsistency (%s)",
                    clamped, power_terms(power),
                )
            else:
                # (#979) The six inputs, and the one to look at first. The
                # message used to carry the aggregate alone, so the owner had
                # to reverse-engineer which readings SEM even builds the
                # residual from before they could suspect a sensor — while
                # every term was in hand right here.
                violations.append(
                    f"Home consumption residual clamped by {clamped:.0f}W "
                    f"(inputs produce a NEGATIVE house load — a power sensor "
                    f"is stale or its sign is inverted). "
                    f"{power_terms(power)}. "
                    f"Largest demand term: {largest_demand_term(power)}"
                )
        elif imbalance > tolerance:  # rounding and meter noise (#1234)
            if home_hold_active:
                _LOGGER.debug(
                    "Energy balance gap %.0fW (supply=%.0fW, demand=%.0fW) "
                    "bridged by the home-consumption hold — input sensors "
                    "momentarily inconsistent, not counted as a violation",
                    imbalance, supply, demand,
                )
            else:
                violations.append(
                    f"Energy balance: supply={supply:.0f}W, demand={demand:.0f}W, "
                    f"imbalance={imbalance:.0f}W (inputs inconsistent — a power "
                    f"sensor is likely stale). "
                    # (#979) Two aggregates named a disagreement the six terms
                    # behind them could identify; this branch already had them.
                    f"{power_terms(power)} "
                    f"home={power.home_consumption_power:.0f}W"
                )

        # Non-negative checks — RAW reads only.
        #
        # (#660) ``home_consumption``, ``grid_import``, ``grid_export``,
        # ``battery_charge`` and ``battery_discharge`` used to be in this
        # list. All five are ``max(0, ±scalar)`` in
        # ``PowerReadings.calculate_derived``, so they cannot be negative on
        # any production path and the check was inert padding — five sixths
        # of a loop that looked like coverage. What replaces them for the
        # derived home value is the clamp record above; the grid/battery
        # pairs have their own real instrument at the netting site
        # (``SplitSensorExclusivityAudit``, #661).
        #
        # These two survive because they are read straight off a sensor and
        # a negative value is genuinely possible (and genuinely wrong).
        non_negative_fields = [
            # FLEET-READ: health check iterates fleet-level fields; the
            # non-negative invariant applies to the whole-house EV total.
            ("ev_power", power.ev_power),
            ("solar_power", power.solar_power),
        ]
        for name, val in non_negative_fields:
            # (#660) −1 W was mistuned: an inverter idling overnight reports
            # a small negative (its own standby draw through the DC side),
            # and a KEBA on standby does the same. That's normal hardware
            # behaviour, not a calculation fault, and it produced violations
            # every night. −50 W still catches an inverted sign, which is
            # the failure this is here for.
            if val < -50:
                violations.append(f"{name} is negative: {val:.1f}W")

        # Mutual exclusivity is NOT checked here — it cannot be (#661).
        #
        # ``grid_import_power`` / ``grid_export_power`` (and the battery pair)
        # are not inputs: ``PowerReadings.calculate_derived`` re-derives all
        # four from ONE signed scalar with ``max(0, ±x)``. "Both active" is
        # therefore unrepresentable by construction on every production path,
        # and the check that used to live here could not fail — it read as
        # coverage while detecting nothing. Its unit test passed only because
        # it hand-built a ``PowerReadings``, bypassing the derivation.
        #
        # The real check runs where the evidence still exists: at each split
        # netting site in ``SensorReader``, via ``SplitSensorExclusivityAudit``
        # (``_audit_split_pair``), surfaced as the ``split_pair_exclusivity``
        # cross-check in the perception trace.

        return violations

    def check_flows(self, power: PowerReadings, flows: PowerFlows) -> list[str]:
        """Cross-producer flow invariants — the ones that aren't theorems.

        (#660) Two checks used to live here: "solar is not over-allocated" and
        "no flow is negative". ``calculate_power_flows`` is a greedy allocator
        that drains ``sources_left`` via ``delivered = min(avail, need)`` and
        skips any pair where either side is ``<= 0``. Both properties are
        therefore theorems of that loop, and they were being asserted about
        its own output, in the same cycle, with nothing in between. They could
        not fail, so they told a user with a real flow problem "health check
        clean" — the worst possible first lead.

        What survives is the invariant that spans two INDEPENDENT producers,
        so it can actually be false.
        """
        violations: list[str] = []

        # Per-PV-string sensors vs the inverter total. The strings are read
        # from their own entities; ``solar_power`` comes from the inverter's
        # AC total (or the Energy-Dashboard list). ``types.PowerReadings``
        # documents the invariant as ``sum(per_string) ≈ solar_power``.
        #
        # Only the OVER-count direction is checked, and deliberately so:
        # ``discover_pv_strings_from_registry`` caps discovery at 4 slots, so
        # an install with 5+ strings/inverters legitimately sums to LESS than
        # the total and an under-count check would fire forever on correct
        # hardware. An over-count has no benign reading — it means a string
        # entity is being double-counted, or the total is only one inverter
        # of several.
        if flows.solar_per_string:
            per_string = sum(
                float(v or 0.0) for v in flows.solar_per_string.values()
            )
            # 10 % or 100 W, whichever is larger. That looks slack until you
            # note WHICH side is being compared: the per-string values are
            # frequently DC (``sensor_reader._read_pv_string`` synthesises
            # V×I when the inverter exposes no per-string power entity, which
            # is the Huawei case on HA-PROD), while ``solar_power`` is the AC
            # total. Inverter efficiency alone puts the DC sum 2–5 % above the
            # AC total on a healthy system, and the two sides are sampled at
            # different instants on a moving cloud edge. A 2 % band false-fires
            # on correct hardware every sunny afternoon.
            #
            # The fault this exists to catch is not subtle: a string entity
            # counted twice (+100 %) or a total that covers one inverter of
            # several (+100 % and up). 10 % separates those from physics with
            # room to spare.
            tolerance = max(100.0, 0.10 * float(power.solar_power))
            if per_string > float(power.solar_power) + tolerance:
                # (#979) Name the strings. "The sum is too big" leaves the
                # owner to open four entities and add them up by hand; the
                # duplicate is usually obvious the moment the members are
                # listed (two slots reading the same watts), and the map is
                # right here.
                listed = ", ".join(
                    f"{sid}={float(v or 0.0):.0f}W"
                    for sid, v in sorted(
                        flows.solar_per_string.items(),
                        key=lambda kv: -float(kv[1] or 0.0),
                    )
                )
                violations.append(
                    f"PV strings sum to {per_string:.0f}W but the inverter "
                    f"total reads {power.solar_power:.0f}W — a string is "
                    f"double-counted, or the total covers fewer inverters "
                    f"than the strings do. Strings: {listed}"
                )

        return violations

    def _reconcile_partition(
        self,
        label: str,
        members: Mapping[str, float],
        fleet_total: float,
        live_ids: Optional[Iterable[str]] = None,
        member_evidence: Optional[Mapping[str, str]] = None,
    ) -> Optional[str]:
        """(#771) One breakdown against the fleet row it decomposes.

        Over-count only. The rationale is the same one that kept the
        per-string POWER check alive through #660 and killed everything
        around it: a shortfall has several correct explanations, so checking
        it would fire on healthy hardware every day, and a check that cries
        wolf gets muted. An EXCESS has none — the same physical energy is
        being counted under two ids.

        Legitimate shortfalls, for the record: string discovery caps at 4
        slots; each charger's daily bucket rolls at its own ``Charge by``
        deadline while the fleet EV day falls back to midnight when two
        chargers disagree (#723); ``_reconcile_solar_energy`` corrects
        ``daily_solar`` upward from the hardware counter (#556).
        """
        if not members:
            # No breakdown is not a disagreement — single-charger and
            # single-string installs never populate one.
            return None

        total = sum(float(v or 0.0) for v in members.values())
        fleet = float(fleet_total or 0.0)
        # 10 % or 0.5 kWh, whichever is larger. The band is the energy twin of
        # ``check_flows``: per-string members are frequently DC (V×I
        # synthesised) against an AC fleet row, so inverter efficiency alone
        # puts a healthy sum 2–5 % over. The absolute floor keeps the relative
        # band from being meaningless before dawn, when every row is ~0.
        tolerance = max(
            self._PARTITION_ABS_FLOOR_KWH, self._PARTITION_REL_TOL * abs(fleet)
        )
        excess = total - fleet
        if excess <= tolerance:
            return None

        # Name the members, biggest first, and mark the ones that are no
        # longer configured — a stale member IS the suspect, and saying so is
        # the difference between "something is wrong" and "delete this id".
        #
        # (#979) And say where each number CAME FROM where the caller knows.
        # A bucket alone ("heat_pump=1906.00kWh") names the symptom; the
        # source sensor and its raw reading name the fault — a lifetime
        # counter read as a day looks exactly like that, and the violation is
        # often gone by the time anyone looks.
        live = set(live_ids) if live_ids is not None else None
        evidence = member_evidence or {}
        listed = ", ".join(
            f"{mid}={float(kwh or 0.0):.2f}kWh"
            + (f" [{evidence[mid]}]" if mid in evidence else "")
            + (" [no longer configured]" if live is not None and mid not in live else "")
            for mid, kwh in sorted(
                members.items(), key=lambda kv: -float(kv[1] or 0.0)
            )
        )
        return (
            f"{label}: members sum to {total:.2f}kWh against a fleet total of "
            f"{fleet:.2f}kWh — {excess:.2f}kWh over the {tolerance:.2f}kWh "
            f"band. One physical quantity is counted twice (a renamed or "
            f"removed id whose bucket is still published). Members: {listed}"
        )

    def check_ledger_partitions(
        self,
        energy: EnergyTotals,
        energy_flows: EnergyFlows | None = None,
        per_charger_daily: Mapping[str, float] | None = None,
        live_charger_ids: Iterable[str] | None = None,
        per_device_daily: Mapping[str, float] | None = None,
        per_device_evidence: Mapping[str, str] | None = None,
    ) -> list[str]:
        """(#771) The three published breakdowns vs their fleet rows.

        The #628 identity checks the fleet rows only, so a per-device
        misattribution moves no total and is invisible: the per-charger card
        shows a wrong number confidently and nothing anywhere disagrees.

        Note what is absent. Issue #771's table also lists a ``per_battery``
        charge/discharge breakdown; there is no such ledger. The dicts that
        carried that name had no production writer, so a reconciler over them
        would have been unfireable — the #660 failure mode, rebuilt. They are
        deleted instead; ``tests/test_771_ledger_partitions.py`` holds the
        ratchet against re-adding data-shaped surface with nothing behind it.
        """
        violations: list[str] = []

        # 1. Per-charger daily kWh vs the fleet EV day. The sharpest of the
        #    three — the members are integrated in the coordinator from each
        #    charger's own reading, the fleet row in EnergyCalculator from
        #    ``power.ev_power``. Two producers, two inputs, one quantity.
        v = self._reconcile_partition(
            "Per-charger daily EV energy",
            per_charger_daily or {},
            getattr(energy, "daily_ev", 0.0),
            live_charger_ids,
        )
        if v:
            violations.append(v)

        if energy_flows is not None:
            # 2. The per-charger ORIGIN split — what the per-charger cost and
            #    savings figures are built on.
            per_charger = getattr(energy_flows, "per_charger", None) or {}
            if per_charger:
                fleet_ev = (
                    float(getattr(energy_flows, "solar_to_ev", 0.0) or 0.0)
                    + float(getattr(energy_flows, "grid_to_ev", 0.0) or 0.0)
                    + float(getattr(energy_flows, "battery_to_ev", 0.0) or 0.0)
                )
                v = self._reconcile_partition(
                    "Per-charger EV origin split",
                    {
                        cid: (
                            float(getattr(c, "solar_to_ev", 0.0) or 0.0)
                            + float(getattr(c, "grid_to_ev", 0.0) or 0.0)
                            + float(getattr(c, "battery_to_ev", 0.0) or 0.0)
                        )
                        for cid, c in per_charger.items()
                    },
                    fleet_ev,
                    live_charger_ids,
                )
                if v:
                    violations.append(v)

            # 3. Per-PV-string daily kWh vs the solar day. No live-id set is
            #    passed: the strings a cloudy cycle reports are not the strings
            #    that exist, so "not live this cycle" would libel healthy
            #    hardware. The member list alone identifies the duplicate.
            per_string = getattr(energy_flows, "per_string", None) or {}
            if per_string:
                v = self._reconcile_partition(
                    "Per-PV-string daily energy",
                    {
                        sid: float(getattr(s, "energy_kwh", 0.0) or 0.0)
                        for sid, s in per_string.items()
                    },
                    getattr(energy, "daily_solar", 0.0),
                )
                if v:
                    violations.append(v)

        # 4. (#773) Controlled loads vs the home row. The devices are members
        #    of home the way chargers are members of the EV day — most of
        #    home is the un-metered baseload, so SHORTFALL is the healthy
        #    state, and only over-count fires: Σ(devices) > home is the
        #    energy-domain shape of a NEGATIVE baseload — a draw counted
        #    twice or a sign error, never a house. The members are the live
        #    device objects' own day totals (sunrise-keyed, which only makes
        #    the check more conservative against the midnight home row), so
        #    a removed device drops out by construction and no live-id set
        #    is needed.
        v = self._reconcile_partition(
            "Controlled loads vs home residual",
            per_device_daily or {},
            getattr(energy, "daily_home", 0.0),
            # (#979) This is the check whose members have a NAMEABLE source —
            # each device knows its counter/power entity and what it last
            # read. The two charger partitions above are integrated by SEM
            # itself from the fleet reading, so there is no third-party sensor
            # to name and nothing is invented for them.
            member_evidence=per_device_evidence,
        )
        if v:
            violations.append(v)

        return violations

    # (#773) Baseload drift tolerance: a step must clear BOTH bounds to
    # fire. The residual is small (a few kWh) and moves ±40% with ordinary
    # occupancy (a weekend at home is not a dead sensor), while the faults
    # this exists to catch — a metered row dying, a counter reset, a
    # #761-shape double-count — move it by a whole row's worth. A tighter
    # band would fire on healthy houses and be muted, which is the #660
    # death: a check that cried wolf until nobody listened.
    _BASELOAD_ABS_TOL_KWH = 2.0
    _BASELOAD_REL_TOL = 0.5
    _BASELOAD_MIN_REFERENCE_DAYS = 3
    # A day is usable when its ESTIMATED portion is too small to move a
    # verdict — a quarter of the absolute band. Gating on "no estimate
    # anywhere" (the boolean ``measured``) made one meterless pool pump
    # silence the check forever: .175's very first sealed day, and any
    # house with any meterless device. Dormant-by-default is the #660
    # death by other means. The estimate's error is bounded by the
    # estimate itself, so a bounded estimate cannot flip a comparison
    # the 2 kWh band would pass.
    _BASELOAD_EST_TOL_KWH = 0.5

    def check_baseload_drift(
        self, history: list, charger_ids: Iterable[str] = (),
    ) -> list[str]:
        """(#773) Does the leftover behave like a house?

        Compares the newest SEALED, USABLE day against the median of the
        usable days before it. Usable means the day's estimated portion is
        bounded (≤ ``_BASELOAD_EST_TOL_KWH``) — small enough that its worst-
        case error cannot move a verdict. #628 discipline for the rest: a
        day with an unbounded estimate or a missing home row is a GAP — it
        neither feeds the reference nor is itself judged, because comparing
        an estimate-of-unknown-size against measurements fires on healthy
        hardware and gets muted. Rows sealed before ``estimated_kwh``
        existed fall back to the strict boolean: ``measured`` means an
        estimate of exactly zero; unmeasured-with-unknown-size stays a gap
        and ages out of the 14-day window. Fewer than
        ``_BASELOAD_MIN_REFERENCE_DAYS`` usable reference days: silent.

        A breach NAMES its suspect — the term (a device id, or the home row
        itself) whose own day-over-day move best explains the step — because
        "imbalance" alone sends the user hunting through every sensor they
        own. The device day totals sealed alongside each day exist for
        exactly this.

        (#1044) ``charger_ids`` are SEM's own EV chargers. They are not terms
        of the baseload (``home_members``), so they are never named as its
        mover. And on an install that has one, a day sealed before the fix
        (no ``home_members_only`` stamp) subtracted the car from ``home`` a
        second time — a gap, not a reference: it ages out of the window.
        """
        if not history:
            return []
        chargers = {str(c) for c in (charger_ids or ())}

        def _usable(r) -> bool:
            if not isinstance(r, dict) or r.get("baseload_kwh") is None:
                return False
            if chargers and not r.get("home_members_only"):
                return False
            est = r.get("estimated_kwh")
            if est is None:
                return bool(r.get("measured"))
            try:
                return float(est) <= self._BASELOAD_EST_TOL_KWH
            except (TypeError, ValueError):
                return False

        measured = [r for r in history if _usable(r)]
        if len(measured) < self._BASELOAD_MIN_REFERENCE_DAYS + 1:
            return []
        latest = measured[-1]
        if history[-1] is not latest:
            return []  # the newest sealed day is a gap — nothing to judge
        reference = measured[:-1][-self._BASELOAD_MIN_REFERENCE_DAYS * 2:]
        ref_values = sorted(float(r["baseload_kwh"]) for r in reference)
        median = ref_values[len(ref_values) // 2]
        value = float(latest["baseload_kwh"])
        step = value - median
        tolerance = max(
            self._BASELOAD_ABS_TOL_KWH, self._BASELOAD_REL_TOL * abs(median)
        )
        if abs(step) <= tolerance:
            return []

        # Name the mover: for each term, its latest value minus its median
        # over the reference days. ``home`` is a term like any device — a
        # step that arrives through the home row means a METERED row (or
        # the balance) moved, not a device.
        def _term_median(key_fn) -> float:
            vals = sorted(key_fn(r) for r in reference)
            return vals[len(vals) // 2]

        movers: dict[str, float] = {
            "home": float(latest.get("home_kwh", 0.0) or 0.0)
            - _term_median(lambda r: float(r.get("home_kwh", 0.0) or 0.0)),
        }
        device_ids = set(latest.get("devices") or {})
        for r in reference:
            device_ids |= set(r.get("devices") or {})
        for did in device_ids - chargers:
            movers[did] = float(
                (latest.get("devices") or {}).get(did, 0.0) or 0.0
            ) - _term_median(
                lambda r, d=did: float(
                    (r.get("devices") or {}).get(d, 0.0) or 0.0)
            )
        suspect, moved = max(movers.items(), key=lambda kv: abs(kv[1]))
        return [
            f"True baseload stepped {step:+.2f}kWh against a "
            f"{median:.2f}kWh median ({tolerance:.2f}kWh band). The house "
            f"SEM does not control varies slowly — a step means a sensor "
            f"died, a counter reset, or a device is double-counted. "
            f"Largest mover: {suspect} ({moved:+.2f}kWh day-over-day)."
        ]

    def check_clamps(self, clamp_engagement: dict[str, float]) -> list[str]:
        """(#660) Report clamps that have been engaged for too long.

        ``EnergyCalculator`` records how much each ``max(0, …)`` /
        ``min(100, …)`` guard removed this cycle. A guard that engages once
        is doing its job against a transient; a guard that engages every
        cycle for ``_CLAMP_CYCLES`` is holding a wrong formula inside the
        valid range, which is precisely the failure the old range checks
        could not see.

        Streaks are per clamp name and reset the moment that clamp goes
        quiet, so a cleared bug clears the violation.
        """
        violations: list[str] = []
        engaged = clamp_engagement or {}

        for name in list(self._clamp_streaks):
            if name not in engaged:
                del self._clamp_streaks[name]

        for name, amount in engaged.items():
            streak = self._clamp_streaks.get(name, 0) + 1
            self._clamp_streaks[name] = streak
            if streak >= self._CLAMP_CYCLES:
                violations.append(
                    f"{name} has been clamped for {streak} consecutive "
                    f"cycles (last correction {amount}) — the value stays in "
                    f"range only because the clamp is holding it there; the "
                    f"formula behind it is wrong"
                )
        return violations

    def check_costs(self, costs: CostData) -> list[str]:
        """Verify cost values that can actually be negative.

        (#660) ``daily_savings`` and ``daily_battery_savings`` were also
        checked here, but both are ``max(0, …)`` at their only assignment
        site — the check could not fire. They are not instrumented as clamp
        engagement either; see ``EnergyCalculator.calculate_costs`` for why
        (a negative raw saving is legitimate under a negative import price).
        ``daily_costs`` is a raw accumulator with no floor, so it is the one
        that stays.
        """
        violations: list[str] = []
        val = getattr(costs, "daily_costs", 0)
        if val < -0.01:
            violations.append(f"Cost daily_costs is negative: {val:.4f}")
        return violations

    def run_all_checks(
        self,
        power: PowerReadings,
        flows: PowerFlows | None = None,
        costs: CostData | None = None,
        clamp_engagement: dict[str, float] | None = None,
        home_hold_active: bool = False,
        energy: EnergyTotals | None = None,
        energy_flows: EnergyFlows | None = None,
        per_charger_daily: Mapping[str, float] | None = None,
        live_charger_ids: Iterable[str] | None = None,
        per_device_daily: Mapping[str, float] | None = None,
        per_device_evidence: Mapping[str, str] | None = None,
        baseload_history: list | None = None,
        charger_ids: Iterable[str] | None = None,
    ) -> list[str]:
        """Run all health checks and return violations list.

        (#660) The ``autarky`` / ``self_consumption`` parameters are gone.
        They fed a range check on values their producer had already clamped
        into that range; ``clamp_engagement`` carries the same two metrics
        with the information still attached.

        (#771) ``flows`` is the instantaneous :class:`PowerFlows`;
        ``energy_flows`` is the integrated :class:`EnergyFlows`. The partition
        check needs the latter — the two are one letter apart and mean
        different things, which is why they are separate parameters rather
        than one polymorphic one.
        """
        violations = self.check_power_balance(power, home_hold_active)
        if flows is not None:
            violations += self.check_flows(power, flows)
        violations += self.check_clamps(clamp_engagement or {})
        if costs is not None:
            violations += self.check_costs(costs)
        if energy is not None:
            violations += self.check_ledger_partitions(
                energy,
                energy_flows=energy_flows,
                per_charger_daily=per_charger_daily,
                live_charger_ids=live_charger_ids,
                per_device_daily=per_device_daily,
                per_device_evidence=per_device_evidence,
            )
        if baseload_history:
            violations += self.check_baseload_drift(
                baseload_history, charger_ids or ())

        if violations:
            self._violation_count += len(violations)
            self._last_violations = violations
            self._violation_streak += 1
            if self._violation_streak <= self._WARN_CYCLES:
                for v in violations:
                    _LOGGER.warning("Health check violation: %s", v)
                if self._violation_streak == self._WARN_CYCLES:
                    _LOGGER.warning(
                        "Health check violations persist — further "
                        "occurrences drop to debug until they clear "
                        "(diag: sem health sensors keep counting)",
                    )
            else:
                for v in violations:
                    _LOGGER.debug("Health check violation: %s", v)
        else:
            if self._violation_streak > self._WARN_CYCLES:
                _LOGGER.info("Health check violations cleared")
            self._violation_streak = 0
            self._last_violations = []

        return violations

    @property
    def total_violations(self) -> int:
        """Cumulative count of all violations seen since startup."""
        return self._violation_count

    @property
    def last_violations(self) -> list[str]:
        """Violations detected in the most recent cycle (empty if all OK)."""
        return self._last_violations
