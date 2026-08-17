"""#700 — two charger follow-ups from @jappish84's #628 testing.

1. The STOP-unenforceable warning (#627) fired every reconcile cycle while
   the condition persisted — 8000+ entries on a real install, crowding out
   the entire log history. It must warn once per ONSET, drop repeats to
   debug, and re-arm when any enforceable action lands.

2. The ED duplicate-row suppression for a configured charger required the
   row's ``is_ev`` flag — an English-only name-pattern guess. A Swedish
   "Billaddare" row for the configured Garo matched nothing and Load
   Management showed the charger twice. Suppression now tests IDENTITY:
   entity match or shared HA registry device with a charger's power entity.
"""
import logging
from unittest.mock import MagicMock


from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)


# ── 1. warning rate limit ─────────────────────────────────────────────────

class _Reconciler:
    """Bare instance carrying only what the action loop reads."""
    def __new__(cls):
        from custom_components.solar_energy_management.coordinator.charger_reconciler import (
            ChargerReconciler,
        )
        return ChargerReconciler.__new__(ChargerReconciler)



def _kinds():
    from custom_components.solar_energy_management.coordinator.charger_reconciler import (
        ActionKind,
    )
    return ActionKind


class TestStopUnenforceableRateLimit:
    def _mk(self):
        rec = _Reconciler()
        rec.charger_id = "garo"
        return rec

    def test_warns_once_then_debug(self, caplog):
        from custom_components.solar_energy_management.coordinator import (
            charger_reconciler as cr,
        )
        rec = self._mk()
        with caplog.at_level(logging.DEBUG, logger=cr._LOGGER.name):
            for _ in range(5):
                self._fire_unenforceable(rec)
        warnings = [r for r in caplog.records
                    if r.levelno == logging.WARNING
                    and "unenforceable" in r.message]
        assert len(warnings) == 1, (
            f"{len(warnings)} WARNING entries for one persistent episode — "
            "the 8000-entry log flood class"
        )
        debugs = [r for r in caplog.records
                  if r.levelno == logging.DEBUG
                  and "still unenforceable" in r.message]
        assert len(debugs) == 4

    def test_rearms_after_an_enforceable_action(self, caplog):
        from custom_components.solar_energy_management.coordinator import (
            charger_reconciler as cr,
        )
        rec = self._mk()
        with caplog.at_level(logging.DEBUG, logger=cr._LOGGER.name):
            self._fire_unenforceable(rec)
            self._fire_disable(rec)          # a stop mechanism appeared
            self._fire_unenforceable(rec)    # NEW episode
        warnings = [r for r in caplog.records
                    if r.levelno == logging.WARNING
                    and "unenforceable" in r.message]
        assert len(warnings) == 2

    # -- helpers driving the real action loop --

    def _fire_unenforceable(self, rec):
        self._fire(rec, self._action(_kinds().REPORT_STOP_UNENFORCEABLE))

    def _fire_disable(self, rec):
        self._fire(rec, self._action(_kinds().DISABLE))

    @staticmethod
    def _action(kind, amps=0):
        from types import SimpleNamespace
        return SimpleNamespace(kind=kind, amps=amps)

    @staticmethod
    def _fire(rec, action):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        adapter = MagicMock()
        adapter.ensure_enabled = AsyncMock()
        adapter.command_disable = AsyncMock()
        adapter.command_current = AsyncMock()
        adapter.arm_failsafe = AsyncMock()
        rec._report_stop_unenforceable = MagicMock()
        decision = SimpleNamespace(reason="test")
        power = SimpleNamespace(power_w=3900.0)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                rec._apply_actions([action], adapter, decision, power))
        finally:
            loop.close()


# ── 2. identity-based ED-row suppression ─────────────────────────────────

class TestEdChargerRowIdentitySuppression:
    def _reg(self, monkeypatch, *, charger_power="sensor.garo_laddbox_charging_power",
             registry_map=None):
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg.hass = MagicMock()
        reg._ev_charger_rows = [{"id": "c1", "power_entity": charger_power}]
        if registry_map is not None:
            class _Ent:
                def __init__(self, device_id):
                    self.device_id = device_id

            class _Reg:
                def async_get(self, eid):
                    did = registry_map.get(eid)
                    return _Ent(did) if did else None

            import homeassistant.helpers.entity_registry as er
            monkeypatch.setattr(er, "async_get", lambda hass: _Reg())
        return reg

    def test_entity_match_suppresses_regardless_of_is_ev(self, monkeypatch):
        reg = self._reg(monkeypatch)
        # "Billaddare": is_ev False (Swedish name), but its stat_rate IS the
        # charger's power sensor
        dev = MagicMock()
        dev.power_sensor = "sensor.garo_laddbox_charging_power"
        dev.energy_sensor = "sensor.garo_laddbox_total_energy_kwh"
        assert dev.power_sensor in reg._configured_charger_entities()

    def test_registry_device_match(self, monkeypatch):
        reg = self._reg(monkeypatch, registry_map={
            "sensor.garo_laddbox_charging_power": "garo_dev",
            "sensor.garo_laddbox_total_energy_kwh": "garo_dev",
        })
        assert reg._same_registry_device_as_charger(
            "sensor.garo_laddbox_total_energy_kwh") is True

    def test_different_device_is_not_suppressed(self, monkeypatch):
        reg = self._reg(monkeypatch, registry_map={
            "sensor.garo_laddbox_charging_power": "garo_dev",
            "sensor.dishwasher_energy": "dishwasher_dev",
        })
        assert reg._same_registry_device_as_charger(
            "sensor.dishwasher_energy") is False

    def test_unanswerable_registry_is_no_match(self, monkeypatch):
        reg = self._reg(monkeypatch, registry_map={})
        assert reg._same_registry_device_as_charger("sensor.anything") is False
        assert reg._same_registry_device_as_charger(None) is False
