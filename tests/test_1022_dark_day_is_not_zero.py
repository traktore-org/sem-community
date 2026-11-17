"""#1022 — a day without a solar reading is not a 0 kWh day.

One rule (``ForecastLedger.settle_day``) feeds the active ledger, every
source ledger and the forecast tracker's day record.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.analytics.pv_health import pv_health
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.forecast_ledger import (
    DARK_DAY_MAX_MIN, ForecastLedger,
)
from custom_components.solar_energy_management.coordinator.forecast_tracker import (
    ForecastTracker,
)

DAY = "2026-11-17"


def _coord(storage=None):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c._storage = storage
    c._forecast_ledger = None
    c._source_ledgers = None
    c._forecast_reader = SimpleNamespace(
        peek_sources=lambda: {"a": {"today_kwh": 12.0, "tomorrow_kwh": 10.0}})
    return c


def _run(c, dark_min, actual):
    now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    fd = SimpleNamespace(forecast_today_kwh=12.0, forecast_tomorrow_kwh=10.0,
                         forecast_d2_kwh=9.0)
    with patch("homeassistant.util.dt.now", return_value=now):
        try:
            c._record_forecast_horizons(
                fd, SimpleNamespace(daily_solar=actual), now,
                SimpleNamespace(solar_downtime_min_today=dark_min))
        except Exception:  # noqa: BLE001 — the publish tail needs a full coordinator
            pass


class TestLedgerRule:
    def test_whole_dark_day_records_no_actual(self):
        led = ForecastLedger()
        led.record(DAY, 0, 12.0)
        led.settle_day(DAY, 0.0, 600.0)
        assert led.actual_for(DAY) is None
        assert led.settled_samples(0) == 0

    def test_three_hour_dark_day_records_no_actual(self):
        led = ForecastLedger()
        led.settle_day(DAY, 3.0, 180.0)
        assert led.actual_for(DAY) is None

    def test_ten_minute_blip_is_recorded(self):
        led = ForecastLedger()
        led.settle_day(DAY, 9.5, 10.0)
        assert led.actual_for(DAY) == 9.5

    def test_the_limit_itself_counts(self):
        led = ForecastLedger()
        led.settle_day(DAY, 9.5, DARK_DAY_MAX_MIN)
        assert led.actual_for(DAY) == 9.5

    def test_snow_day_readable_input_is_zero_and_pv_health_sees_it(self):
        led = ForecastLedger()
        led.record(DAY, 0, 12.0)
        led.settle_day(DAY, 0.0, 0.0)
        assert led.actual_for(DAY) == 0.0
        h = pv_health([(12.0, 0.0)] * 3, 0, True, 0, 0, None)
        assert h.settled_days == 3 and h.ratio_7d == 0.0

    def test_morning_value_cleared_when_the_afternoon_goes_dark(self):
        led = ForecastLedger()
        led.settle_day(DAY, 4.0, 0.0)
        assert led.actual_for(DAY) == 4.0
        assert led.settle_day(DAY, 4.0, 200.0) is True
        assert led.actual_for(DAY) is None
        led.settle_day(DAY, 5.0, 0.0)           # a later settle stays refused
        assert led.actual_for(DAY) is None

    def test_dark_mark_survives_persistence(self):
        led = ForecastLedger()
        led.settle_day(DAY, 0.0, 600.0)
        back = ForecastLedger.from_dict(led.to_dict())
        assert back.is_dark(DAY) and back.actual_for(DAY) is None

    def test_pv_health_skips_the_dark_day(self):
        led = ForecastLedger()
        for d in ("2026-11-10", "2026-11-11", "2026-11-12"):
            led.record(d, 0, 12.0)
            led.settle_day(d, 12.0, 0.0)
        led.record("2026-11-13", 0, 12.0)
        led.settle_day("2026-11-13", 0.0, 600.0)
        pairs = [(led.forecast_for(d, 0), led.actual_for(d)) for d in led.days()]
        h = pv_health(pairs, 600.0, None, 0, 0, None)
        assert h.settled_days == 3 and h.ratio_7d == 1.0
        assert h.days_since_full_yield == 0 and h.downtime_min_today == 600


class TestCoordinator:
    def test_active_ledger_dark_day_not_settled(self):
        c = _coord()
        _run(c, 600.0, 0.0)
        assert c._forecast_ledger.actual_for(DAY) is None
        assert c._forecast_ledger.is_dark(DAY)

    def test_active_ledger_blip_settled(self):
        c = _coord()
        _run(c, 10.0, 7.0)
        assert c._forecast_ledger.actual_for(DAY) == 7.0

    def test_every_source_ledger_follows_the_rule(self):
        c = _coord()
        _run(c, 600.0, 0.0)
        assert c._source_ledgers["a"].actual_for(DAY) is None
        c2 = _coord()
        _run(c2, 0.0, 6.0)
        assert c2._source_ledgers["a"].actual_for(DAY) == 6.0

    def test_dark_mark_is_persisted_at_once(self):
        storage = MagicMock()
        storage.get_forecast_ledger_state.return_value = {}
        storage.get_source_ledgers_state.return_value = {}
        c = _coord(storage)
        _run(c, 600.0, 0.0)
        saved = storage.set_forecast_ledger_state.call_args[0][0]
        assert saved["days"][DAY]["dark"] is True

    def test_restart_keeps_the_day_dark_though_the_counter_reset(self):
        led = ForecastLedger()
        led.settle_day(DAY, 0.0, 600.0)
        c = _coord()
        c._forecast_ledger = ForecastLedger.from_dict(led.to_dict())
        # (#645) the day is SEM's own day clock
        c._tracker_date = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc).date()
        if True:
            assert c._solar_day_counts(SimpleNamespace(solar_downtime_min_today=0.0)) is False
            c._forecast_ledger = None
            assert c._solar_day_counts(SimpleNamespace(solar_downtime_min_today=0.0)) is True
            assert c._solar_day_counts(SimpleNamespace(solar_downtime_min_today=90.0)) is False


class TestTracker:
    def _day(self, counts):
        t = ForecastTracker()
        t._hass = None
        with patch("homeassistant.util.dt.now",
                   return_value=datetime(2026, 11, 16, 12, tzinfo=timezone.utc)):
            t.update(12.0, 0.0, "sunny", day_counts=counts)
        with patch("homeassistant.util.dt.now",
                   return_value=datetime(2026, 11, 17, 0, 5, tzinfo=timezone.utc)):
            t.update(12.0, 0.0, "sunny")
        return t

    def test_dark_day_is_not_taught(self):
        assert len(self._day(False)._history) == 0

    def test_readable_zero_day_is_recorded(self):
        t = self._day(True)
        assert len(t._history) == 1 and t._history[0].actual_kwh == 0.0
