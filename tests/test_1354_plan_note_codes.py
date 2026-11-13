"""#1354 — every planner note also leaves the packer as codes + params,
so cards translate it; the English note stays for logs."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "coordinator" / "energy_planner.py").read_text()
HELPER = (ROOT / "dashboard" / "card" / "src" / "util" / "plan-notes.js").read_text()


def test_each_note_sentence_has_a_code_next_to_it():
    codes = set(re.findall(r'\("([a-z_]+)",\s*\{', SRC))
    listed = set(re.findall(r"'([a-z_]+)'", HELPER.split("PLAN_NOTE_CODES")[1].split("]")[0]))
    assert codes == listed, (codes, listed)
    assert len(codes) == 7


def test_the_packer_publishes_codes_for_an_empty_night():
    from custom_components.solar_energy_management.coordinator.energy_planner import (
        pack_night,
    )
    from types import SimpleNamespace
    d = SimpleNamespace(id="ev:x", energy_kwh=2.0, priority=1)
    plan = pack_night([d], [])
    r = plan.results[0]
    assert r.note == "no night window"
    assert r.note_codes == (("no_night_window", {}),)
