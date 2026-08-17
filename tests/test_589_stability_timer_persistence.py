"""#589 — restart-safe timing for the EV charge-stability layer.

ChargeStability holds per-charger timer stamps as ``time.monotonic()``
values in RAM. On an HA restart, ``time.monotonic()`` restarts near 0
and all dicts are empty, so a deep-solar-deficit that was 40 s into its
45 s grace window would re-arm a full fresh window instead of stopping
the charger promptly — allowing the battery to drain for another 45 s
(the #461 deep-deficit bug, re-armed by every restart).

``snapshot_timers`` captures elapsed seconds; ``restore_timers`` rebases
them onto the new monotonic clock so the countdown resumes exactly where
it was.

Rebase formula: ``stamp = now_mono - elapsed``
Invariant: ``new_now - restored_stamp == elapsed`` (within floating-point
tolerance, since monotonic advances between snapshot and restore).
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.charge_stability import (
    ChargeStability,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stability_with_deficit(
    cid: str,
    deficit_elapsed_s: float,
    deep_deficit_elapsed_s: float | None,
    now_mono: float,
) -> ChargeStability:
    """Build a ChargeStability with pre-set timer stamps for ``cid``."""
    cs = ChargeStability()
    cs._deficit_since[cid] = now_mono - deficit_elapsed_s
    if deep_deficit_elapsed_s is not None:
        cs._deep_deficit_since[cid] = now_mono - deep_deficit_elapsed_s
    cs._sem_session.add(cid)
    return cs


# ---------------------------------------------------------------------------
# 1. Round-trip: snapshot → restore preserves elapsed
# ---------------------------------------------------------------------------

class TestSnapshotRestoreRoundTrip:
    """A snapshot taken at now_mono=1000, restored at now_mono=5 (new clock)
    must present the same elapsed time to the new clock.
    """

    def test_deficit_elapsed_preserved(self) -> None:
        cid = "wb"
        snapshot_mono = 1000.0
        deficit_started_at = 940.0  # 60 s ago at snapshot time
        elapsed_at_snapshot = snapshot_mono - deficit_started_at  # 60.0

        cs_old = ChargeStability()
        cs_old._deficit_since[cid] = deficit_started_at

        snap = cs_old.snapshot_timers(snapshot_mono)
        assert snap["deficit"][cid] == pytest.approx(60.0)

        # Simulate restart: new instance, new clock
        restore_mono = 5.0
        cs_new = ChargeStability()
        cs_new.restore_timers(snap, restore_mono)

        # stamp = restore_mono - elapsed = 5.0 - 60.0 = -55.0
        # restore_mono - stamp = 5.0 - (-55.0) = 60.0
        restored_stamp = cs_new._deficit_since[cid]
        assert restore_mono - restored_stamp == pytest.approx(elapsed_at_snapshot)

    def test_all_six_dicts_round_trip(self) -> None:
        cid = "wb"
        mono = 500.0
        cs = ChargeStability()
        cs._deficit_since[cid] = mono - 30.0
        cs._deep_deficit_since[cid] = mono - 20.0
        cs._surplus_since[cid] = mono - 10.0
        cs._start_since[cid] = mono - 5.0
        cs._latched[cid] = mono - 15.0
        cs._stopped_at[cid] = mono - 2.0

        snap = cs.snapshot_timers(mono)

        new_mono = 3.0
        cs2 = ChargeStability()
        cs2.restore_timers(snap, new_mono)

        assert new_mono - cs2._deficit_since[cid] == pytest.approx(30.0)
        assert new_mono - cs2._deep_deficit_since[cid] == pytest.approx(20.0)
        assert new_mono - cs2._surplus_since[cid] == pytest.approx(10.0)
        assert new_mono - cs2._start_since[cid] == pytest.approx(5.0)
        assert new_mono - cs2._latched[cid] == pytest.approx(15.0)
        assert new_mono - cs2._stopped_at[cid] == pytest.approx(2.0)

    def test_multiple_chargers_restored_independently(self) -> None:
        mono = 200.0
        cs = ChargeStability()
        cs._deficit_since["wb1"] = mono - 40.0
        cs._deficit_since["wb2"] = mono - 70.0

        snap = cs.snapshot_timers(mono)

        new_mono = 10.0
        cs2 = ChargeStability()
        cs2.restore_timers(snap, new_mono)

        assert new_mono - cs2._deficit_since["wb1"] == pytest.approx(40.0)
        assert new_mono - cs2._deficit_since["wb2"] == pytest.approx(70.0)


# ---------------------------------------------------------------------------
# 2. DRAIN scenario: deep-deficit 40 s in, restart must keep it at 40 s
# ---------------------------------------------------------------------------

class TestDrainScenario:
    """A ``_deep_deficit_since`` that is 40 s old before restart must be
    treated as 40 s old after restore — not reset to 0 — so it fires the
    stop within the remaining 5 s of the 45 s grace window.
    """

    def test_deep_deficit_40s_old_after_restore(self) -> None:
        cid = "wb"
        pre_restart_mono = 1000.0
        deep_deficit_elapsed = 40.0  # 40 s into the 45 s grace
        cs_before = _make_stability_with_deficit(
            cid,
            deficit_elapsed_s=40.0,
            deep_deficit_elapsed_s=deep_deficit_elapsed,
            now_mono=pre_restart_mono,
        )

        snap = cs_before.snapshot_timers(pre_restart_mono)

        # HA restarts; new monotonic starts at 2.0
        post_restart_mono = 2.0
        cs_after = ChargeStability()
        cs_after.restore_timers(snap, post_restart_mono)

        deep_elapsed_after = post_restart_mono - cs_after._deep_deficit_since[cid]
        assert deep_elapsed_after == pytest.approx(deep_deficit_elapsed)

    def test_deep_deficit_not_reset_to_zero(self) -> None:
        """Verifying the bug the fix closes: without restore, elapsed would be 0."""
        cid = "wb"
        mono = 1000.0
        cs = _make_stability_with_deficit(
            cid,
            deficit_elapsed_s=40.0,
            deep_deficit_elapsed_s=40.0,
            now_mono=mono,
        )
        snap = cs.snapshot_timers(mono)

        new_mono = 2.0
        cs_new = ChargeStability()

        # Without restore, the dict is empty → no countdown, effectively 0s elapsed
        assert cid not in cs_new._deep_deficit_since

        cs_new.restore_timers(snap, new_mono)
        # With restore, elapsed is ~40 s — near the 45 s stop threshold
        assert (new_mono - cs_new._deep_deficit_since[cid]) == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# 3. Cap guard: elapsed > 86400 s is ignored
# ---------------------------------------------------------------------------

class TestCapGuard:
    def test_elapsed_beyond_24h_is_dropped(self) -> None:
        cid = "wb"
        snap = {
            "deficit": {cid: 86_401.0},   # just over 24 h
            "deep_deficit": {cid: 100_000.0},
            "surplus": {},
            "start": {},
            "latched": {},
            "stopped_at": {},
        }
        cs = ChargeStability()
        cs.restore_timers(snap, now_mono=10.0)

        assert cid not in cs._deficit_since
        assert cid not in cs._deep_deficit_since

    def test_exactly_86400_is_dropped(self) -> None:
        """The cap is half-open: elapsed must be strictly < 86400 to be accepted."""
        snap = {
            "deficit": {"wb": 86_400.0},
            "deep_deficit": {},
            "surplus": {},
            "start": {},
            "latched": {},
            "stopped_at": {},
        }
        cs = ChargeStability()
        cs.restore_timers(snap, now_mono=5.0)
        assert "wb" not in cs._deficit_since

    def test_negative_elapsed_is_dropped(self) -> None:
        snap = {
            "deficit": {"wb": -1.0},
            "deep_deficit": {"wb": -0.001},
            "surplus": {},
            "start": {},
            "latched": {},
            "stopped_at": {},
        }
        cs = ChargeStability()
        cs.restore_timers(snap, now_mono=5.0)
        assert "wb" not in cs._deficit_since
        assert "wb" not in cs._deep_deficit_since

    def test_valid_elapsed_just_inside_cap(self) -> None:
        snap = {
            "deficit": {"wb": 86_399.9},
            "deep_deficit": {},
            "surplus": {},
            "start": {},
            "latched": {},
            "stopped_at": {},
        }
        cs = ChargeStability()
        cs.restore_timers(snap, now_mono=5.0)
        assert "wb" in cs._deficit_since


# ---------------------------------------------------------------------------
# 4. Malformed blob guards
# ---------------------------------------------------------------------------

class TestMalformedBlob:
    def test_non_dict_blob_does_not_raise(self) -> None:
        cs = ChargeStability()
        cs.restore_timers(None, now_mono=5.0)   # type: ignore[arg-type]
        cs.restore_timers("garbage", now_mono=5.0)  # type: ignore[arg-type]
        cs.restore_timers(42, now_mono=5.0)         # type: ignore[arg-type]

    def test_missing_keys_are_silently_skipped(self) -> None:
        """A blob with only some keys present must not raise."""
        snap = {"deficit": {"wb": 30.0}}  # all other keys absent
        cs = ChargeStability()
        cs.restore_timers(snap, now_mono=5.0)
        assert "wb" in cs._deficit_since

    def test_non_numeric_elapsed_is_skipped(self) -> None:
        snap = {
            "deficit": {"wb": "not_a_number"},
            "deep_deficit": {},
            "surplus": {},
            "start": {},
            "latched": {},
            "stopped_at": {},
        }
        cs = ChargeStability()
        cs.restore_timers(snap, now_mono=5.0)
        assert "wb" not in cs._deficit_since

    def test_inner_dict_replaced_by_non_dict_is_skipped(self) -> None:
        snap = {
            "deficit": "should_be_dict",
            "deep_deficit": None,
            "surplus": 42,
            "start": {},
            "latched": {},
            "stopped_at": {},
        }
        cs = ChargeStability()
        cs.restore_timers(snap, now_mono=5.0)  # must not raise

    def test_empty_snapshot_is_a_no_op(self) -> None:
        cs_old = ChargeStability()
        snap_dict = cs_old.snapshot_timers(1000.0)
        # All sub-dicts are empty → restore must leave new instance clean
        cs_new = ChargeStability()
        cs_new.restore_timers(snap_dict, now_mono=5.0)
        assert not cs_new._deficit_since
        assert not cs_new._deep_deficit_since
        assert not cs_new._surplus_since
        assert not cs_new._start_since
        assert not cs_new._latched
        assert not cs_new._stopped_at


# ---------------------------------------------------------------------------
# 5. snapshot_timers: only non-negative, finite elapsed values are emitted
# ---------------------------------------------------------------------------

class TestSnapshotOutput:
    def test_snapshot_omits_future_stamps(self) -> None:
        """A stamp in the future (bug/clock jump) must not appear in snapshot."""
        mono = 100.0
        cs = ChargeStability()
        # A stamp 10 s in the future → elapsed = -10 → must be dropped
        cs._deficit_since["wb"] = mono + 10.0
        snap = cs.snapshot_timers(mono)
        assert "wb" not in snap["deficit"]

    def test_snapshot_elapsed_is_non_negative(self) -> None:
        mono = 300.0
        cs = ChargeStability()
        cs._deficit_since["wb"] = mono - 55.0
        snap = cs.snapshot_timers(mono)
        assert snap["deficit"]["wb"] >= 0.0

    def test_snapshot_of_clean_instance_is_all_empty(self) -> None:
        cs = ChargeStability()
        snap = cs.snapshot_timers(500.0)
        for key in ("deficit", "deep_deficit", "surplus", "start", "latched", "stopped_at"):
            assert snap[key] == {}
