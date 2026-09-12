"""#923 — a card must survive a module's entities not existing.

On a battery-less install ``hass.states['sensor.sem_battery_soc']`` is
``undefined``. ``states[x].state`` then throws inside render and Lovelace
paints an error card. Every read goes through ``?.``."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "dashboard" / "card" / "src"
UNGUARDED = re.compile(r"states\[[^\]]+\]\.[A-Za-z_]")


def test_no_card_dereferences_a_state_lookup_unguarded():
    hits = []
    for js in sorted(SRC.rglob("*.js")):
        for n, line in enumerate(js.read_text(encoding="utf-8").splitlines(), 1):
            if UNGUARDED.search(line):
                hits.append(f"{js.relative_to(SRC)}:{n}: {line.strip()}")
    assert not hits, "unguarded state reads (use ?.):\n" + "\n".join(hits)
