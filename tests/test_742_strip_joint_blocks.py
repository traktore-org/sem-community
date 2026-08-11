"""#742 — the EV strip's rows come from the joint plan's BLOCKS when covered.

Live evidence (08.08 23:10): the Energy Plan card said WAITS·00:00 while
the EV tab's mini-strip painted the static tariff's reactive prediction
(idle till ~05:00). Post-C3 the wait FLAG already comes from the overlay,
but the strip still had only one derived instant (next_cheap_window) and a
rate-math min-reached — a multi-block night and the plan's own end time
were invisible.

``compose_today_plan`` now takes ``ev_plan_blocks`` (THIS charger's blocks
from the stamped plan, passed only when the gate covers the demand): one
``ev_charge_start`` row per future block with the ``plan_ev_charge_joint``
detail, and the min-reached row at the LAST block's end — the plan's own
promise, not a rate estimate. Without blocks the legacy composition is the
uncovered fallback, unchanged. One data source, every surface."""

from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.today_plan import (
    KIND_EV_CHARGE_START,
    KIND_EV_MIN_REACHED,
    compose_today_plan,
)

NOW = datetime(2026, 8, 11, 22, 0)


def _blocks(*windows):
    return [{"start": s.isoformat(), "end": e.isoformat(), "power_w": 4140.0}
            for s, e in windows]


def _compose(**kw):
    base = dict(now=NOW, upcoming_prices=[], ev_min_remaining_kwh=5.0,
                night_start=NOW + timedelta(hours=1))
    base.update(kw)
    return compose_today_plan(**base)


@pytest.mark.unit
class TestBlocksDriveTheRows:
    def test_one_charge_start_row_per_future_block(self):
        b1 = (NOW + timedelta(hours=2), NOW + timedelta(hours=3))
        b2 = (NOW + timedelta(hours=5), NOW + timedelta(hours=6))
        rows = _compose(ev_plan_blocks=_blocks(b1, b2))
        starts = [r for r in rows if r["kind"] == KIND_EV_CHARGE_START]
        assert [r["when"] for r in starts] == [b1[0].isoformat(), b2[0].isoformat()]
        assert all(r.get("detail") == "plan_ev_charge_joint" for r in starts)

    def test_min_reached_is_the_last_blocks_end(self):
        b1 = (NOW + timedelta(hours=2), NOW + timedelta(hours=3))
        b2 = (NOW + timedelta(hours=5), NOW + timedelta(hours=6))
        rows = _compose(ev_plan_blocks=_blocks(b1, b2),
                        ev_effective_rate_kw=5.0)
        done = [r for r in rows if r["kind"] == KIND_EV_MIN_REACHED]
        assert len(done) == 1
        assert done[0]["when"] == b2[1].isoformat()  # the plan's promise

    def test_the_reactive_night_row_is_suppressed_when_blocks_exist(self):
        b1 = (NOW + timedelta(hours=2), NOW + timedelta(hours=3))
        rows = _compose(ev_plan_blocks=_blocks(b1))
        night_details = [r for r in rows if r["kind"] == KIND_EV_CHARGE_START
                         and r.get("detail") != "plan_ev_charge_joint"]
        assert night_details == []

    def test_a_block_already_running_adds_no_start_row_for_it(self):
        running = (NOW - timedelta(minutes=30), NOW + timedelta(hours=1))
        later = (NOW + timedelta(hours=4), NOW + timedelta(hours=5))
        rows = _compose(ev_plan_blocks=_blocks(running, later))
        starts = [r for r in rows if r["kind"] == KIND_EV_CHARGE_START]
        assert [r["when"] for r in starts] == [later[0].isoformat()]

    def test_no_blocks_keeps_the_legacy_fallback(self):
        rows = _compose(ev_plan_blocks=None)
        starts = [r for r in rows if r["kind"] == KIND_EV_CHARGE_START]
        assert len(starts) == 1
        assert starts[0].get("detail") == "plan_ev_charge_night"

    def test_malformed_blocks_fall_back_not_crash(self):
        rows = _compose(ev_plan_blocks=[{"start": "junk", "end": None}])
        starts = [r for r in rows if r["kind"] == KIND_EV_CHARGE_START]
        assert len(starts) == 1  # the legacy night row


@pytest.mark.unit
class TestTheCoordinatorPassesCoveredBlocks:
    def test_both_call_sites_thread_the_blocks(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator)
        assert src.count("ev_plan_blocks=") >= 1
        assert "_ev_blocks_for(" in src
