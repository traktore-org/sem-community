"""(#928) A goal, mode or flag for a device this install does not
have is refused, not silently stored.

Seen on the branch server while proving #913: `update_device_config` with
`device_id: hot_water` on a rig with NO hot-water device returned 200 twice
and stored a window nothing would ever read. Same for `control_mode` on a
made-up id. The registry keys its stores by whatever id it is handed —
right for a device that is about to register, wrong for a typo or a row
that no longer exists. The user got success and nothing happened: the #462
silent-no-op class.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)

_ROOT = Path(__file__).resolve().parent.parent


def _registry(live=None, registrations=None, rows=None):
    reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
    live = dict(live or {})
    reg._surplus_controller = SimpleNamespace(get_device=lambda d: live.get(d))
    reg._service_registrations = dict(registrations or {})
    reg.get_devices_for_sensor = lambda: dict(rows or {})
    return reg


class TestWhatCountsAsKnown:

    def test_a_live_device_is_known(self):
        assert _registry(live={"hot_water": object()}).knows_device("hot_water")

    def test_a_persisted_service_registration_is_known_before_it_is_built(self):
        """A service-registered load may get its goal before it registers —
        that shape stays legal."""
        assert _registry(registrations={"pool": {}}).knows_device("pool")

    def test_a_row_the_card_shows_is_known(self):
        for did in ("energy_dashboard_pump", "keba_fa87f74cd3", "home_battery"):
            assert _registry(rows={did: {}}).knows_device(did), did

    def test_a_made_up_id_is_not(self):
        reg = _registry(live={"hot_water": object()},
                        registrations={"pool": {}},
                        rows={"energy_dashboard_pump": {}})
        assert not reg.knows_device("no_such_device_xyz")
        assert not reg.knows_device("")

    def test_an_unbuildable_card_payload_reads_unknown_not_crash(self):
        reg = _registry()
        def boom(): raise RuntimeError("no coordinator yet")
        reg.get_devices_for_sensor = boom
        assert reg.knows_device("anything") is False


class TestTheHandlersRefuseAnUnknownId:
    """Structural: each of the three branches that write a per-device store
    asks knows_device and raises device_not_found."""

    def _handler(self):
        src = (_ROOT / "__init__.py").read_text(encoding="utf-8")
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_update_device_config":
                return n
        raise AssertionError("async_update_device_config not found")

    def test_knows_device_is_asked_three_times(self):
        fn = self._handler()
        asks = [n for n in ast.walk(fn)
                if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "knows_device"]
        assert len(asks) == 3, (
            f"expected the goals, control_mode and flag branches each to ask "
            f"knows_device; found {len(asks)}")

    def test_device_not_found_is_raised_for_it(self):
        fn = self._handler()
        raises = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
            and any(kw.arg == "translation_key" and isinstance(kw.value, ast.Constant)
                    and kw.value.value == "device_not_found" for kw in n.exc.keywords)
        ]
        # three new + the pre-existing depends_on one
        assert len(raises) >= 4, len(raises)
        for r in raises:
            ph = [kw for kw in r.exc.keywords if kw.arg == "translation_placeholders"]
            assert ph, "device_not_found must name the device"
