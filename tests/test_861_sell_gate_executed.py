"""#861 item 1 — the sell gate's wiring, EXECUTED instead of source-read.

`test_778_forecast_sell.py` pins the coordinator wiring with
`inspect.getsource` substring checks — which prove the code is PRESENT,
not that it RUNS or that its flag truly gates it. Same doubt the coverage
audit raised for #820, answered the same way: drive the real method on a
faithful double and watch the wire.

`evaluate_forecast_sell` is monkeypatched with a recorder, so the assert
is on invocation — with the flag OFF the pipeline must never consult the
spend evaluator at all; with it ON (and the actuation kill switch armed)
the very same double reaches it. The ON case is the discriminator: it
proves this harness genuinely reaches the gate, so the OFF case's silence
is the flag's doing and not a broken double.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _double(spend_on: bool):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    async def _no_sched(*a, **kw):
        return None
    fake = SimpleNamespace(
        hass=hass,
        config={
            "forecast_spending_enabled": spend_on,
            "battery_max_discharge_power": 5000.0,
            "battery_reserve_soc": 20.0,
        },
        _energy_plan_actuation=True,
        _energy_plan_shadow={"forecast_sell": {"blocks": []}},
        _planning_evidence={"battery_spendable_kwh": 4.2,
                            "battery_dynamic_floor_pct": 35.0},
        _forecast_sell_active=False,
        data={},
        # Everything the pipeline touches before the gate — a scheduler
        # that answers None, no adapters, arbitrage off, mode watch quiet.
        _arbitrage_enabled=lambda *a, **kw: False,
        _battery_adapter=None,
        _battery_adapters={},
        _battery_charge_scheduler=SimpleNamespace(
            enabled=False, _decision=None),
        _battery_mode_watch=None,
        _battery_operating_mode=None,
        _compute_arbitrage_signals=lambda *a, **kw: None,
        _maybe_run_scheduler_evaluation=_no_sched,
        _per_battery_config=lambda *a, **kw: {},
    )
    return fake


@pytest.mark.asyncio
class TestTheSellGateExecutes:
    async def _run(self, fake, monkeypatch, calls):
        from custom_components.solar_energy_management.coordinator import (
            forecast_sell as fs,
        )

        def _recorder(*a, **kw):
            calls.append(kw)
            return SimpleNamespace(
                state=SimpleNamespace(value="idle"), reason="recorded",
                should_charge=False)
        monkeypatch.setattr(fs, "evaluate_forecast_sell", _recorder)
        try:
            await SEMCoordinator._run_battery_pipeline(
                fake, power=SimpleNamespace(batteries=None, battery_soc=50.0),
                energy=SimpleNamespace(), charging_state=None)
        except Exception:  # noqa: BLE001 — the double ends where it ends;
            pass           # the recorder has already answered the question

    async def test_flag_off_never_consults_the_evaluator(self, monkeypatch):
        calls: list = []
        await self._run(_double(spend_on=False), monkeypatch, calls)
        assert calls == [], (
            "forecast_spending_enabled=False must gate the spend evaluator "
            "entirely — the branch's merge justification"
        )

    async def test_flag_on_reaches_it_with_the_evidence(self, monkeypatch):
        calls: list = []
        await self._run(_double(spend_on=True), monkeypatch, calls)
        assert calls, (
            "the discriminator: the same double with the flag ON must reach "
            "the evaluator, or the OFF case above proves nothing"
        )
        assert calls[0].get("spendable_kwh") == 4.2, (
            "the planning evidence must arrive at the evaluator unmangled"
        )
