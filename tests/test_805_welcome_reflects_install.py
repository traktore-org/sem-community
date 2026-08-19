"""#805 fix 2 — the welcome must describe THIS install.

The first-run notification told everyone to "pick an EV charge mode on the
EV tab". But #595 deliberately removes the EV tab when no charger is
configured, so for a user who owns a wallbox but has not told SEM about it —
exactly the #803 reporter — the instruction pointed at a tab that is not
there. His reasonable conclusion was that the controls were missing, and he
uninstalled.

A checklist that names absent things teaches people the software is broken.
So each line is either an instruction about something present, or an
invitation to add what is missing — never a pointer into a void.
"""
from __future__ import annotations

from custom_components.solar_energy_management import build_welcome_message


class TestTheChecklistMatchesReality:

    def test_no_charger_invites_instead_of_pointing_at_a_missing_tab(self):
        msg = build_welcome_message({})
        assert "EV tab" not in msg, (
            "#595 removes the EV tab without a charger — naming it here is "
            "the #803 dead end"
        )
        assert "Add your EV charger" in msg or "add your EV charger" in msg
        assert "Configure" in msg

    def test_a_configured_charger_gets_the_real_instruction(self):
        msg = build_welcome_message({"ev_chargers": [{"name": "Wallbox"}]})
        assert "EV tab" in msg
        assert "charge mode" in msg.lower()

    def test_the_legacy_single_charger_key_counts_too(self):
        msg = build_welcome_message({"ev_charging_power_sensor": "sensor.wb"})
        assert "EV tab" in msg

    def test_no_battery_does_not_send_you_to_a_battery_tab(self):
        msg = build_welcome_message({})
        assert "Battery tab" not in msg

    def test_a_battery_install_gets_its_reserve_line(self):
        msg = build_welcome_message({"battery_capacity_kwh": 10})
        assert "Battery tab" in msg
        assert "reserve" in msg.lower()

    def test_the_dashboard_link_is_always_there(self):
        for cfg in ({}, {"battery_capacity_kwh": 10}):
            assert "/sem-dashboard/home" in build_welcome_message(cfg)

    def test_it_says_what_sem_will_control_before_it_controls_it(self):
        # The promise "everything else has sensible defaults" hid that SEM
        # was about to manage auto-discovered devices (#805 fix 1 made that
        # monitor-only; the welcome must still SAY so).
        msg = build_welcome_message({})
        assert "monitor" in msg.lower()
        assert "sensible defaults" not in msg.lower()
