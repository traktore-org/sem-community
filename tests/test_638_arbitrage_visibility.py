"""(#638 C7, Guido's PROD card 16.08 08:05) The arbitrage advisor is an
INSTRUMENT, and an instrument's readout is not a user's answer.

The advisor runs on every stamp by design — it reads every page of the
ledger, so an economically-absurd advice is the first symptom of a lying
book. That is worth keeping. What is NOT defensible is printing its
verdict on the dashboard of an install where arbitrage *cannot happen*:
Guido's battery is in ``auto``, the global toggle is off (#533 stands),
and his card still said

    Battery arbitrage — no room to buy into: battery 6.3/15.0 kWh full…

which reads as "SEM wanted to trade tonight and the battery was in the
way". Nothing wanted to trade. The feature is closed.

So: the advice keeps being computed and logged; the PLAN says whether
arbitrage can act at all, and the card renders the verdict only then.
One fact, one accessor, asked in both places that care.
"""
from __future__ import annotations

import inspect
import pathlib
import re
from types import SimpleNamespace

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent


def _enabled(*, global_toggle: bool, modes: list[str]) -> bool:
    """Call the accessor on a stub carrying only what it may read."""
    from custom_components.solar_energy_management.coordinator.coordinator \
        import SEMCoordinator
    fake = SimpleNamespace()
    fake._battery_scheduler_config = SimpleNamespace(
        arbitrage_enabled=global_toggle)
    fake._per_battery_config = lambda idx, count=1: {
        "battery_mode": modes[idx]}
    return SEMCoordinator._arbitrage_enabled(fake, len(modes))


@pytest.mark.unit
class TestTheOneAccessor:
    """Whether arbitrage can act is ONE fact. Before this it was an inline
    expression in the battery pipeline and nowhere else — so the plan
    payload and the card had no way to ask."""

    def test_a_default_install_cannot_arbitrage(self):
        # Guido's PROD: one battery, mode auto, global toggle off.
        assert _enabled(global_toggle=False, modes=["auto"]) is False

    def test_a_battery_in_allow_arbitrage_opens_the_valve(self):
        assert _enabled(global_toggle=False,
                        modes=["auto", "allow_arbitrage"]) is True

    def test_the_global_toggle_opens_the_valve(self):
        assert _enabled(global_toggle=True, modes=["auto"]) is True

    def test_a_batteryless_install_cannot_arbitrage(self):
        assert _enabled(global_toggle=False, modes=[]) is False

    def test_the_battery_pipeline_asks_the_accessor_not_its_own_copy(self):
        """The mode scan existed inline in ``_run_battery_pipeline``. Two
        copies of one rule is how the card and the pipeline come to
        disagree — the same shape as every bug in this file's neighbours."""
        from custom_components.solar_energy_management.coordinator import (
            coordinator as mod)
        src = pathlib.Path(inspect.getfile(mod)).read_text()
        assert src.count('== "allow_arbitrage"') == 1, (
            "the allow_arbitrage mode scan must live in exactly one place "
            "— _arbitrage_enabled")
        pipeline = inspect.getsource(mod.SEMCoordinator._run_battery_pipeline)
        assert "self._arbitrage_enabled(" in pipeline


@pytest.mark.unit
class TestThePlanSaysWhetherArbitrageCanAct:
    def test_the_advisor_payload_carries_the_gate(self):
        """``arbitrage`` is published for diagnostics on every stamp; the
        consumer needs to know it is a closed feature's readout."""
        from custom_components.solar_energy_management.coordinator import (
            coordinator as mod)
        src = inspect.getsource(mod.SEMCoordinator._shadow_energy_plan)
        # the dict literal that builds the published advice
        assert re.search(r'"reason":\s*_adv\.reason', src), (
            "this pin is reading the wrong lines")
        assert '"enabled": _arb_on' in src, (
            "the published advice must say whether arbitrage can act")


@pytest.mark.unit
class TestTheCardHidesAClosedFeature:
    def test_the_advisor_row_is_gated_on_enabled(self):
        card = (ROOT / "dashboard" / "card" / "src" / "cards"
                / "sem-energy-plan-card.js").read_text()
        body = card.split("_renderArb(arb)", 1)[1].split("_renderIdle", 1)[0]
        assert "arb.enabled" in body, (
            "the card must not render the advisor's verdict on an install "
            "where arbitrage cannot act (Guido's PROD, 16.08)")
