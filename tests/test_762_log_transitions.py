"""#762 — a log line is a transition, not a heartbeat.

Measured on the .175 rig (13.08, one harvested half-day at DEBUG): the
same six steady-state lines repeated ~8,000 times — `decide_battery →
normal` 1423×, `actuate_battery: NORMAL` 1424×, `Charging strategy:
idle` 1792×, `Scheduled delayed save` 1930× — and the observer seam
emitted ~950 INFO lines for decisions that had not changed. That volume
is why the host's log ring held ~2 minutes and the N1 night's evidence
was gone by morning, and it is what HA's native "Enable debug logging"
download drowns in.

The contract: an UNCHANGED decision is silent; every CHANGE logs. The
gate is `utils.log_gate.log_on_change` — one shared cache, keyed by
(logger, key), so a flap still logs every edge (edges ARE the signal).
"""
from __future__ import annotations

import logging

import pytest

from custom_components.solar_energy_management.utils.log_gate import (
    log_on_change, reset_log_gate,
)


@pytest.fixture(autouse=True)
def _clean_gate():
    reset_log_gate()
    yield
    reset_log_gate()


class TestLogOnChange:

    def test_the_first_message_logs(self, caplog) -> None:
        lg = logging.getLogger("sem.test.a")
        with caplog.at_level(logging.DEBUG, logger="sem.test.a"):
            log_on_change(lg, "k", logging.DEBUG, "state %s", "normal")
        assert caplog.text.count("state normal") == 1

    def test_the_same_message_is_silent(self, caplog) -> None:
        lg = logging.getLogger("sem.test.b")
        with caplog.at_level(logging.DEBUG, logger="sem.test.b"):
            for _ in range(50):
                log_on_change(lg, "k", logging.DEBUG, "state %s", "normal")
        assert caplog.text.count("state normal") == 1

    def test_a_change_logs_and_a_flap_logs_every_edge(self, caplog) -> None:
        lg = logging.getLogger("sem.test.c")
        with caplog.at_level(logging.DEBUG, logger="sem.test.c"):
            for s in ("normal", "normal", "limit", "limit", "normal"):
                log_on_change(lg, "k", logging.DEBUG, "state %s", s)
        assert caplog.text.count("state normal") == 2
        assert caplog.text.count("state limit") == 1

    def test_keys_are_independent(self, caplog) -> None:
        """Two batteries with the same message must not mask each other."""
        lg = logging.getLogger("sem.test.d")
        with caplog.at_level(logging.DEBUG, logger="sem.test.d"):
            log_on_change(lg, "b1", logging.DEBUG, "intent %s", "normal")
            log_on_change(lg, "b2", logging.DEBUG, "intent %s", "normal")
        assert caplog.text.count("intent normal") == 2

    def test_a_disabled_level_costs_nothing_and_remembers_nothing(
            self, caplog) -> None:
        """While debug is OFF, the gate must not record state — otherwise
        enabling debug later (the HA toggle flow) would suppress the
        first line as 'unchanged' when the user never saw it."""
        lg = logging.getLogger("sem.test.e")
        with caplog.at_level(logging.INFO, logger="sem.test.e"):
            log_on_change(lg, "k", logging.DEBUG, "state %s", "normal")
        with caplog.at_level(logging.DEBUG, logger="sem.test.e"):
            log_on_change(lg, "k", logging.DEBUG, "state %s", "normal")
        assert caplog.text.count("state normal") == 1

    def test_bad_format_args_never_raise(self, caplog) -> None:
        lg = logging.getLogger("sem.test.f")
        with caplog.at_level(logging.DEBUG, logger="sem.test.f"):
            log_on_change(lg, "k", logging.DEBUG, "state %d", "not-a-number")
        # Degrades to logging something rather than crashing the cycle.
        assert "state" in caplog.text

    def test_a_wobbling_measurement_is_not_news(self, caplog) -> None:
        """The .175 tell: `limit_discharge ... 594 W` -> `602 W` -> `590 W`
        every cycle, decision unchanged. Dedup judges the digit-stripped
        message; the emitted line still carries the live number as of
        each real transition."""
        lg = logging.getLogger("sem.test.g")
        with caplog.at_level(logging.DEBUG, logger="sem.test.g"):
            for w in (594, 602, 590, 574):
                log_on_change(lg, "b1", logging.DEBUG,
                              "limit_discharge %d W — ev plugged in", w)
            log_on_change(lg, "b1", logging.DEBUG,
                          "normal — no protection")
            log_on_change(lg, "b1", logging.DEBUG,
                          "limit_discharge %d W — ev plugged in", 610)
        assert caplog.text.count("limit_discharge 594 W") == 1
        assert "602 W" not in caplog.text
        assert "normal — no protection" in caplog.text
        assert "limit_discharge 610 W" in caplog.text


class TestTheOffendersAreGated:
    """The sweep itself: the measured top emitters go through the gate.
    Grep-level pins so a revert shows up as a failing test, not as a
    2-minute log ring six months from now."""

    def _src(self, rel: str) -> str:
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        return (root / rel).read_text()

    def test_the_delayed_save_heartbeat_is_gone(self) -> None:
        assert "Scheduled delayed save" not in self._src(
            "coordinator/storage.py")

    def test_decide_and_actuate_battery_are_gated(self) -> None:
        for rel, marker in (
            ("coordinator/coordinator.py", "decide_battery(%s) → intent="),
            ("coordinator/actuate_battery.py", "actuate_battery(%s): NORMAL"),
            ("coordinator/actuate_battery.py",
             "actuate_battery(%s): LIMIT_DISCHARGE"),
        ):
            src = self._src(rel)
            idx = src.find(marker)
            assert idx > 0, f"log site moved: {marker!r}"
            assert "log_on_change" in src[max(0, idx - 300):idx], (
                f"{marker!r} is not transition-gated"
            )

    def test_the_observer_seam_is_gated(self) -> None:
        src = self._src("coordinator/surplus_controller.py")
        idx = src.find("OBSERVER · WOULD ACTIVATE")
        assert idx > 0
        assert "log_on_change" in src[max(0, idx - 400):idx], (
            "the observer WOULD lines log every cycle at INFO"
        )
