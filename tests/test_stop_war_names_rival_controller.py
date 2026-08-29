"""The stop-war warning must name a rival controller as a candidate cause.

Live on PROD 29.08.2026: a second SEM instance (a test rig wired to the same
physical KEBA, left actuating after a clean install) fought PROD's stop for
40 minutes — four stop→redraw round-trips, the #763 ceasefire stood down, and
~5 kWh went into a car whose charge mode was Off.

From inside one instance a rival controller is INDISTINGUISHABLE from the
wallbox's own auto-start: both look like "the box re-closes the contactor
after my stop". The warning named only the wallbox, so the diagnosis went to
the hardware first and cost an hour. The evidence that settles it is cheap —
a stop that starts holding the moment the other controller is silenced — but
only if the reader is told to look.

This pins the second candidate into the message. It is a diagnosability fix:
no control-flow changes, the ceasefire is untouched.
"""
from __future__ import annotations

import pathlib
import re

SRC = (pathlib.Path(__file__).resolve().parent.parent
       / "coordinator" / "charger_reconciler.py")


def _stop_war_message() -> str:
    """The warning's literal text, joined across its implicit concatenation."""
    text = SRC.read_text()
    start = text.index("stop war detected")
    end = text.index("self.charger_id", start)
    # The literal spans several implicitly-concatenated lines; strip the
    # quoting and indentation rather than trying to re-parse it.
    return re.sub(r'["\s]+', " ", text[start:end])


class TestTheWarningNamesBothCauses:
    def test_the_wallbox_autostart_cause_survives(self):
        msg = _stop_war_message().lower()
        assert "auto-start" in msg, (
            "the original cause is still the most common one — it stays"
        )

    def test_a_second_controller_is_named(self):
        msg = _stop_war_message().lower()
        assert "controller" in msg or "instance" in msg, (
            "a rival controller writing to the same charger looks identical "
            "from here and must be offered as a candidate — PROD 29.08"
        )

    def test_it_tells_the_reader_how_to_tell_them_apart(self):
        msg = _stop_war_message().lower()
        assert any(k in msg for k in ("another", "second", "other")), (
            "naming the cause is not enough; the message must point at the "
            "check that separates the two"
        )
