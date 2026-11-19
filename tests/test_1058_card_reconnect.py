"""#1058 — the charts drew once; after a tab switch they were empty.

(#1321) The chart, flow, diagram and title cards this was first written for
are gone with the classic dashboard. The SEM dashboard's cards keep their
timers in connectedCallback and clear them in disconnectedCallback
(dashboard/card/test/next-reconnect.test.js); the base class asks for a render
on return, which is what this file still pins in the built bundle.

Home Assistant takes a view's cards off the page when you leave a tab and puts
the SAME card objects back when you return; Lit does not render a card that
comes back. This file checks only that the BUILT bundle HA loads carries the
base-class fix, like ``test_646_stable_report.py::test_bundle_is_rebuilt``.
"""

from pathlib import Path

DIST = (
    Path(__file__).resolve().parents[1] / "dashboard" / "card" / "dist" / "sem-cards.js"
).read_text()


def test_every_card_draws_again_on_return():
    # SEMLitBase.connectedCallback asks for a render when the card comes back.
    assert "this.hasUpdated&&this.requestUpdate()" in DIST
