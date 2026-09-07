"""(#930) A stored ``allow_arbitrage`` mode becomes the explicit permission
it always meant — once, on disk — so the master switches apply to it.

The mode left the selector in v1.7.3 and ``migrate_mode()`` has read it as
``auto`` + ``may_export=True`` ever since, but only ephemerally: the stored
value never went away, and ``battery_modes.arbitrage_allowed_for_mode``
short-circuits it past BOTH master switches. A battery still carrying it
kept selling under a switch that read "off" (found by the ruflo audit of
arbitrage mode, 08.09).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.solar_energy_management import (
    _migrate_legacy_arbitrage_mode,
)


def _run(data: dict, options: dict):
    hass = MagicMock()
    entry = SimpleNamespace(data=dict(data), options=dict(options))
    _migrate_legacy_arbitrage_mode(hass, entry)
    calls = hass.config_entries.async_update_entry.call_args_list
    written = calls[-1].kwargs["options"] if calls else None
    return written, len(calls)


class TestTheLegacyModeIsWrittenDown:

    def test_global_mode_becomes_auto_plus_the_permission(self):
        w, n = _run({}, {"battery_mode": "allow_arbitrage"})
        assert n == 1
        assert w["battery_mode"] == "auto"
        assert w["battery_permissions"]["may_export"] is True

    def test_a_value_living_only_in_data_is_overridden_from_options(self):
        """entry.data is read-only; options win the merge, so the fix is
        written there."""
        w, n = _run({"battery_mode": "allow_arbitrage"}, {})
        assert n == 1 and w["battery_mode"] == "auto"

    def test_per_battery_list_is_rewritten_entry_by_entry(self):
        w, n = _run({}, {"battery_modes": ["allow_arbitrage", "self_consumption"]})
        assert n == 1
        assert w["battery_modes"] == ["auto", "self_consumption"]
        assert w["battery_permissions"]["may_export"] is True

    def test_a_revocation_is_never_overwritten(self):
        """An explicit False is the user's word; the migration must not turn
        it back into a sell."""
        w, _ = _run({}, {"battery_mode": "allow_arbitrage",
                         "battery_permissions": {"may_export": False}})
        assert w["battery_permissions"]["may_export"] is False
        assert w["battery_mode"] == "auto"


class TestItIsOneShotAndNarrow:

    def test_no_legacy_value_no_write(self):
        for opts in ({}, {"battery_mode": "auto"},
                     {"battery_mode": "self_consumption"},
                     {"battery_modes": ["auto", "self_consumption"]}):
            _, n = _run({}, opts)
            assert n == 0, opts

    def test_idempotent_on_the_second_start(self):
        w, _ = _run({}, {"battery_mode": "allow_arbitrage"})
        _, n2 = _run({}, w)
        assert n2 == 0

    def test_self_consumption_keeps_its_own_promise_untouched(self):
        """Its legacy meaning ('never sell') is honoured by effective_permissions;
        this migration is only about the retired sell mode."""
        _, n = _run({}, {"battery_mode": "self_consumption"})
        assert n == 0
