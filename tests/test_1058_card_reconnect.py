"""#1058 — the Energy tab's charts drew once; after a tab switch they were empty.

Home Assistant takes a view's cards off the page when you leave a tab and puts
the SAME card objects back when you return. The chart card destroyed its chart
on leaving and built it only in ``firstUpdated()``, which runs once. The flow
card, the system diagram and the title card lost their watchers or template
subscription the same way, and Lit does not render a card that comes back.

The behaviour is tested in ``dashboard/card/test/reconnect.test.js`` (the real
card code, driven through leave-and-return, plus a source check over every
card), run by CI's card-test job. This file checks only that the BUILT bundle
HA loads was rebuilt with the fix: what it pins is the text of a build
output, like ``test_646_stable_report.py::test_bundle_is_rebuilt``.
"""

from pathlib import Path

DIST = (
    Path(__file__).resolve().parents[1] / "dashboard" / "card" / "dist" / "sem-cards.js"
).read_text()


def test_chart_card_draws_again_on_return():
    assert "this._period&&this._redraw()" in DIST, "dist/sem-cards.js not rebuilt after #1058"


def test_chart_card_drops_an_answer_that_lands_after_leaving():
    assert "this._fetchSeq++" in DIST


def test_flow_card_and_diagram_watch_again_on_return():
    assert "this.hasUpdated&&this._observe()" in DIST
    assert "this.hasUpdated&&(this._observe(),this._targets&&this._startTickIfIdle())" in DIST


def test_title_card_subscribes_again_on_return():
    assert "this._hass&&this._hasJinja(this._config?.subtitle)&&this._subscribeTemplate()" in DIST


def test_every_card_draws_again_on_return():
    # SEMLitBase.connectedCallback asks for a render when the card comes back.
    assert "this.hasUpdated&&this.requestUpdate()" in DIST
