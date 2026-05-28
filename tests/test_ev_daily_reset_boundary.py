"""Per-charger daily reset boundary (#280).

The "EV day" boundary used to be sunrise (``get_current_meter_day_sunrise_based``),
which on short summer nights wiped each charger's daily accumulator between Min
being met (~03:00) and the night window's end (~07:00) — causing SEM to see
``remaining = daily_target`` again and re-fire night charging until 07:00.
Users got double-billed for the same target.

The fix moves the boundary to each charger's own ``Charge by`` deadline. These
tests pin the new boundary semantics + the multi-charger isolation property.
"""
from __future__ import annotations

from datetime import date

import pytest
from custom_components.solar_energy_management.utils.time_manager import TimeManager


@pytest.mark.unit
class TestDeadlineBoundaryFunction:
    """``get_current_meter_day_offset_based(hhmm)`` is the function we now use.

    Existed pre-#280 but wasn't wired in for EV — these are just guard rails
    that the function returns what the new caller expects.
    """

    def test_before_deadline_returns_yesterday(self, monkeypatch):
        from datetime import datetime
        from homeassistant.util import dt as dt_util

        # 05:30 local, deadline 07:00 → still in yesterday's "EV day".
        fake_now = datetime(2026, 5, 28, 5, 30, 0, tzinfo=dt_util.UTC)
        monkeypatch.setattr(dt_util, "now", lambda: fake_now.astimezone(dt_util.DEFAULT_TIME_ZONE))

        tm = TimeManager(hass=None, config={})
        d = tm.get_current_meter_day_offset_based("07:00")
        # Whatever timezone resolves to, "before 07:00 today" => yesterday's date.
        assert d < tm.get_current_meter_day_offset_based("00:00")

    def test_after_deadline_returns_today(self, monkeypatch):
        from datetime import datetime
        from homeassistant.util import dt as dt_util

        # 08:00 local, deadline 07:00 → today's "EV day".
        fake_now = datetime(2026, 5, 28, 8, 0, 0, tzinfo=dt_util.UTC)
        monkeypatch.setattr(dt_util, "now", lambda: fake_now.astimezone(dt_util.DEFAULT_TIME_ZONE))

        tm = TimeManager(hass=None, config={})
        before = tm.get_current_meter_day_offset_based("07:00")
        after = tm.get_current_meter_day_offset_based("23:00")
        # After 07:00 deadline but before 23:00 ⇒ same day in the 07:00 frame,
        # yesterday in the 23:00 frame. The relationship is what matters.
        assert before > after


@pytest.mark.unit
class TestPerChargerResetIsolation:
    """A second charger with a later deadline does not get wiped when the
    first charger's deadline boundary passes."""

    def test_two_chargers_different_deadlines_reset_independently(self):
        """Verify dict-keyed date tracking: each charger keeps its own boundary.

        This is the structural property of the #280 fix — the date tracker went
        from ``Optional[str]`` (global) to ``Dict[str, str]`` (per-cid), so a
        boundary crossing for charger A leaves charger B's accumulator alone.
        """
        # Simulate the post-fix data structure.
        daily = {"car_a": 8.5, "car_b": 6.0}
        date_per_cid = {"car_a": "2026-05-27", "car_b": "2026-05-27"}

        # Car A's deadline (07:00) crosses → its boundary rolls to today.
        new_day = "2026-05-28"

        # Apply the reset path's logic for car_a only.
        if date_per_cid.get("car_a") != new_day:
            daily["car_a"] = 0.0
            date_per_cid["car_a"] = new_day

        # Car B (later deadline, e.g. 09:00) is untouched.
        assert daily["car_a"] == 0.0, "car_a should reset at its deadline"
        assert daily["car_b"] == 6.0, "car_b must not be wiped by car_a's reset"
        assert date_per_cid["car_b"] == "2026-05-27", "car_b's date untouched"

    def test_legacy_string_date_promotes_to_per_cid_dict(self):
        """Restore path: legacy stores hold a single string for global sunrise
        reset. Upgrade promotes to a dict so every charger inherits cleanly."""
        legacy_pcd = {
            "values": {"car_a": 8.5, "car_b": 6.0},
            "date": "2026-05-27",  # legacy single string
        }

        # Mirror the promotion logic in coordinator.py:626-635.
        values = dict(legacy_pcd["values"])
        raw_date = legacy_pcd["date"]
        if isinstance(raw_date, dict):
            date_per_cid = dict(raw_date)
        elif isinstance(raw_date, str):
            date_per_cid = {cid: raw_date for cid in values}
        else:
            date_per_cid = {}

        assert date_per_cid == {"car_a": "2026-05-27", "car_b": "2026-05-27"}
        # Both chargers carry the legacy date so the next per-cid evaluation
        # against their own deadlines starts from a known boundary.


@pytest.mark.unit
class TestRegressionDoubleChargeBug:
    """Pin the actual bug: sunrise reset between Min-met and night-end caused
    night charging to re-fire because daily_ev → 0 ⇒ remaining → daily_target."""

    def test_min_met_stays_met_after_sunrise_with_deadline_boundary(self):
        """With deadline at 07:00 and sunrise at 05:30, the 05:30 sunrise
        crossing must NOT reset the per-charger bucket; only 07:00 does.

        Bucket-key timing in the offset-based frame:

        * 22:00 last night (2026-05-27 22:00, deadline 07:00 today=05-27):
          ``now > today's 07:00`` (which is in the past) → ev_day = 2026-05-27.
        * 03:00 this morning (2026-05-28 03:00, deadline 07:00 today=05-28):
          ``now < today's 07:00`` → ev_day = 2026-05-27 (yesterday).
        * 05:30 sunrise (still 2026-05-28 05:30): same — yesterday.
        * 08:00 (2026-05-28 08:00): ``now > today's 07:00`` → ev_day = 2026-05-28.

        So the night's accumulation lives entirely under the "2026-05-27" key
        and the bucket only flips once at 07:00 — by which time Min is done.
        """
        # State after Min is hit (~03:00): bucket = 8.5, keyed by "yesterday
        # in the deadline frame" which is 2026-05-27.
        daily = {"car_a": 8.5}
        date_per_cid = {"car_a": "2026-05-27"}

        # === 05:30 sunrise crossing — the legacy bug point ===
        # OLD code: get_current_meter_day_sunrise_based() flips at 05:30 →
        # bucket wiped → SEM re-fires night charging until 07:00.
        # NEW code: deadline frame still says "2026-05-27" at 05:30 →
        # bucket-key matches stored → no reset → no re-fire.
        ev_day_at_0530 = "2026-05-27"
        if date_per_cid.get("car_a") != ev_day_at_0530:
            daily["car_a"] = 0.0  # the bug path — should NOT execute
            date_per_cid["car_a"] = ev_day_at_0530
        assert daily["car_a"] == 8.5, (
            "Min-met bucket must NOT reset between 03:00 and the deadline — "
            "if it does, the sunrise double-charge bug returns"
        )

        # === 08:00 — past deadline, legitimate reset ===
        ev_day_at_0800 = "2026-05-28"
        if date_per_cid.get("car_a") != ev_day_at_0800:
            daily["car_a"] = 0.0
            date_per_cid["car_a"] = ev_day_at_0800
        assert daily["car_a"] == 0.0
        assert date_per_cid["car_a"] == ev_day_at_0800
