"""#708 — delivered energy was applied with the sign of *consumed* energy.

Reporter (@Azlinon, 85 kWh Blazer EV, JuiceBox): started a session at 36 %,
let it reach 38 %, then stopped the OnStar integration so the SOC sensor
froze. The car kept charging — the EVSE metered 11.5 kWh — and "SOC (EST.)"
walked *down* from 32 % to 25 %. His arithmetic: 11.5 / 85 × 0.92 ≈ 12.4 %,
"almost exactly the amount of *decrease* I'm seeing".

``_energy_since_full`` is a **deficit** — kWh the pack is below full. Seven
sites agree on that reading: the day-rollover decay adds driving consumption,
the sensor calibration sets ``(100 − soc)/100 × capacity``, the stall/taper
anchor zeroes it at 100 %, ``on_session_end`` *subtracts* what a session
delivered, and every display divides it out of 100.

``update_energy`` — the one path that runs every cycle *while charging* —
added the delivered kWh instead. So each cycle of a real charge pushed the
estimate down by exactly what went into the pack. It never surfaced before
because the taper detector normally reaches full and resets the deficit to
zero; it takes a session that charges *without* topping out AND a sensor
that stops updating to leave the inverted value on screen. That is the test
the reporter ran.
"""
import ast
import pathlib

import pytest

from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    CHARGE_EFFICIENCY,
    EVTaperDetector,
)


CAPACITY = 85.0          # reporter's pack
ANCHOR_SOC = 38.0        # last reading before OnStar was stopped
DELIVERED = 11.5         # kWh the EVSE metered while the sensor was frozen


def _detector(capacity=CAPACITY):
    return EVTaperDetector({"ev_battery_capacity_kwh": capacity})


def _anchored():
    """A detector calibrated by a real reading, then blinded (sensor gone)."""
    det = _detector()
    det.get_virtual_soc(ANCHOR_SOC)
    return det


def _expected(delivered_kwh, start=ANCHOR_SOC):
    """The energy-accounted route to the same number.

    ``anchor + delivered × eff / capacity`` is algebraically identical to the
    deficit route (``100 − (deficit − delivered × eff) / capacity``) once the
    deficit was set from that anchor — which is the point: the big "SOC
    (EST.)" figure and the small "est. now ~54 %" hint stop being two
    answers. The ±0.5 tolerance the callers use is float accumulation over a
    few hundred incremental steps, nothing physical.
    """
    return start + delivered_kwh * CHARGE_EFFICIENCY / CAPACITY * 100.0


# ──────────────────────────────────────────────
# The reported bug
# ──────────────────────────────────────────────
class TestChargingRaisesTheEstimate:
    def test_reporter_scenario_power_integration(self):
        """11.5 kWh into a blinded 38 % pack lands near 50 %, not near 25 %."""
        det = _anchored()
        assert det.get_virtual_soc(None) == pytest.approx(ANCHOR_SOC, abs=0.1)

        # ~10 s cycles at 11.5 kW, the way the coordinator feeds it
        step = DELIVERED / 360.0
        for _ in range(360):
            det.update_energy(step)

        # Reporter's own hand-calculation: "I should now be up to about 50%"
        assert det.get_virtual_soc(None) == pytest.approx(_expected(DELIVERED), abs=0.5)

    def test_estimate_never_walks_down_while_charging(self):
        det = _anchored()
        previous = det.get_virtual_soc(None)
        for _ in range(60):
            det.update_energy(0.05)
            current = det.get_virtual_soc(None)
            assert current >= previous - 1e-9, (
                f"estimate fell from {previous:.2f}% to {current:.2f}% "
                "while the charger was delivering energy"
            )
            previous = current
        assert previous > ANCHOR_SOC

    def test_the_counter_is_tracked_but_does_not_book_the_deficit(self):
        """A lifetime counter measures energy put IN, never distance driven.

        Reading it as the deficit is exactly what produced the sign error,
        and its per-cycle delta is no safer a substitute: a counter that goes
        unavailable for a stretch and then returns re-books the whole gap the
        power integral already covered, and a charger publishing Wh has its
        ~4 Wh cycles booked as 4 kWh — small enough to pass a "≤ capacity"
        sanity bound and pin the estimate at 100 %. The counter keeps its
        real job here, the taper anchor (``_hw_total_at_full``); the deficit
        is booked from the integral alone.

        Fed here in that second shape: nothing at the read site normalizes
        the unit (``float(hw_state.state)``, raw), so a Wh counter's cycles
        arrive as the bare number 4.0.
        """
        det = _anchored()
        for i in range(1, 24):
            det.update_energy(0.5, hw_total_energy_kwh=1_000_000.0 + i * 4.0)
        assert det.get_virtual_soc(None) == pytest.approx(_expected(11.5), abs=0.5)
        assert det._hw_total_last == pytest.approx(1_000_092.0)

    def test_disconnect_does_not_book_the_session_a_second_time(self):
        """``on_session_end`` used to be the other half of the cancelling pair.

        Pre-fix the two errors hid each other: the live path ADDED the session
        to the deficit, then at disconnect ``on_session_end`` SUBTRACTED it —
        so the end state landed back near the truth and only the *live* number
        was inverted. That is why this shipped. With the live path corrected,
        the session-end subtraction is a straight double-count.

        The primary charger's detector is the fleet detector
        (``coordinator._ev_taper_detector`` resolves to
        ``_ev_taper_detectors[primary_id]``), so both calls land on the same
        object on every real install.
        """
        det = _anchored()
        det._session_peak_w = 7000.0     # on_session_end ignores sub-500 W sessions
        step = DELIVERED / 100.0
        for _ in range(100):
            det.update_energy(step)
        during = det.get_virtual_soc(None)

        det.on_session_end(DELIVERED)

        assert det.get_virtual_soc(None) == pytest.approx(during, abs=0.1), (
            "disconnect re-applied the whole session on top of what the live "
            "path already booked"
        )

    def test_a_full_pack_clamps_at_100(self):
        det = _anchored()
        det.update_energy(200.0)          # far more than the pack can hold
        assert det.get_virtual_soc(None) == pytest.approx(100.0, abs=0.01)
        assert det.energy_since_full >= 0.0


# ──────────────────────────────────────────────
# Signs that must NOT flip (pins, green before and after)
# ──────────────────────────────────────────────
class TestSignsThatMustNotFlip:
    def test_driving_still_lowers_the_estimate(self):
        det = _anchored()
        det.apply_daily_decay(8.5, 10.0)
        assert det.get_virtual_soc(None) == pytest.approx(
            ANCHOR_SOC - 8.5 / CAPACITY * 100.0, abs=0.1
        )

    def test_a_counter_that_reboots_is_ignored(self):
        """A charger that resets its lifetime total must not move the estimate."""
        det = _anchored()
        det.update_energy(0.0, hw_total_energy_kwh=1000.0)
        before = det.get_virtual_soc(None)
        det.update_energy(0.0, hw_total_energy_kwh=0.0)      # rebooted to zero
        det.update_energy(0.0, hw_total_energy_kwh=0.2)
        assert det.get_virtual_soc(None) == pytest.approx(before, abs=0.01)

    def test_unanchored_detector_stays_unanchored(self):
        """#245: no reference yet → nothing to estimate from.

        ``_estimated_soc`` is the persisted field, so it is the one that
        matters: writing 100.0 into it here would survive the restart and
        outlive the ``_soc_anchored`` display gate that is currently hiding
        it. Leave both the deficit and the estimate untouched — an install
        with no vehicle-SOC sensor is anchored by its first COMPLETED
        session (``on_session_end``'s bootstrap), not mid-charge.
        """
        det = _detector()
        det.update_energy(5.0)
        assert det.energy_since_full == 0.0
        assert det._estimated_soc == 0.0
        assert det._soc_anchored is False

    def test_first_session_still_bootstraps_without_a_soc_sensor(self):
        """The bootstrap is now the ONLY way a sensorless install anchors.

        ``update_energy`` is deliberately inert while unanchored, so removing
        the session-end subtraction must not take the bootstrap with it.
        """
        det = EVTaperDetector(
            {"ev_battery_capacity_kwh": 40, "ev_target_soc": 80}
        )
        det._session_peak_w = 7000.0
        for _ in range(100):
            det.update_energy(0.095)         # 9.5 kWh over the session
        # ...every one of which was a no-op, by design — that is exactly why
        # the bootstrap below cannot go with the double-count it was tangled
        # up in.
        assert det._energy_since_full == 0.0
        assert det._soc_anchored is False

        det.on_session_end(9.5)

        assert det._soc_anchored is True
        assert det._estimated_soc == pytest.approx(80.0, abs=2.0)

    def test_full_detected_short_circuits(self):
        det = _anchored()
        det._full_detected = True
        det._energy_since_full = 0.0
        det.update_energy(5.0)
        assert det.energy_since_full == 0.0

    def test_a_taper_anchored_counter_no_longer_reconciles_the_deficit(self):
        """The branch the reporter most likely actually hit.

        Once a taper sets ``_hw_total_at_full``, that anchor OUTLIVES the
        session (``reset_session`` clears ``_full_detected`` but not the hw
        anchor), so the next session took the "reconcile from the counter"
        branch: ``deficit = hw_total − hw_total_at_full``, i.e. *energy put
        back in since the pack was last full* assigned to *how far below full
        it is*. Those are opposites. A car that has been driven since full
        reads deficit ≈ 0 (SOC 100 %) and then walks DOWN as it charges —
        precisely the reported symptom, and immune to any per-cycle fix.
        """
        det = _detector()
        det._hw_total_at_full = 1000.0      # taper anchored here last session
        det.get_virtual_soc(ANCHOR_SOC)     # real reading: pack is at 38 %
        det.update_energy(0.5, hw_total_energy_kwh=1005.0)

        assert det.get_virtual_soc(None) == pytest.approx(_expected(0.5), abs=0.1), (
            "the lifetime counter was reconciled back into the deficit — "
            "delivered-since-full is not distance-below-full"
        )


# ──────────────────────────────────────────────
# The coordinator's out-of-band writes
# ──────────────────────────────────────────────
class TestCoordinatorReachIns:
    """Two coordinator sites set the detector's estimate from outside: the
    stall→full anchor and the SOC self-heal. Both bypass every method on the
    class, so the fields they must keep consistent are only enforced here.
    """

    def _self_heal_block(self):
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "coordinator" / "coordinator.py").read_text()
        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, ast.If)
                    and "SOC self-healed" in ast.dump(node)):
                return node
        raise AssertionError("SOC self-heal block not found in coordinator.py")

    def test_the_self_heal_anchors_what_it_writes(self):
        """#708 — ``update_energy`` is inert until ``_soc_anchored``.

        The self-heal writes a plausible deficit and estimate when SOC has
        bottomed out at 0 % while the car is demonstrably taking charge. If
        it does not also anchor, every later cycle of that session skips the
        booking and the healed number FREEZES for the rest of the charge —
        which is worse than the wrong-but-moving value it replaced. Its
        sibling twenty lines below (the stall→full anchor) already sets all
        four fields; this is the one that forgot.
        """
        written = {
            t.attr
            for node in ast.walk(self._self_heal_block())
            if isinstance(node, ast.Assign)
            for t in node.targets
            if isinstance(t, ast.Attribute)
        }
        assert "_soc_anchored" in written, (
            "self-heal sets the estimate but never anchors it — update_energy "
            f"will skip every subsequent cycle. Writes: {sorted(written)}"
        )
