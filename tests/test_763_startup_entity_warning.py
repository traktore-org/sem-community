"""#763 beta.7 — the "entities missing, commands will no-op" warning must
not fire during HA's warm-up.

SEM's setup runs before many upstream integrations have loaded their
entities. The registration-time check saw ``switch.wb_einfahrt_
ladefreigabe`` absent, warned that commands would silently no-op — and
the entity existed minutes later (the reporter verified it manually).
The warning sent the diagnosis down a dead end. The check now runs
DEFERRED (after warm-up) via a testable helper: still-missing entities
warn exactly as before; entities that appeared in the meantime log the
recovery at DEBUG and nothing else.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management import (
    _warn_missing_charger_entities,
)


def _hass(existing):
    return SimpleNamespace(
        states=SimpleNamespace(
            get=lambda eid: object() if eid in existing else None,
        ),
    )


@pytest.mark.unit
class TestDeferredEntityWarning:

    def test_still_missing_entities_warn(self, caplog):
        to_check = [("ev_start_stop_entity", "switch.gone")]
        with caplog.at_level(logging.WARNING):
            missing = _warn_missing_charger_entities(
                _hass(set()), "EV Charger", "ev_charger", to_check)
        assert missing == [("ev_start_stop_entity", "switch.gone")]
        assert "switch.gone" in caplog.text
        assert "silently no-op" in caplog.text

    def test_entities_present_after_warmup_do_not_warn(self, caplog):
        # The reporter's exact case: the switch exists by the time anyone
        # can act on a warning — so no warning.
        to_check = [
            ("ev_start_stop_entity", "switch.wb_einfahrt_ladefreigabe"),
            ("ev_current_control_entity", "number.wb_einfahrt_ladestrom"),
        ]
        with caplog.at_level(logging.WARNING):
            missing = _warn_missing_charger_entities(
                _hass({"switch.wb_einfahrt_ladefreigabe",
                       "number.wb_einfahrt_ladestrom"}),
                "EV Charger", "ev_charger", to_check)
        assert missing == []
        assert "silently no-op" not in caplog.text

    def test_unconfigured_entries_are_skipped(self, caplog):
        with caplog.at_level(logging.WARNING):
            missing = _warn_missing_charger_entities(
                _hass(set()), "EV Charger", "ev_charger",
                [("ev_charge_mode_entity", None),
                 ("ev_start_stop_entity", "")])
        assert missing == []
        assert "silently no-op" not in caplog.text
