"""#1192 — a "Fix grid sign" tap made while SEM reads no grid meter.

The tap is saved with the grid source in use (#971). With no meter there is
no source, and builds since #971 saved the tap with a None source. A None
source also means "a flip from before the binding", which applies to every
auto-found meter, so the meter SEM found later read import as export. A user
whose grid reads 0 W is the one who taps the button to try to fix it.

Now a tap with no meter is bound to ``NO_GRID_SOURCE`` and applies to no
meter; a None that a newer build saved reads the same; only a store without
the key at all is a flip from before the binding. Swept: the read without an
Energy Dashboard named no source, so every tap there was a tap with no meter
and was never applied; a flip about no meter or another meter stood the
balance self-heal down; and a tap on a flip that did not apply only cleared
it, though the log asks for a tap to flip the new meter.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    NO_GRID_SOURCE, SensorReader,
)

from .test_split_grid_integration import (
    _make_energy_dashboard_config, _make_reader_with_states, _state,
)

METER = "sensor.power_meter"
IMP, EXP = "sensor.grid_import_w", "sensor.grid_export_w"


def _no_meter_reader(**cfg):
    """A dashboard home whose grid gives SEM nothing to read: no power
    sensor, no counters, no split pair."""
    ed = _make_energy_dashboard_config(
        solar_power="sensor.solar", grid_import_power=None,
        grid_import_energy=None, grid_export_energy=None, battery_power=None)
    return _make_reader_with_states(
        MagicMock(), {"sensor.solar": _state(5000)}, ed, extra_config=cfg)


def _meter_reader(**cfg):
    """The same home once SEM finds the meter: +2000 W, SEM's sign (export)."""
    ed = _make_energy_dashboard_config(
        solar_power="sensor.solar", grid_import_power=METER, battery_power=None)
    states = {
        "sensor.solar": _state(5000),
        METER: _state(2000, device_class="power"),
        "sensor.grid_import_total": _state(10, "kWh"),
        "sensor.grid_export_total": _state(20, "kWh"),
    }
    r = _make_reader_with_states(MagicMock(), states, ed, extra_config=cfg)
    r._grid_sign_detected = True          # the lock has spoken: no negation
    r._grid_sign_inverted = False
    return r


def _legacy_reader(pair=False, **cfg):
    """A home without an Energy Dashboard: the Config card's grid sensor, or
    a manual import/export pair. +2000 W of export either way."""
    states = {
        "sensor.solar": _state(5000),
        METER: _state(2000, device_class="power"),
        IMP: _state(0, device_class="power"),
        EXP: _state(2000, device_class="power"),
    }
    base = {"solar_power_sensor": "sensor.solar"}
    if pair:
        base.update(grid_import_power_entity=IMP, grid_export_power_entity=EXP)
    else:
        base["grid_power_sensor"] = METER
    base.update(cfg)
    return _make_reader_with_states(MagicMock(), states, None, extra_config=base)


def _tap(reader, options=None):
    """What the flip service saves for a tap (turning the flip on)."""
    reader.read_power()
    return reader.user_flip_options(dict(options or {}), True)


# ═══════════════════════════════════════════════════════════════════════
# The issue
# ═══════════════════════════════════════════════════════════════════════

class TestATapWithNoMeterFlipsNoMeter:
    def test_the_tap_is_saved_bound_to_no_meter(self):
        opts = _tap(_no_meter_reader())
        assert opts == {"grid_sign_user_flip": True,
                        "grid_sign_user_flip_source": NO_GRID_SOURCE}

    def test_the_meter_found_later_reads_as_it_is(self):
        """The reported case: export 2000 W read as 2000 W of import."""
        opts = _tap(_no_meter_reader())
        r = _meter_reader(**opts)
        assert r.read_power().grid_power == 2000          # was −2000
        assert r.user_flip_applies() is False

    def test_a_tap_saved_by_a_build_since_971_reads_the_same(self):
        """Those builds saved the no-meter tap with a None source."""
        r = _meter_reader(grid_sign_user_flip=True, grid_sign_user_flip_source=None)
        assert r.read_power().grid_power == 2000
        assert r.user_flip_applies() is False

    def test_an_empty_source_is_no_meter_too(self):
        r = _meter_reader(grid_sign_user_flip=True, grid_sign_user_flip_source="")
        assert r.read_power().grid_power == 2000

    @pytest.mark.parametrize("source", ["combined:sensor.other", "sum:2",
                                        f"discovered:{IMP}|{EXP}"])
    def test_no_auto_source_takes_a_no_meter_flip(self, source):
        r = _no_meter_reader(grid_sign_user_flip=True,
                             grid_sign_user_flip_source=NO_GRID_SOURCE)
        r._grid_source_key = source
        assert r.user_flip_applies() is False

    def test_with_no_meter_still_read_it_applies_to_nothing(self):
        r = _no_meter_reader(grid_sign_user_flip=True,
                             grid_sign_user_flip_source=NO_GRID_SOURCE)
        assert r.read_power().grid_power == 0
        assert r._grid_source_key is None
        assert r.user_flip_applies() is False


class TestATapWhileTheMeterReadsNothingFlipsNoMeter:
    """Review: the source a branch named last stays set while the meter is
    dark, or once no branch reads it. A tap then reads 0 W as well."""

    def test_a_tap_while_the_meter_is_dark(self):
        r = _meter_reader()
        r.read_power()
        r.hass.states.get(METER).state = "unavailable"
        p = r.read_power()
        assert p.grid_power_unavailable is True
        assert r._grid_source_key == f"combined:{METER}"     # the lock's, kept
        opts = r.user_flip_options({}, True)
        assert opts["grid_sign_user_flip_source"] == NO_GRID_SOURCE
        assert r.grid_sign_diagnostics()["grid_read_source"] is None
        # …so the meter back on reads as it is
        assert _meter_reader(**opts).read_power().grid_power == 2000

    def test_a_tap_once_no_branch_reads_the_grid(self):
        r = _meter_reader()
        r.read_power()
        r._energy_dashboard_config = _make_energy_dashboard_config(
            solar_power="sensor.solar", grid_import_power=None,
            grid_import_energy=None, grid_export_energy=None, battery_power=None)
        r.read_power()
        assert r._grid_source_key == f"combined:{METER}"     # kept, as before
        assert r.user_flip_options({}, True)[
            "grid_sign_user_flip_source"] == NO_GRID_SOURCE

    def test_a_read_that_raises_keeps_the_last_source(self):
        """Review 2: the saved lock's source must survive a failed read."""
        r = _meter_reader()
        r.read_power()
        r._read_from_energy_dashboard = MagicMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            r.read_power()
        assert r._grid_source_key == f"combined:{METER}"
        assert r._grid_read_source is None

    def test_a_tap_on_a_live_meter_is_bound_to_it(self):
        r = _meter_reader()
        r.read_power()
        assert r.user_flip_options({}, True)[
            "grid_sign_user_flip_source"] == f"combined:{METER}"


class TestFlipsFromBeforeTheBindingAreKept:
    def test_a_store_without_the_key_still_corrects_the_meter(self):
        """#971's rule for a flip from before the binding is unchanged."""
        r = _meter_reader(grid_sign_user_flip=True)
        assert r.read_power().grid_power == -2000
        assert r.user_flip_applies() is True

    def test_a_tap_on_the_meter_still_corrects_it(self):
        opts = _tap(_meter_reader())
        assert opts["grid_sign_user_flip_source"] == f"combined:{METER}"
        r = _meter_reader(**opts)
        assert r.read_power().grid_power == -2000

    def test_turning_it_off_saves_no_source(self):
        r = _no_meter_reader(); r.read_power()
        out = r.user_flip_options({"grid_sign_user_flip": True,
                                   "grid_sign_user_flip_source": NO_GRID_SOURCE}, False)
        assert out["grid_sign_user_flip"] is False
        assert out["grid_sign_user_flip_source"] is None


class TestTheDiagnosticsSayIt:
    def test_a_no_meter_tap_shows_its_binding(self):
        r = _meter_reader(grid_sign_user_flip=True, grid_sign_user_flip_source=None)
        r.read_power()
        d = r.grid_sign_diagnostics()
        assert d["user_flip_source"] == NO_GRID_SOURCE
        assert d["grid_source"] == f"combined:{METER}"
        assert d["user_flip_applies"] is False

    def test_a_flip_from_before_shows_none(self):
        r = _meter_reader(grid_sign_user_flip=True); r.read_power()
        assert r.grid_sign_diagnostics()["user_flip_source"] is None

    def test_a_flip_that_is_off_shows_no_source(self):
        """Review: tap-off and reset save a None source with the flip off."""
        r = _meter_reader(grid_sign_user_flip=False, grid_sign_user_flip_source=None)
        r.read_power()
        d = r.grid_sign_diagnostics()
        assert d["user_flip_source"] is None and d["user_flip"] is False

    def test_the_log_names_no_meter_once(self, caplog):
        import logging
        r = _meter_reader(grid_sign_user_flip=True,
                          grid_sign_user_flip_source=NO_GRID_SOURCE)
        with caplog.at_level(logging.WARNING):
            r.read_power(); r.read_power()
        hits = [m for m in caplog.messages if "one-tap user flip is bound" in m]
        assert len(hits) == 1, hits
        assert "bound to no grid sensor" in hits[0]

    def test_no_log_while_no_meter_is_read(self, caplog):
        """Nothing is read, so there is nothing the flip was kept off."""
        import logging
        r = _no_meter_reader(grid_sign_user_flip=True,
                             grid_sign_user_flip_source=NO_GRID_SOURCE)
        with caplog.at_level(logging.WARNING):
            r.read_power()
        assert not [m for m in caplog.messages if "user flip" in m]


# ═══════════════════════════════════════════════════════════════════════
# Swept: the read without an Energy Dashboard
# ═══════════════════════════════════════════════════════════════════════

class TestTheReadWithoutADashboardNamesItsSource:
    def test_the_tap_on_the_grid_sensor_applies(self):
        """Before: saved with no source and never applied."""
        opts = _tap(_legacy_reader())
        assert opts["grid_sign_user_flip_source"] == f"combined:{METER}"
        r = _legacy_reader(**opts)
        assert r.read_power().grid_power == -2000
        assert r.user_flip_applies() is True

    def test_the_tap_on_a_manual_pair_applies_to_that_pair(self):
        opts = _tap(_legacy_reader(pair=True))
        assert opts["grid_sign_user_flip_source"] == f"manual:{IMP}|{EXP}"
        assert _legacy_reader(pair=True, **opts).read_power().grid_power == -2000

    def test_a_flip_from_before_the_binding_stays_off(self):
        """Review: this read has not applied such a flip since #971. Off for
        weeks, it must not come back on its own (a user may have fixed the
        sign with Invert grid power sign since)."""
        r = _legacy_reader(grid_sign_user_flip=True)
        assert r.read_power().grid_power == 2000
        assert r.user_flip_applies() is False
        r2 = _legacy_reader(grid_sign_user_flip=True, grid_sign_invert=True)
        assert r2.read_power().grid_power == -2000              # once, not twice

    def test_a_flip_from_before_never_reaches_a_manual_pair(self):
        r = _legacy_reader(pair=True, grid_sign_user_flip=True)
        assert r.read_power().grid_power == 2000

    def test_with_no_grid_sensor_the_tap_is_bound_to_no_meter(self):
        r = _make_reader_with_states(
            MagicMock(), {"sensor.solar": _state(5000)}, None,
            extra_config={"solar_power_sensor": "sensor.solar"})
        assert _tap(r)["grid_sign_user_flip_source"] == NO_GRID_SOURCE

    def test_a_saved_lock_is_kept_as_before(self):
        """Its stores saved the lock with a None source. Named now, the
        source must not drop that lock (#1246: it is named from now on)."""
        r = _legacy_reader()
        r.restore_sign_state({"grid_detected": True, "grid_inverted": True,
                              "grid_source": None})
        assert r.read_power().grid_power == -2000
        assert r._grid_sign_detected is True and r._grid_sign_inverted is True
        assert r.export_sign_state()["grid_source"] == f"combined:{METER}"

    def test_a_legacy_pair_lock_is_judged_on_the_dashboard_read(self):
        """Review: legacy pair, a stale inverted lock, then a dashboard read
        of the same pair. Saved with no source, it is judged: a pair is never
        negated (#1103)."""
        legacy = _legacy_reader(pair=True)
        legacy.read_power()
        legacy._grid_sign_detected = True
        legacy._grid_sign_inverted = True
        saved = legacy.export_sign_state()
        ed = _make_energy_dashboard_config(
            solar_power="sensor.solar", grid_import_power=None, battery_power=None)
        states = {"sensor.solar": _state(5000),
                  IMP: _state(0, device_class="power"),
                  EXP: _state(2000, device_class="power"),
                  "sensor.grid_import_total": _state(10, "kWh"),
                  "sensor.grid_export_total": _state(20, "kWh")}
        r = _make_reader_with_states(
            MagicMock(), states, ed,
            extra_config={"grid_import_power_entity": IMP,
                          "grid_export_power_entity": EXP})
        r.restore_sign_state(saved)
        assert r.read_power().grid_power == 2000

    def test_the_check_still_runs_on_a_dashboard_read(self):
        """Unchanged (#1103): a lock saved on another source is learned again."""
        r = _meter_reader()
        r._grid_sign_detected = False
        r.restore_sign_state({"grid_detected": True, "grid_inverted": True,
                              "grid_source": "combined:sensor.old_meter"})
        r.read_power()
        assert r._grid_sign_inverted is False


def test_every_grid_branch_of_both_reads_tags_its_source():
    """#971's AST check covered the dashboard read only; the read without a
    dashboard assigned grid_power with no source (#1192)."""
    import ast
    from .ast_contracts import _tree_of
    for method in (SensorReader._read_from_energy_dashboard,
                   SensorReader._read_from_legacy_config):
        tree = _tree_of(method)
        assigns = [n.lineno for n in ast.walk(tree)
                   if isinstance(n, ast.Assign) and any(
                       isinstance(t, ast.Attribute) and t.attr == "grid_power"
                       for t in n.targets)]
        tags = [n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.Assign) and any(
                    isinstance(t, ast.Attribute) and t.attr == "_grid_source_key"
                    for t in n.targets)]
        assert assigns, f"no grid_power assignment in {method.__name__}?"
        untagged = [a for a in assigns if not any(0 < t - a <= 3 for t in tags)]
        assert not untagged, (
            f"{method.__name__}: grid_power assigned without a source tag "
            f"at lines {untagged}")


# ═══════════════════════════════════════════════════════════════════════
# Swept: who reads the saved flag
# ═══════════════════════════════════════════════════════════════════════

class TestOnlyAFlipThatAppliesStandsTheSelfHealDown:
    def test_a_no_meter_flip_is_no_decision_about_the_meter(self):
        r = _meter_reader(grid_sign_user_flip=True,
                          grid_sign_user_flip_source=NO_GRID_SOURCE)
        r.read_power()
        assert r.grid_sign_user_override is False

    def test_a_flip_on_another_meter_is_no_decision_either(self):
        r = _meter_reader(grid_sign_user_flip=True,
                          grid_sign_user_flip_source=f"manual:{IMP}|{EXP}")
        r.read_power()
        assert r.grid_sign_user_override is False

    def test_a_flip_that_applies_still_counts(self):
        r = _meter_reader(grid_sign_user_flip=True,
                          grid_sign_user_flip_source=f"combined:{METER}")
        r.read_power()
        assert r.grid_sign_user_override is True

    def test_the_manual_invert_still_counts(self):
        r = _meter_reader(grid_sign_invert=True)
        r.read_power()
        assert r.grid_sign_user_override is True


async def _flip_service():
    """The real flip_grid_sign handler, from the real registration."""
    from custom_components.solar_energy_management import (
        _async_register_phase_services,
    )
    hass = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    await _async_register_phase_services(hass, MagicMock())
    handlers = {c.args[1]: c.args[2] for c in hass.services.async_register.call_args_list}
    return hass, handlers["flip_grid_sign"]


def _entry(options, reader):
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.options = dict(options)
    entry.runtime_data = MagicMock()
    entry.runtime_data._sensor_reader = reader
    return entry


async def _press(options, reader):
    hass, handler = await _flip_service()
    entry = _entry(options, reader)
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    hass.config_entries.async_reload = AsyncMock()
    saved = {}
    hass.config_entries.async_update_entry = (
        lambda e, options: saved.update(options=options))
    call = MagicMock(); call.data = {}
    result = await handler(call)
    return result, saved["options"]


class TestTheTapActsOnTheMeterReadNow:
    async def test_a_flip_that_does_not_apply_is_replaced_in_one_tap(self):
        """The log says: tap again on the new source. That tap used to only
        clear the old flip, so the meter needed two taps."""
        opts = {"grid_sign_user_flip": True,
                "grid_sign_user_flip_source": NO_GRID_SOURCE}
        r = _meter_reader(**opts); r.read_power()
        result, saved = await _press(opts, r)
        assert result["user_flip"] is True
        assert saved["grid_sign_user_flip"] is True
        assert saved["grid_sign_user_flip_source"] == f"combined:{METER}"

    async def test_a_flip_that_applies_is_turned_off(self):
        opts = {"grid_sign_user_flip": True,
                "grid_sign_user_flip_source": f"combined:{METER}"}
        r = _meter_reader(**opts); r.read_power()
        result, saved = await _press(opts, r)
        assert result["user_flip"] is False
        assert saved["grid_sign_user_flip"] is False
        assert saved["grid_sign_user_flip_source"] is None

    async def test_a_tap_with_no_meter_is_saved_bound_to_no_meter(self):
        r = _no_meter_reader(); r.read_power()
        _, saved = await _press({}, r)
        assert saved["grid_sign_user_flip"] is True
        assert saved["grid_sign_user_flip_source"] == NO_GRID_SOURCE

    async def test_a_second_tap_with_no_meter_turns_it_off(self):
        """Review: each tap with no meter saved the flip on again."""
        opts = {"grid_sign_user_flip": True,
                "grid_sign_user_flip_source": NO_GRID_SOURCE}
        r = _no_meter_reader(**opts); r.read_power()
        result, saved = await _press(opts, r)
        assert result["user_flip"] is False
        assert saved["grid_sign_user_flip"] is False

    async def test_a_flip_from_before_on_the_meter_is_turned_off(self):
        opts = {"grid_sign_user_flip": True}
        r = _meter_reader(**opts); r.read_power()
        _, saved = await _press(opts, r)
        assert saved["grid_sign_user_flip"] is False

    async def test_without_a_reader_the_tap_is_bound_to_no_meter(self):
        _, saved = await _press({}, None)
        assert saved["grid_sign_user_flip"] is True
        assert saved["grid_sign_user_flip_source"] == NO_GRID_SOURCE
