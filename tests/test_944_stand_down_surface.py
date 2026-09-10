"""#944 — the stop-war ceasefire stood down in silence while the car kept charging.

PROD 10.09.2026: the KEBA auto-restarted itself every ~10 minutes. SEM stopped
it again and again, every stop taking within seconds; then the #763 ceasefire
stood down — correctly, so the car is not strobed into a charging fault — and
said so with one ``_LOGGER.warning``. Then nothing: the car drew from the house
battery and the grid from 18:29 to 19:49, and the owner found out from the
battery.

A log line is not a surface (#799). While SEM holds fire AND the box draws: a
Repair of its own, one charger notification, the state on the card — all gone
the moment the draw stops or the war ends; once per onset, never per cycle.
And the class guard: no ``REPORT_*`` action may reach only the log.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator import repair_issues as ri
from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    STOP_WAR_BACKOFF_S,
    Action,
    ActionKind,
    ChargerReconciler,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
    ChargerPower,
)
from custom_components.solar_energy_management.coordinator.notifications import (
    NotificationManager,
)

_ROOT = Path(__file__).resolve().parent.parent
_CID = "keba"
_DRAW_W = 4100.0
_RECONCILER_LOGGER = (
    "custom_components.solar_energy_management.coordinator.charger_reconciler")


class _Box:
    """A wallbox whose every stop takes, and which restarts itself anyway."""

    def __init__(self, *, observer: bool = False):
        self.notifier = SimpleNamespace(notify_charger_stand_down=AsyncMock())
        dev = SimpleNamespace(
            name="KEBA P30", hass=MagicMock(), _current_setpoint=0,
            can_stop_charging=lambda: True, contactor_surface=False,
            observer_mode=observer,
            _coordinator=SimpleNamespace(_notification_manager=self.notifier),
        )
        a = MagicMock()
        a._device = dev
        a.actual_charging = MagicMock(side_effect=lambda p: p.power_w > 500)
        a.is_self_charging = MagicMock(return_value=False)
        a.enable_state = MagicMock(return_value=(None, True))
        a.max_current_a = 16
        for m in ("command_disable", "command_current", "arm_failsafe",
                  "ensure_enabled", "command_park_off"):
            setattr(a, m, AsyncMock())
        self.adapter = a


def _decision(intent=ChargerIntent.IDLE, amps=0):
    return ChargerDecision(charger_id=_CID, mode="solar_only", intent=intent,
                           commanded_amps=amps, reason="test")


async def _cycle(rec, box, t, *, w=0.0, connected=True,
                 intent=ChargerIntent.IDLE, amps=0):
    await rec.reconcile_and_apply(
        _decision(intent, amps), box.adapter,
        ChargerPower(charger_id=_CID, power_w=w, connected=connected,
                     charging=w > 500),
        now=t)


async def _to_ceasefire(rec, box):
    """Settle, then three stop→redraw rounds the box wins; its fourth
    restart at t=270 finds SEM standing down with the car drawing."""
    await _cycle(rec, box, 0.0)
    for t in (10.0, 110.0, 210.0):
        await _cycle(rec, box, t, w=_DRAW_W)    # the box restarted → DISABLE
        await _cycle(rec, box, t + 5, w=0.0)    # …and the stop took
    await _cycle(rec, box, 270.0, w=_DRAW_W)    # restart #4 → stand down


@pytest.fixture
def repairs(monkeypatch):
    calls = {"raise": [], "clear": []}
    monkeypatch.setattr(
        ri, "raise_charger_stop_war_stand_down",
        lambda hass, device_id, **kw: calls["raise"].append((device_id, kw)))
    monkeypatch.setattr(
        ri, "clear_charger_stop_war_stand_down",
        lambda hass, device_id: calls["clear"].append(device_id))
    monkeypatch.setattr(ri, "clear_charger_stop_unenforceable",
                        lambda hass, device_id: None)
    return calls


@pytest.mark.unit
class TestTheStandDownIsSeen:
    @pytest.mark.asyncio
    async def test_the_stand_down_raises_all_three_once(self, repairs):
        rec, box = ChargerReconciler(charger_id=_CID, heartbeat_s=5.0), _Box()
        await _to_ceasefire(rec, box)
        for t in range(280, 580, 10):          # the car keeps drawing
            await _cycle(rec, box, float(t), w=_DRAW_W)

        assert box.adapter.command_disable.await_count == 3, (
            "the ceasefire itself must not change — fighting harder is out "
            "of scope")
        assert len(repairs["raise"]) == 1, "once per onset, not per cycle"
        device_id, kw = repairs["raise"][0]
        assert device_id == _CID
        assert kw["name"] == "KEBA P30"
        assert kw["power_w"] == pytest.approx(_DRAW_W)
        assert kw["minutes"] == pytest.approx(STOP_WAR_BACKOFF_S / 60.0)

        box.notifier.notify_charger_stand_down.assert_awaited_once()
        n = box.notifier.notify_charger_stand_down.await_args.kwargs
        assert n["charger_id"] == _CID
        assert n["power_w"] == pytest.approx(_DRAW_W)

        snap = rec.stand_down_snapshot(570.0)
        assert snap["standing_down"] is True
        assert snap["power_w"] == 4100
        assert snap["remaining_s"] == pytest.approx(
            270.0 + STOP_WAR_BACKOFF_S - 570.0)
        assert rec.snapshot_war(570.0)["stand_down"] == snap
        assert repairs["clear"] == [_CID], (
            "only the boot-time clear — never one mid-stand-down")

    @pytest.mark.asyncio
    async def test_a_pause_clears_and_a_resume_does_not_push_again(self, repairs):
        rec, box = ChargerReconciler(charger_id=_CID, heartbeat_s=5.0), _Box()
        await _to_ceasefire(rec, box)
        await _cycle(rec, box, 400.0, w=_DRAW_W)
        repairs["clear"].clear()

        await _cycle(rec, box, 410.0, w=0.0)            # the car paused
        assert repairs["clear"] == [_CID]
        assert rec.stand_down_snapshot(410.0)["standing_down"] is False

        await _cycle(rec, box, 500.0, w=_DRAW_W)        # …and resumed, in the window
        assert len(repairs["raise"]) == 2, "the Repair follows the draw"
        box.notifier.notify_charger_stand_down.assert_awaited_once()
        assert rec.stand_down_snapshot(500.0)["standing_down"] is True
        assert box.adapter.command_disable.await_count == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "ending", ["sem_wants_charge", "car_unplugged", "window_closed"])
    async def test_every_end_of_the_war_takes_the_surfaces_down(
            self, repairs, ending):
        rec, box = ChargerReconciler(charger_id=_CID, heartbeat_s=5.0), _Box()
        await _to_ceasefire(rec, box)
        repairs["clear"].clear()
        if ending == "sem_wants_charge":
            t = 300.0
            await _cycle(rec, box, t, w=_DRAW_W,
                         intent=ChargerIntent.CHARGE_AT_AMPS, amps=10)
        elif ending == "car_unplugged":
            t = 300.0
            await _cycle(rec, box, t, w=0.0, connected=False)
        else:
            t = 270.0 + STOP_WAR_BACKOFF_S + 1.0
            await _cycle(rec, box, t, w=_DRAW_W)         # SEM stops it again
            assert box.adapter.command_disable.await_count == 4
        assert repairs["clear"] == [_CID]
        assert rec.stand_down_snapshot(t)["standing_down"] is False

    @pytest.mark.asyncio
    async def test_a_second_ceasefire_announces_its_real_length(
            self, repairs, caplog):
        rec, box = ChargerReconciler(charger_id=_CID, heartbeat_s=5.0), _Box()
        await _to_ceasefire(rec, box)
        t = 270.0 + STOP_WAR_BACKOFF_S + 1.0
        await _cycle(rec, box, t, w=_DRAW_W)            # probe
        await _cycle(rec, box, t + 10, w=0.0)           # it took
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=_RECONCILER_LOGGER):
            await _cycle(rec, box, t + 100, w=_DRAW_W)  # back: ceasefire 2
        msgs = [r.getMessage() for r in caplog.records]
        assert any("Standing down for 60 min" in m for m in msgs), msgs
        assert repairs["raise"][-1][1]["minutes"] == pytest.approx(
            2 * STOP_WAR_BACKOFF_S / 60.0)
        assert box.notifier.notify_charger_stand_down.await_count == 2, (
            "a new stand-down is a new onset")

    @pytest.mark.asyncio
    async def test_an_observer_rig_leaves_the_box_display_alone(self, repairs):
        """An observer may share the physical box (#855): its display is
        somebody else's, and "SEM stood down" there would be a lie told by
        an instance that commands nothing. Its own Repair is its own."""
        rec, box = ChargerReconciler(charger_id=_CID, heartbeat_s=5.0), _Box(
            observer=True)
        await _to_ceasefire(rec, box)
        assert len(repairs["raise"]) == 1
        box.notifier.notify_charger_stand_down.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_rebuilt_reconciler_clears_a_leftover_repair_exactly_once(
            self, repairs):
        """An options reload rebuilds the reconciler mid-stand-down; the old
        one's Repair must not outlive it — and a quiet charger must not pay a
        registry write every cycle for the privilege."""
        rec, box = ChargerReconciler(charger_id=_CID, heartbeat_s=5.0), _Box()
        for t in (0.0, 10.0, 20.0, 30.0):
            await _cycle(rec, box, t)
        assert repairs["clear"] == [_CID]
        assert repairs["raise"] == []

    @pytest.mark.asyncio
    async def test_no_coordinator_link_still_files_the_repair(self, repairs):
        rec, box = ChargerReconciler(charger_id=_CID, heartbeat_s=5.0), _Box()
        box.adapter._device._coordinator = None
        await _to_ceasefire(rec, box)
        assert len(repairs["raise"]) == 1


def _nm(**config):
    hass = MagicMock()
    hass.config.language = "en"
    nm = NotificationManager(hass, config)
    nm._send_charger_notification = AsyncMock()
    return nm, hass


async def _notify(nm):
    await nm.notify_charger_stand_down(
        charger_id=_CID, charger_name="KEBA P30", power_w=_DRAW_W,
        minutes=30.0)


@pytest.mark.unit
class TestTheChargerNotification:
    @pytest.mark.asyncio
    async def test_it_goes_through_the_existing_charger_path(self):
        nm, hass = _nm(enable_charger_notifications=True)
        await _notify(nm)
        nm._send_charger_notification.assert_awaited_once_with("SEM stood down")
        name, payload = hass.bus.async_fire.call_args.args
        assert name.endswith("_notification")
        assert payload["event"] == "charger_stop_war_stand_down"
        assert payload["charger_id"] == _CID
        assert payload["power_w"] == 4100

    @pytest.mark.asyncio
    async def test_the_users_switch_is_honoured(self):
        nm, hass = _nm(enable_charger_notifications=False)
        await _notify(nm)
        nm._send_charger_notification.assert_not_awaited()
        hass.bus.async_fire.assert_called_once()   # automations still hear it

    @pytest.mark.asyncio
    async def test_zero_config_default_is_on(self):
        nm, _ = _nm()
        await _notify(nm)
        nm._send_charger_notification.assert_awaited_once()


@pytest.mark.unit
class TestTheRepair:
    def test_it_is_its_own_non_persistent_warning(self):
        with patch.object(ri.ir, "async_create_issue") as create:
            ri.raise_charger_stop_war_stand_down(
                MagicMock(), _CID, name="KEBA P30", power_w=4100.0,
                minutes=29.6)
        kw = create.call_args.kwargs
        assert kw["translation_key"] == "charger_stop_war_stand_down"
        assert kw["issue_id"] == f"charger_stop_war_stand_down_{_CID}"
        assert kw["is_persistent"] is False, (
            "the ceasefire lives in memory; a restart forgets it")
        assert kw["is_fixable"] is False
        assert kw["translation_placeholders"] == {
            "name": "KEBA P30", "power": "4100", "minutes": "30"}
        assert kw["learn_more_url"].endswith(
            "TROUBLESHOOTING.md#sem-stood-down-while-the-charger-kept-charging")

    def test_clear_deletes_the_same_id(self):
        with patch.object(ri.ir, "async_delete_issue") as delete:
            ri.clear_charger_stop_war_stand_down(MagicMock(), _CID)
        assert delete.call_args.args[2] == f"charger_stop_war_stand_down_{_CID}"

    def test_a_registry_failure_never_costs_the_cycle(self):
        with patch.object(ri.ir, "async_create_issue",
                          side_effect=RuntimeError("boom")):
            ri.raise_charger_stop_war_stand_down(
                MagicMock(), _CID, name="x", power_w=1.0, minutes=1.0)
        with patch.object(ri.ir, "async_delete_issue",
                          side_effect=RuntimeError("boom")):
            ri.clear_charger_stop_war_stand_down(MagicMock(), _CID)

    def test_the_text_names_both_causes_and_not_the_627_story(self):
        issues = json.loads((_ROOT / "translations" / "en.json").read_text(
            encoding="utf-8"))["issues"]
        raw = issues["charger_stop_war_stand_down"]["description"]
        text = raw.lower()
        assert "auto-start" in text
        assert "another controller" in text
        assert "{name}" in raw and "{power}" in raw and "{minutes}" in raw
        # #627's story is that no mechanism is configured — false here.
        assert "no configured mechanism" not in text
        assert raw != issues["charger_stop_unenforceable"]["fix_flow"]["step"][
            "confirm"]["description"]


@pytest.mark.unit
class TestTheCardCanSeeIt:
    def test_the_charging_state_sensor_publishes_it_per_charger(self):
        from custom_components.solar_energy_management.sensor import (
            SEMSolarSensor,
        )
        me = MagicMock()
        me.entity_description.key = "charging_state"
        me.coordinator.data = {
            "charger_keba_stop_war_stand_down": True,
            "charger_keba_stop_war_stand_down_s": 1470.0,
            "charger_keba_stop_war_stand_down_w": 4100.0,
            "charger_garage_stop_war_stand_down": False,
            "charger_garage_stop_war_stand_down_s": 0.0,
            "charger_garage_stop_war_stand_down_w": 0.0,
        }
        attrs = SEMSolarSensor._extra_state_attributes_base(me)
        assert attrs["per_charger_stop_war"] == {
            "keba": {"standing_down": True, "remaining_s": 1470.0,
                     "power_w": 4100.0},
            "garage": {"standing_down": False, "remaining_s": 0.0,
                       "power_w": 0.0},
        }

    def test_the_coordinator_writes_the_keys_the_sensor_reads(self):
        """Class 22: a string-keyed store whose write site and read site
        disagree is silent. The coordinator is too large to drive for one
        key, so its PARSED tree (not its spelling, #925) is held to calling
        the snapshot and to writing the suffixes the sensor above reads."""
        import ast

        from .ast_contracts import call_sites

        assert any(path == "coordinator/coordinator.py"
                   for path, _line, _kw in call_sites("stand_down_snapshot")), (
            "nothing publishes the stand-down — the card would never see it")
        tree = ast.parse((_ROOT / "coordinator" / "coordinator.py")
                         .read_text(encoding="utf-8"))
        written = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for t in node.targets:
                if not (isinstance(t, ast.Subscript)
                        and isinstance(t.value, ast.Name)
                        and t.value.id == "result"
                        and isinstance(t.slice, ast.JoinedStr)):
                    continue
                parts = t.slice.values
                if (len(parts) == 3 and isinstance(parts[0], ast.Constant)
                        and parts[0].value == "charger_"
                        and isinstance(parts[2], ast.Constant)):
                    written.add(parts[2].value)
        # Vacuity (class 8): the walker must see a known sibling first.
        assert "_anticycle_hold" in written, sorted(written)[:10]
        assert {"_stop_war_stand_down", "_stop_war_stand_down_s",
                "_stop_war_stand_down_w"} <= written

    def test_the_countdown_is_live_context_not_history(self):
        from custom_components.solar_energy_management.sensor import (
            SEMSolarSensor,
        )
        assert "per_charger_stop_war" in SEMSolarSensor._unrecorded_attributes

    def test_the_card_has_the_words_in_every_language(self):
        tables = json.loads((_ROOT / "dashboard" / "translations.json")
                            .read_text(encoding="utf-8"))
        for lang, table in tables.items():
            for key in ("charger_status_stood_down", "notif_charger_stood_down"):
                assert table.get(key, "").strip(), f"{lang}.{key}"


# ── The class guard: no REPORT_* reaches only the log ──────────────────────

_REPORT_KINDS = [k for k in ActionKind if k.name.startswith("REPORT_")]
_HOOKS = ("report_enable_blocked", "report_failsafe_suspected")


def _surfaces(kind, rec=None) -> set:
    """Drive the REAL action loop with one report and name the non-log
    surfaces it touched: an issue-registry write, or an adapter report hook
    (the adapter's own Repair path)."""
    rec = rec or ChargerReconciler(charger_id=_CID, heartbeat_s=5.0)
    box = _Box()
    for hook in _HOOKS:
        setattr(box.adapter, hook, AsyncMock())
    touched: set = set()
    with patch.object(ri.ir, "async_create_issue",
                      side_effect=lambda *a, **k: touched.add("repair")), \
            patch.object(ri.ir, "async_delete_issue"):
        asyncio.run(rec._apply_actions(
            [Action(kind, interval_s=600.0)], box.adapter,
            SimpleNamespace(reason="guard"), SimpleNamespace(power_w=_DRAW_W),
            now=1.0))
    touched.update(h for h in _HOOKS if getattr(box.adapter, h).await_count)
    return touched


@pytest.mark.unit
class TestEveryReportReachesASurface:
    """Bug class 82. A ``REPORT_*`` action is SEM telling the user it cannot
    or will not do what it was asked. Reaching only the log is how #944
    stood down in silence; a new report that does the same fails here,
    whatever it is called."""

    def test_the_enumeration_sees_the_reports(self):
        names = {k.name for k in _REPORT_KINDS}
        assert {"REPORT_STOP_WAR", "REPORT_STOP_UNENFORCEABLE",
                "REPORT_ENABLE_BLOCKED", "REPORT_FAILSAFE_SUSPECTED"} <= names

    @pytest.mark.parametrize("kind", _REPORT_KINDS, ids=lambda k: k.name)
    def test_every_report_reaches_a_surface_beyond_the_log(self, kind):
        assert _surfaces(kind), (
            f"{kind.name} reaches only the log — a log line is not a surface "
            "(#799, #944). Raise a Repair or call an adapter report hook.")

    def test_the_oracle_fires_on_a_log_only_report(self):
        """Vacuity twin (class 8): strip #944's surface and the stop war is
        back to a log line — the oracle must say so."""
        rec = ChargerReconciler(charger_id=_CID, heartbeat_s=5.0)
        rec._surface_stand_down = AsyncMock()
        assert _surfaces(ActionKind.REPORT_STOP_WAR, rec) == set()
