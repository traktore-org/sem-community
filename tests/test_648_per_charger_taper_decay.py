"""#648 — day-rollover virtual-SOC decay reaches EVERY charger's detector.

While a car is away SEM can't watch it being driven, so each day rollover
advances the taper detector's ``energy_since_full`` by the predicted daily
consumption. That decay ran through the ``_ev_taper_detector`` property (the
PRIMARY detector only), gated on the FLEET ``power.ev_connected`` — ledger
class 3, fleet-read-for-one, the analytics-side sibling of the #639 double-feed.

Two failures on a multi-charger install:

1. **Secondary detectors never decayed.** Car 2 charges full on Sunday, drives
   all week, and its detector still reads ~100 %. Load-bearing:
   ``_resolve_charger_soc`` falls back to the per-charger virtual SOC when the
   real SOC entity is offline → ``build_night_target_map`` sees remaining ≈ 0
   → a needed night charge is silently skipped.
2. **One plugged car froze every other car's decay.** The fleet gate is true
   while ANY charger is connected.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import SEMCoordinator


def _det(last_full=1000.0):
    d = MagicMock()
    d.last_full_timestamp = last_full
    return d


def _coord(detectors, connected, predicted=12.0):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.config = {"daily_ev_target": 10, "ev_battery_capacity_kwh": 40}
    c._ev_taper_detectors = detectors
    c._last_ev_connected_per_charger = connected
    c._predictor = MagicMock()
    c._predictor.predict_ev_consumption_tomorrow = MagicMock(return_value=predicted)
    c._read_outdoor_temperature = MagicMock(return_value=15.0)
    c.hass = MagicMock()
    return c


def _power(fleet_connected):
    p = MagicMock()
    p.ev_connected = fleet_connected
    return p


@pytest.mark.unit
class TestEveryChargerDecays648:
    def test_the_bug_charger_two_decays_while_charger_one_is_plugged_in(self):
        """The stated closure. Car 1 is plugged in (so the FLEET flag is True,
        which pre-fix suppressed everything); car 2 is away and must decay."""
        d1, d2 = _det(), _det()
        c = _coord({"keba": d1, "wallbox": d2}, {"keba": True, "wallbox": False})

        c._apply_daily_taper_decay(MagicMock(), _power(fleet_connected=True))

        d2.apply_daily_decay.assert_called_once()
        d1.apply_daily_decay.assert_not_called()      # car 1 is here, SEM sees it

    def test_a_plugged_secondary_no_longer_freezes_the_primary(self):
        """The mirror image: car 2 sits plugged in overnight, car 1 is away."""
        d1, d2 = _det(), _det()
        c = _coord({"keba": d1, "wallbox": d2}, {"keba": False, "wallbox": True})

        # fleet_connected is deliberately True and deliberately irrelevant: with
        # per-charger detectors present the fleet flag is never consulted. It is
        # set here only to mirror what the old code would have seen (and been
        # frozen by).
        c._apply_daily_taper_decay(MagicMock(), _power(fleet_connected=True))

        d1.apply_daily_decay.assert_called_once()
        d2.apply_daily_decay.assert_not_called()

    def test_both_away_both_decay(self):
        d1, d2 = _det(), _det()
        c = _coord({"keba": d1, "wallbox": d2}, {"keba": False, "wallbox": False})
        c._apply_daily_taper_decay(MagicMock(), _power(fleet_connected=False))
        d1.apply_daily_decay.assert_called_once()
        d2.apply_daily_decay.assert_called_once()

    def test_every_detector_gets_the_same_inputs(self):
        """Prediction / fallback / temperature are household-level, so each
        detector must receive identical arguments — and they are computed once."""
        d1, d2, d3 = _det(), _det(), _det()
        # One charger IS plugged in — the shared inputs must still be computed
        # exactly once, not once per decaying detector.
        c = _coord(
            {"keba": d1, "wallbox": d2, "easee": d3},
            {"easee": True},
            predicted=12.0,
        )
        c._apply_daily_taper_decay(MagicMock(), _power(False))
        d3.apply_daily_decay.assert_not_called()
        assert d1.apply_daily_decay.call_args == d2.apply_daily_decay.call_args
        assert d1.apply_daily_decay.call_args[0][0] == 12.0     # predicted
        assert d1.apply_daily_decay.call_args[0][1] == 10       # daily_ev_target
        assert c._predictor.predict_ev_consumption_tomorrow.call_count == 1

    def test_a_detector_that_never_saw_full_does_not_decay(self):
        """No ``last_full_timestamp`` = no anchor, so there is nothing to decay
        FROM. Preserved from #106."""
        never, once = _det(last_full=None), _det()
        c = _coord({"keba": never, "wallbox": once}, {})
        c._apply_daily_taper_decay(MagicMock(), _power(False))
        never.apply_daily_decay.assert_not_called()
        once.apply_daily_decay.assert_called_once()

    def test_nothing_to_decay_skips_the_prediction_work(self):
        """The predictor + weather read cost real work — don't do it for a
        rollover where every car is home."""
        d1 = _det()
        c = _coord({"keba": d1}, {"keba": True})
        c._apply_daily_taper_decay(MagicMock(), _power(True))
        d1.apply_daily_decay.assert_not_called()
        c._predictor.predict_ev_consumption_tomorrow.assert_not_called()
        c._read_outdoor_temperature.assert_not_called()

    def test_a_charger_missing_from_the_connected_map_is_treated_as_away(self):
        """A detector built before the session loop first ran has no entry yet.
        Defaulting to "connected" would silently skip its decay forever."""
        d1 = _det()
        c = _coord({"keba": d1}, {})          # no entry for keba
        c._apply_daily_taper_decay(MagicMock(), _power(False))
        d1.apply_daily_decay.assert_called_once()


@pytest.mark.unit
class TestSingleDetectorInstallUnchanged648:
    """The legacy path — no per-charger detectors built yet (first-refresh
    restore window, or a bare single-charger install). There is no per-charger
    connection state to consult, so the fleet flag IS this charger's flag."""

    def test_unplugged_single_charger_still_decays(self):
        default = _det()
        c = _coord({}, {})
        c._ev_devices = {}
        c._ev_taper_detector_default = default
        c._apply_daily_taper_decay(MagicMock(), _power(fleet_connected=False))
        default.apply_daily_decay.assert_called_once()

    def test_plugged_single_charger_does_not_decay(self):
        default = _det()
        c = _coord({}, {})
        c._ev_devices = {}
        c._ev_taper_detector_default = default
        c._apply_daily_taper_decay(MagicMock(), _power(fleet_connected=True))
        default.apply_daily_decay.assert_not_called()

    def test_no_detector_at_all_is_a_no_op(self):
        c = _coord({}, {})
        c._ev_devices = {}
        c._ev_taper_detector_default = None
        c._apply_daily_taper_decay(MagicMock(), _power(False))      # must not raise


@pytest.mark.unit
class TestDecayIsWiredIntoTheRollover648:
    def test_the_rollover_calls_the_per_charger_helper(self):
        """Pins the call chain: the day-rollover must reach the per-charger
        helper, not go back to the primary-only property. Since #645 the
        rollover calls ``_run_due_daily_decay``, which is the only caller of
        ``_apply_daily_taper_decay`` — pin both links."""
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as mod

        update_src = inspect.getsource(mod.SEMCoordinator._async_update_data)
        assert "self._run_due_daily_decay(now_time, today_date, power)" in update_src
        due_src = inspect.getsource(mod.SEMCoordinator._run_due_daily_decay)
        assert "self._apply_daily_taper_decay(now_time, power)" in due_src
        for src in (update_src, due_src):
            assert "self._ev_taper_detector.apply_daily_decay" not in src, (
                "the primary-only decay call is back (#648)"
            )
