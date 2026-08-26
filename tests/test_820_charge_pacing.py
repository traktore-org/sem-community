"""#820 — pace the battery's daytime fill so it lands full at day's end.

@ArneGollin1987 (discussion #817): a 21 kWh pack is full by ~11:30 and then
sits at 100 % for hours — bad for longevity, and it caps midday harvest when
PV + battery charging together exceed the inverter's AC limit. His export
price is FIXED, so the pacing stands on forecast + headroom alone; price
never enters.

The reporter's own staging, as guards with named reasons:
  * below the safety buffer (~35 %) charge ASAP — no cap;
  * an untrusted forecast paces nothing — a pace computed from a forecast
    that disappoints strands the pack half-full at sunset, which is WORSE
    than greedy (greedy's failure is cosmetic, pacing's is material);
  * where clipping is predicted, RAISE the cap — captured sun beats pacing;
  * otherwise: the smallest constant cap that still lands the pack at its
    target by sunset − margin, found by inverting the already-published
    provisional_soc_curve — the same model the user sees.

Everything is default-off (battery_charge_pacing_enabled) and observer-gated;
the write target is a user-named number entity (the inverter's standing
max-charge-power register), captured on engage and RESTORED on disengage —
never a stale cap left behind.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.charge_pacing import (
    PacingDecision,
    paced_charge_cap_w,
)


def _ledger(hours, solar_w, home_w=800.0, soc_kwh=6.0):
    """A synthetic sunny-day ledger in the day_ledger slot shape."""
    t0 = datetime(2026, 8, 25, 8, 0)
    out = []
    for i in range(hours):
        w = solar_w[i] if isinstance(solar_w, (list, tuple)) else solar_w
        out.append(SimpleNamespace(
            start=t0 + timedelta(hours=i), end=t0 + timedelta(hours=i + 1),
            hours=1.0, soc_kwh=soc_kwh, home_batt_kwh=0.0,
            solar_w=float(w),
            cap_override_w=max(0.0, w - home_w), grid_committed_w=0.0,
        ))
    return out


BASE = dict(
    capacity_kwh=21.0, soc_pct=40.0, target_soc_pct=100.0,
    floor_soc_pct=35.0, forecast_trusted=True,
    inverter_ac_limit_w=20000.0, hw_max_charge_w=10000.0,
)


class TestThePace:
    def test_reporters_day_lands_full_at_sunset_not_1130(self):
        """8 sunny hours, 6 kW surplus each: greedy fills 21 kWh in ~3.5 h
        (full by 11:30). The paced cap lands 100 % in the LAST slot."""
        led = _ledger(8, 6800.0)
        d = paced_charge_cap_w(ledger=led, **BASE)
        assert d.cap_w is not None
        assert 1500.0 <= d.cap_w <= 3000.0, d
        # walk the fill with the cap: full only near the end
        filled, full_at = 0.0, None
        for i, s in enumerate(led):
            filled += min(s.cap_override_w, d.cap_w) / 1000.0
            if filled >= 21.0 * (1.0 - 0.40) - 1e-9 and full_at is None:
                full_at = i
        assert full_at is not None and full_at >= len(led) - 2, (
            f"paced pack still full early (slot {full_at})"
        )

    def test_below_the_buffer_charges_asap(self):
        d = paced_charge_cap_w(ledger=_ledger(8, 6800.0),
                               **{**BASE, "soc_pct": 20.0})
        assert d.cap_w is None and "buffer" in d.reason

    def test_untrusted_forecast_paces_nothing(self):
        d = paced_charge_cap_w(ledger=_ledger(8, 6800.0),
                               **{**BASE, "forecast_trusted": False})
        assert d.cap_w is None and "trust" in d.reason

    def test_no_ledger_paces_nothing(self):
        d = paced_charge_cap_w(ledger=[], **BASE)
        assert d.cap_w is None

    def test_clipping_hours_raise_the_cap(self):
        """Midday surplus above the inverter's AC limit would clip; the cap
        must open to swallow it — captured sun beats pacing."""
        solar = [4000, 6000, 21500, 22000, 21500, 6000, 4000, 3000]
        d_clip = paced_charge_cap_w(
            ledger=_ledger(8, solar), **{**BASE, "inverter_ac_limit_w": 20000.0})
        d_flat = paced_charge_cap_w(ledger=_ledger(8, 6800.0), **BASE)
        assert d_clip.cap_w is not None and d_flat.cap_w is not None
        assert d_clip.cap_w > d_flat.cap_w, (
            f"clipping did not open the cap ({d_clip.cap_w} vs {d_flat.cap_w})"
        )
        assert "clip" in d_clip.reason

    def test_a_day_too_weak_to_fill_paces_nothing(self):
        """If even greedy cannot reach the target, a cap only makes it worse."""
        d = paced_charge_cap_w(ledger=_ledger(8, 2000.0), **BASE)
        assert d.cap_w is None and "cannot" in d.reason

    def test_cap_never_exceeds_hardware(self):
        d = paced_charge_cap_w(ledger=_ledger(8, 21000.0),
                               **{**BASE, "hw_max_charge_w": 5000.0,
                                  "inverter_ac_limit_w": 50000.0})
        if d.cap_w is not None:
            assert d.cap_w <= 5000.0


class TestTheDecisionShape:
    def test_every_outcome_names_its_reason(self):
        for kwargs in (
            {},
            {"soc_pct": 20.0},
            {"forecast_trusted": False},
        ):
            d = paced_charge_cap_w(ledger=_ledger(8, 6800.0), **{**BASE, **kwargs})
            assert isinstance(d, PacingDecision) and d.reason


class TestTheWriter:
    def _hass(self, current="5000"):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock
        st = SimpleNamespace(state=current)
        return SimpleNamespace(
            states=SimpleNamespace(get=MagicMock(return_value=st)),
            services=SimpleNamespace(async_call=AsyncMock()),
        )

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_engage_captures_then_disengage_restores(self):
        from custom_components.solar_energy_management.coordinator.charge_pacing import (
            ChargePacingWriter,
        )
        w = ChargePacingWriter()
        h = self._hass(current="5000")
        assert self._run(w.apply(h, "number.max_charge", 2000.0, observer=False)) == "wrote"
        assert w.restore_value == 5000.0
        out = self._run(w.apply(h, "number.max_charge", None, observer=False))
        assert out == "restored"
        call = h.services.async_call.await_args
        assert call.args[2]["value"] == 5000.0, "the captured value must return"
        assert not w.engaged

    def test_dedupe_holds_small_changes(self):
        from custom_components.solar_energy_management.coordinator.charge_pacing import (
            ChargePacingWriter,
        )
        w = ChargePacingWriter(); h = self._hass()
        self._run(w.apply(h, "number.x", 2000.0, observer=False))
        assert self._run(w.apply(h, "number.x", 2050.0, observer=False)) == "held"
        assert self._run(w.apply(h, "number.x", 2200.0, observer=False)) == "wrote"

    def test_observer_never_writes(self):
        from custom_components.solar_energy_management.coordinator.charge_pacing import (
            ChargePacingWriter,
        )
        w = ChargePacingWriter(); h = self._hass()
        assert self._run(w.apply(h, "number.x", 2000.0, observer=True)) == "observer"
        h.services.async_call.assert_not_awaited()


class TestTodayRemainingSlots:
    """PROD campaign catch (26.08 morning): pacing was hooked to the
    tomorrow PREVIEW ledger, which exists only at night — so it solved a
    correct cap on tomorrow's books at 23:00 and had no input at all in the
    hours it is meant to act. Both rigs read `unavailable` at 06:50.

    The daytime source: today's remaining slots [now, sunset), tiled by the
    same day builder the planner uses, fed the FULL-day forecast so the
    solar curve yields the remaining fraction naturally (passing the
    remaining kWh as the day total would under-count — the builder would
    hand the window only the curve's fraction of it)."""

    def _sun(self):
        return (datetime(2026, 8, 26, 6, 32), datetime(2026, 8, 26, 20, 30))

    def _builder(self, **kw):
        from custom_components.solar_energy_management.coordinator.day_ledger import (
            build_day_slots,
        )
        return build_day_slots(price_at=lambda t: None,
                               level_cheap_at=lambda t: False, **kw)

    def test_night_yields_no_slots(self):
        from custom_components.solar_energy_management.coordinator.charge_pacing import (
            today_remaining_slots,
        )
        sr, ss = self._sun()
        for now in (datetime(2026, 8, 26, 3, 0), datetime(2026, 8, 26, 21, 0)):
            assert today_remaining_slots(
                now=now, sunrise=sr, sunset=ss, day_kwh=40.0,
                home_w_at=lambda t: 500.0, builder=self._builder) == []

    def test_morning_yields_the_rest_of_the_day(self):
        from custom_components.solar_energy_management.coordinator.charge_pacing import (
            today_remaining_slots,
        )
        sr, ss = self._sun()
        now = datetime(2026, 8, 26, 9, 0)
        slots = today_remaining_slots(
            now=now, sunrise=sr, sunset=ss, day_kwh=40.0,
            home_w_at=lambda t: 500.0, builder=self._builder)
        assert slots, "a sunny morning produced no remaining-day slots"
        assert slots[0].start >= now and slots[-1].end <= ss + timedelta(hours=1)
        solar_kwh = sum(s.solar_w * s.hours for s in slots) / 1000.0
        # the morning's 2.5 h are gone, so LESS than the full day — but the
        # bulk of it (midday) is still ahead
        assert 25.0 < solar_kwh < 40.0, solar_kwh

    def test_unknown_forecast_yields_no_slots(self):
        from custom_components.solar_energy_management.coordinator.charge_pacing import (
            today_remaining_slots,
        )
        sr, ss = self._sun()
        assert today_remaining_slots(
            now=datetime(2026, 8, 26, 9, 0), sunrise=sr, sunset=ss,
            day_kwh=None, home_w_at=lambda t: 500.0, builder=self._builder) == []


class TestTheSensorNeverGoesUnavailable:
    """26.08: as a W-valued sensor it went `unavailable` whenever the cap was
    None — most of the time, by design — and HA hides the attributes of an
    unavailable entity, so the REASON vanished exactly when it mattered.
    The state is the action token now; the cap rides the attributes."""

    def test_state_is_the_action_token_and_never_none(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        src = inspect.getsource(cm)
        assert 'result["battery_charge_pacing"] = _cp.get("action") or "idle"' in src
        assert 'result["battery_charge_pacing"] = _cp.get("cap_w")' not in src, (
            "a None cap blanks the sensor and hides the reason (#820)"
        )

    def test_description_carries_no_unit(self):
        import custom_components.solar_energy_management.sensor as sen
        d = next(x for x in sen.SENSOR_TYPES if x.key == "battery_charge_pacing") \
            if hasattr(sen, "SENSOR_TYPES") else None
        if d is not None:
            assert d.native_unit_of_measurement is None
