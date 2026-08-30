"""#873 — run ``async_initialize_energy_dashboard``, don't just reach it.

152 lines that decide where every reading comes from: whether SEM reads the
HA Energy Dashboard or falls back to explicitly configured sensors, which
counters reconcile daily energy, and whether the cold-start retry stays armed
because a source integration had not registered its entities yet (#274).

Nothing ran it. It is *statically* reachable from
``_retry_energy_dashboard_resolution``, which is precisely why a call-graph
measurement is the wrong instrument here: reachable and never executed look
identical on a call graph, and only one of them is coverage. An instrumented
cycle shows this method never runs (see the ratchet).

The branches that matter are the ones that decide behaviour silently: a
dashboard that is present but incomplete, and a reader that throws. Both fall
through to "no dashboard", and from there SEM reads a different set of
sensors for the rest of its life without anything failing loudly.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator import (
    coordinator as coordinator_module,
)

from .test_873_cycle_executes import _hass


def _coordinator(config=None):
    coord = coordinator_module.SEMCoordinator(_hass(), dict(config or {}))
    coord.config_entry = None
    return coord


def _dashboard(*, minimal=True, incomplete=False):
    """A stand-in for EnergyDashboardConfig carrying only what the method
    touches — named attributes, so a rename breaks this test rather than
    silently returning a MagicMock that passes everything."""
    return SimpleNamespace(
        is_minimally_configured=lambda: minimal,
        power_resolution_incomplete=lambda: incomplete,
        solar_power="sensor.ed_solar",
        grid_import_power="sensor.ed_grid_in",
        battery_power="sensor.ed_batt",
        ev_power="sensor.ed_ev",
        solar_energy="sensor.ed_solar_kwh", solar_energy_list=[],
        grid_import_energy="sensor.ed_import_kwh", grid_import_energy_list=[],
        grid_export_energy="sensor.ed_export_kwh", grid_export_energy_list=[],
        battery_charge_energy="sensor.ed_chg_kwh", battery_charge_energy_list=[],
        battery_discharge_energy="sensor.ed_dis_kwh", battery_discharge_energy_list=[],
    )


def _patched(result=None, raises=None):
    """Patch the dashboard reader, plus the PV-string discovery helpers at
    their SOURCE module — the coordinator imports those inside the function
    body, so there is no module-level name to patch on the coordinator."""
    reader = AsyncMock(side_effect=raises) if raises else AsyncMock(return_value=result)
    from custom_components.solar_energy_management import hardware_detection
    return (
        patch.object(coordinator_module, "read_energy_dashboard_config", reader),
        patch.object(hardware_detection, "discover_pv_strings_from_registry",
                     MagicMock(return_value={})),
        patch.object(hardware_detection, "discover_pv_string_vi_pairs",
                     MagicMock(return_value={})),
    )


async def _run(coord, **kw):
    a, b, c = _patched(**kw)
    with a, b, c:
        return await coord.async_initialize_energy_dashboard()


class TestTheDashboardIsAdopted:
    @pytest.mark.asyncio
    async def test_a_configured_dashboard_is_used(self):
        coord = _coordinator()
        assert await _run(coord, result=_dashboard()) is True
        assert coord._energy_dashboard_config is not None

    @pytest.mark.asyncio
    async def test_the_sensor_reader_is_told(self):
        """Adopting the dashboard without handing it to the reader would
        leave every reading on the legacy path — all zeros — while the
        method reported success."""
        coord = _coordinator()
        coord._sensor_reader.set_energy_dashboard_config = MagicMock()
        await _run(coord, result=_dashboard())
        coord._sensor_reader.set_energy_dashboard_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_the_cold_start_retry_stays_armed_while_power_is_unresolved(self):
        """#274: an energy sensor whose real-time power sibling could not be
        derived yet — the source integration had not registered its entities.
        The flag is what keeps SEM re-deriving instead of running blind."""
        coord = _coordinator()
        await _run(coord, result=_dashboard(incomplete=True))
        assert coord._ed_resolve_pending is True

    @pytest.mark.asyncio
    async def test_a_fully_resolved_dashboard_disarms_the_retry(self):
        coord = _coordinator()
        await _run(coord, result=_dashboard(incomplete=False))
        assert coord._ed_resolve_pending is False


class TestTheQuietPathsThatChangeEverything:
    """Both of these leave SEM reading a different set of sensors for the
    rest of its life, and neither fails loudly."""

    @pytest.mark.asyncio
    async def test_no_dashboard_means_no_adoption(self):
        coord = _coordinator()
        assert await _run(coord, result=None) is False
        assert not coord._energy_dashboard_config

    @pytest.mark.asyncio
    async def test_an_incomplete_dashboard_is_not_adopted(self):
        coord = _coordinator()
        assert await _run(coord, result=_dashboard(minimal=False)) is False

    @pytest.mark.asyncio
    async def test_a_throwing_reader_is_survived(self):
        """A broken Energy Dashboard must not take the integration down —
        it must degrade to the configured sensors."""
        coord = _coordinator()
        assert await _run(coord, raises=RuntimeError("energy prefs unreadable")) is False

    @pytest.mark.asyncio
    async def test_the_manual_counter_takes_over_when_there_is_no_dashboard(self):
        """#556: without a dashboard, daily-solar reconciliation falls back
        to the explicitly configured counter — otherwise the fallback path
        silently reconciles against nothing."""
        coord = _coordinator({"solar_energy_sensor": "sensor.my_inverter_total"})
        coord._energy_calculator.configure_solar_counters = MagicMock()
        await _run(coord, result=None)
        coord._energy_calculator.configure_solar_counters.assert_called_once()
        assert (coord._energy_calculator.configure_solar_counters
                .call_args.args[1] == ["sensor.my_inverter_total"])

    @pytest.mark.asyncio
    async def test_ev_counters_are_configured_on_every_path(self):
        """The EV reconciliation sits AFTER the try/except, so it must run
        even when the dashboard read blew up (#658)."""
        for kw in ({"result": _dashboard()}, {"result": None},
                   {"raises": RuntimeError("boom")}):
            coord = _coordinator()
            coord._energy_calculator.configure_ev_counters = MagicMock()
            await _run(coord, **kw)
            coord._energy_calculator.configure_ev_counters.assert_called_once(), kw
