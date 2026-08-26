"""2.1 usefulness audit (26.08) — the eight improvements, pinned.

The audit asked what an ordinary user must DO to get anything out of each
2.1 feature and what they SEE while waiting. Two findings were regressions
from the same week's build (a gate with no UI, a guard reading a key defined
nowhere); the rest were surfaces that existed only as HA entities or on
options-flow page 11-12. These tests pin the fixes so the house rule —
every setting reachable on the dashboard — cannot silently regress again.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOW = (ROOT / "config_flow.py").read_text()
CARD = (ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js").read_text()
BATT = (ROOT / "dashboard" / "card" / "src" / "cards" / "sem-battery-card.js").read_text()
STRINGS = json.loads((ROOT / "strings.json").read_text())


def _flow_declares(key: str) -> int:
    return len(re.findall(r'vol\.Optional\(\s*"' + key + '"', FLOW))


class TestItem1PhaseSwitchingHasASwitch:
    """#804: the dormancy gate had NO user interface — a 2.0 user lost the
    phase row and could not turn it back on."""

    def test_flow_declares_the_gate_on_add_and_edit(self):
        assert _flow_declares("ev_phase_switching_enabled") >= 2, (
            "ev_phase_switching_enabled must be a field on BOTH charger "
            "steps (add + edit) — it had no UI at all"
        )

    def test_card_renders_the_gate_in_the_charger_section(self):
        assert "'ev_phase_switching_enabled'" in CARD

    def test_card_renders_the_wattpilot_label_fields(self):
        for k in ("ev_charge_mode_entity", "ev_charge_mode_start", "ev_charge_mode_stop"):
            assert f"'{k}'" in CARD, f"{k} not on the Config tab"

    def test_the_gate_stays_default_off(self):
        m = re.search(r'"ev_phase_switching_enabled",\s*default=_?c?\(?[^)]*?(False|false)', FLOW)
        assert m or 'default=charger.get("ev_phase_switching_enabled", False)' in FLOW \
            or 'default=False' in FLOW.split('"ev_phase_switching_enabled"')[1][:200]


class TestItem6ClippingGuardHasAnInput:
    """#820: the guard read inverter_ac_limit_w, defined nowhere — dead code
    behind a changelog promise."""

    def test_flow_declares_the_ac_limit(self):
        assert _flow_declares("inverter_ac_limit_w") == 1

    def test_card_renders_it(self):
        assert "'inverter_ac_limit_w'" in CARD


class TestItem2BatterySectionOnTheConfigTab:
    """The four 2.1 switches were HA entities only; the pacing picker and
    the Deye export block lived on options-flow pages 11-12."""

    def test_the_four_switches_render(self):
        for ent in ("switch.sem_forecast_spending_enabled",
                    "switch.sem_battery_may_export",
                    "switch.sem_battery_may_assist_ev",
                    "switch.sem_battery_charge_pacing_enabled"):
            assert f"'{ent}'" in CARD, f"{ent} has no dashboard home"

    def test_the_pacing_picker_renders(self):
        assert "'battery_charge_power_limit_entity'" in CARD

    def test_the_deye_export_row_renders(self):
        assert "'deye_system_work_mode_control'" in CARD
        assert "'deye_system_work_mode_entity'" in CARD


class TestLabelsExistForEveryNewSurface:
    """#737's guard covers the options flow; this covers the card keys the
    new rows translate through."""

    def test_dashboard_translations_have_the_new_keys(self):
        tr = json.loads((ROOT / "dashboard" / "translations.json").read_text())
        en = tr["en"]
        for k in ("config_ev_phase_switching", "config_help_ev_phase_switching",
                  "config_inverter_ac_limit", "config_help_inverter_ac_limit",
                  "config_section_battery_intelligence",
                  "forecast_spending", "battery_may_export", "battery_may_assist_ev",
                  "battery_charge_pacing", "config_charge_power_limit_entity",
                  "config_deye_system_work_mode", "config_deye_system_work_mode_entity"):
            assert k in en, f"missing dashboard translation key {k}"


class TestItem3TheCounterfactual:
    """#778: the reason to wait, shown while waiting — last night with
    hindsight, same arithmetic as the budget with the actual drain in place
    of the forecast and no margin."""

    def test_hindsight_surplus_is_the_budget_with_actual_drain(self):
        from custom_components.solar_energy_management.coordinator.spendable_budget import (
            spendable_budget,
        )
        b = spendable_budget(soc_pct=80.0, usable_capacity_kwh=15.0,
                             overnight_need_kwh=5.0, expected_refill_kwh=1e9,
                             static_floor_pct=10.0, pessimism=1.0,
                             discharge_efficiency=1.0, refill_trusted=True)
        # stored 12.0 − drained 5.0 − floor 1.5 = 5.5 kWh were provably surplus
        assert abs(b.spendable_kwh - 5.5) < 0.01

    def test_coordinator_publishes_it(self):
        src = (ROOT / "coordinator" / "coordinator.py").read_text()
        assert '"battery_last_night_surplus_kwh"' in src
        assert 'result["battery_last_night_surplus_kwh"]' in src

    def test_card_renders_it(self):
        assert "_renderLastNightLine" in BATT and "last_night_surplus" in BATT


class TestItem4WouldBeCapAndReasonCodes:
    def test_every_guard_carries_a_code(self):
        from datetime import datetime, timedelta
        from types import SimpleNamespace
        from custom_components.solar_energy_management.coordinator.charge_pacing import (
            paced_charge_cap_w,
        )
        def led(hours, w):
            t0 = datetime(2026, 8, 26, 8, 0)
            return [SimpleNamespace(start=t0 + timedelta(hours=i), end=t0 + timedelta(hours=i + 1),
                                    hours=1.0, soc_kwh=6.0, home_batt_kwh=0.0, solar_w=float(w),
                                    cap_override_w=max(0.0, w - 800.0), grid_committed_w=0.0)
                    for i in range(hours)]
        base = dict(capacity_kwh=21.0, soc_pct=40.0, target_soc_pct=100.0, floor_soc_pct=35.0,
                    forecast_trusted=True, inverter_ac_limit_w=20000.0, hw_max_charge_w=10000.0)
        assert paced_charge_cap_w(ledger=led(8, 6800), **base).code == "paced"
        assert paced_charge_cap_w(ledger=led(8, 6800), **{**base, "soc_pct": 20.0}).code == "buffer"
        assert paced_charge_cap_w(ledger=led(8, 6800), **{**base, "forecast_trusted": False}).code == "trust"
        assert paced_charge_cap_w(ledger=led(8, 2000), **base).code == "weak_day"
        assert paced_charge_cap_w(ledger=[], **base).code == "none"

    def test_card_renders_the_would_be_cap_while_off(self):
        assert "pacing_would" in BATT and "reason_code" in BATT


class TestItem7RenderWhatIsPublished:
    def test_rate_caveat_is_rendered(self):
        assert "_renderRateCaveat" in BATT and "rate_caveat" in BATT

    def test_docs_links_follow_the_running_version(self):
        from custom_components.solar_energy_management.coordinator import repair_issues as ri
        assert "/blob/develop/" in ri.next_step_url("docs", "sensor_stale", sem_version="2.1.0-beta.3")
        assert "/blob/main/" in ri.next_step_url("docs", "sensor_stale", sem_version="2.1.0")
        keba = ri.next_step_url("docs", "keba_failsafe_active", sem_version="2.1.0")
        assert "/blob/main/docs/KEBA_FAILSAFE.md" in keba

    def test_deye_validation_failure_raises_a_repair(self):
        src = (ROOT / "coordinator" / "battery_adapters" / "deye.py").read_text()
        assert "raise_deye_system_work_mode_invalid" in src
        assert "clear_deye_system_work_mode_invalid" in src


class TestItem8BackfillButton:
    def test_button_platform_registered(self):
        assert "Platform.BUTTON" in (ROOT / "__init__.py").read_text()
        assert (ROOT / "button.py").exists()

    def test_press_calls_the_service(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from custom_components.solar_energy_management.button import BUTTONS, SEMButton
        coord = MagicMock(); coord.device_info = {}
        b = SEMButton(coord, BUTTONS[0])
        b.hass = MagicMock(); b.hass.services.async_call = AsyncMock()
        asyncio.run(b.async_press())
        call = b.hass.services.async_call.await_args
        assert call.args[0] == "solar_energy_management" and call.args[1] == "backfill_battery_nights"

    def test_service_posts_a_persistent_notification(self):
        src = (ROOT / "__init__.py").read_text()
        assert "sem_backfill_battery_nights" in src and "persistent_notification" in src


class TestItem5DetectInsteadOfAsking:
    def test_charge_limit_number_is_suggested_by_pattern(self):
        from types import SimpleNamespace
        from custom_components.solar_energy_management.config_flow import (
            _suggest_charge_limit_number,
        )
        hass = SimpleNamespace(states=SimpleNamespace(async_all=lambda d: [
            SimpleNamespace(entity_id="number.batteries_maximale_entladeleistung"),
            SimpleNamespace(entity_id="number.batteries_maximale_ladeleistung"),
        ]))
        assert _suggest_charge_limit_number(hass) == "number.batteries_maximale_ladeleistung"

    def test_deye_select_is_suggested_by_its_vocabulary(self):
        from types import SimpleNamespace
        from custom_components.solar_energy_management.config_flow import (
            _suggest_select_with_options,
        )
        hass = SimpleNamespace(states=SimpleNamespace(async_all=lambda d: [
            SimpleNamespace(entity_id="select.deye_work_mode",
                            attributes={"options": ["Load First", "Battery First"]}),
            SimpleNamespace(entity_id="select.deye_energy_pattern",
                            attributes={"options": ["Selling First", "Zero Export To Load", "Zero Export To CT"]}),
        ]))
        assert _suggest_select_with_options(
            hass, ("Selling First", "Zero Export To Load", "Zero Export To CT")) == "select.deye_energy_pattern"
