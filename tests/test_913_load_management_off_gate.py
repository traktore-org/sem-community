"""(#913) With load management OFF — the default since #897 — services
that never needed the load manager must not refuse for its absence.

Four handlers gated on ``coordinator._load_manager`` and said "not
initialized, wait" when it was None. Two of them never touch it:

* ``update_target_peak`` writes a config-entry option the EV planner reads
  as its ceiling whether or not shedding is armed. Refusing to SET it while
  telling the user to enable load management prescribed the exact thing
  #897 exists to keep off.
* ``update_device_config`` gated above every branch, and 15 of its 18
  properties go through the device registry only.

The two that do need it — priority sync, and the fallback branch of the
batch priority update — now say which of two things is true: switched
off, or switched on and failed to start.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.solar_energy_management import _require_load_manager
from custom_components.solar_energy_management.tests.ast_contracts import (
    call_sites,
)

_ROOT = Path(__file__).resolve().parent.parent


class TestTheHelperSaysWhichThingIsTrue:

    def test_a_live_manager_is_returned(self):
        lm = object()
        c = SimpleNamespace(_load_manager=lm, config={})
        assert _require_load_manager(c) is lm

    def test_switched_off_is_a_validation_error_naming_the_setting(self):
        c = SimpleNamespace(_load_manager=None,
                            config={"load_management_enabled": False})
        with pytest.raises(ServiceValidationError) as e:
            _require_load_manager(c)
        assert e.value.translation_key == "load_management_disabled"

    def test_the_default_is_off_so_a_bare_config_reads_as_switched_off(self):
        c = SimpleNamespace(_load_manager=None, config={})
        with pytest.raises(ServiceValidationError) as e:
            _require_load_manager(c)
        assert e.value.translation_key == "load_management_disabled"

    def test_enabled_but_absent_is_a_failure_not_a_wait(self):
        c = SimpleNamespace(_load_manager=None,
                            config={"load_management_enabled": True})
        with pytest.raises(HomeAssistantError) as e:
            _require_load_manager(c)
        assert not isinstance(e.value, ServiceValidationError)
        assert e.value.translation_key == "load_management_failed_to_start"


class TestOnlyTheTwoRealConsumersGate:

    def test_exactly_two_call_sites_both_in_init(self):
        sites = call_sites("_require_load_manager")
        assert len(sites) == 2, sites
        assert all(str(p).endswith("__init__.py") for p, _, _ in sites), sites

    def test_the_old_key_is_raised_nowhere(self):
        """A retired exception key must have no raise site — the orphan
        class (#913 found ``energy_dashboard_configuration_failed`` had
        been one for months)."""
        assert _raised_keys().isdisjoint(
            {"load_management_not_initialized",
             "energy_dashboard_configuration_failed"})


def _raised_keys() -> set:
    """Every ``translation_key=`` constant on a ``raise`` in production."""
    keys = set()
    for p in sorted(_ROOT.rglob("*.py")):
        rel = p.relative_to(_ROOT)
        if set(rel.parts) & {"tests", "scripts", "node_modules", ".git"}:
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Raise) or not isinstance(n.exc, ast.Call):
                continue
            for kw in n.exc.keywords:
                if (kw.arg == "translation_key"
                        and isinstance(kw.value, ast.Constant)):
                    keys.add(kw.value.value)
    return keys


class TestTheExceptionBlockHasNoOrphansAndNoGaps:

    def test_every_declared_key_is_raised_and_every_raised_key_declared(self):
        declared = set(json.load(open(_ROOT / "strings.json"))["exceptions"])
        raised = _raised_keys()
        assert declared == raised, (
            f"orphans (declared, never raised): {sorted(declared - raised)}\\n"
            f"gaps (raised, never declared): {sorted(raised - declared)}")

    def test_the_two_new_messages_agree_between_strings_and_en(self):
        s = json.load(open(_ROOT / "strings.json"))["exceptions"]
        e = json.load(open(_ROOT / "translations" / "en.json"))["exceptions"]
        for k in ("load_management_disabled", "load_management_failed_to_start",
                  "device_registry_not_initialized"):
            assert s[k] == e[k], k

    def test_every_language_carries_the_new_keys(self):
        for f in sorted((_ROOT / "translations").glob("*.json")):
            ex = json.load(open(f))["exceptions"]
            for k in ("load_management_disabled",
                      "load_management_failed_to_start"):
                assert k in ex, f"{f.name} lacks {k}"
            assert "load_management_not_initialized" not in ex, f.name


class TestTheTwoHandlersThatNeverNeededIt:
    """Structural: neither gates on the manager any more."""

    def _handler_src(self, name: str) -> ast.AST:
        src = (_ROOT / "__init__.py").read_text(encoding="utf-8")
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.AsyncFunctionDef) and n.name == name:
                return n
        raise AssertionError(name)

    def _raises_key(self, fn: ast.AST, key: str) -> bool:
        return any(
            isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
            and any(kw.arg == "translation_key"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value == key for kw in n.exc.keywords)
            for n in ast.walk(fn))

    def test_update_target_peak_never_refuses_for_the_manager(self):
        fn = self._handler_src("async_update_target_peak")
        assert not any(isinstance(n, ast.Raise) for n in ast.walk(fn)), (
            "update_target_peak refuses — the limit is a config option the "
            "planner reads with shedding off")

    def test_update_target_peak_without_a_manager_does_not_reload(self):
        """(ruflo refutation before PROD) The first no-manager branch went
        through set_option, where this key is UNROUTED and the unrouted path
        ends in a full integration reload — a slider drag tore down the
        coordinator on every default install. It must take the no-reload
        seam and never call set_option or async_reload."""
        fn = self._handler_src("async_update_target_peak")
        called = {
            (n.func.id if isinstance(n.func, ast.Name)
             else getattr(n.func, "attr", ""))
            for n in ast.walk(fn) if isinstance(n, ast.Call)
        }
        assert "persist_global_option" in called, (
            "the no-manager write no longer goes through the no-reload seam")
        assert "async_reload" not in called
        # no set_option service call from inside this handler
        svc = [
            n for n in ast.walk(fn) if isinstance(n, ast.Call)
            and getattr(n.func, "attr", "") == "async_call"
            and any(isinstance(a, ast.Constant) and a.value == "set_option"
                    for a in n.args)
        ]
        assert not svc, "update_target_peak still routes through set_option"

    def test_update_device_config_has_no_manager_gate_above_its_branches(self):
        fn = self._handler_src("async_update_device_config")
        # the only raise for a MISSING dependency is the registry one, and
        # only when the manager is missing too
        assert not self._raises_key(fn, "load_management_disabled")
        assert not self._raises_key(fn, "load_management_failed_to_start")
        assert self._raises_key(fn, "device_registry_not_initialized")
