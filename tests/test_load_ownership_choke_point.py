"""SEM must own every load it actuates (bug class 17, instance 5).

``_sem_owned`` is what tells SEM "this load is on because I turned it on".
Setting Mode → Off releases a running load ONLY through that flag
(``compute_load_intent`` clause 1, and the force-expiry pass in
``SurplusController.update``). Pre-fix, ownership was recorded at the call
site and four of the five activation passes forgot it — no ``activate()``
implementation sets it either — so a load started by the Tier-2 overnight
battery pass, the cheap-hours grid pass or the deadline pass ran with
ownership False and Mode → Off left it running forever.

Caught live on HA-PROD 2026-07-26: a towel heater started by the Tier-2 pass
was still drawing 648 W five minutes after Mode → Off. Bug class 17,
instance 5 — see docs/BUG_CLASSES.md.

The fix funnels every actuation through ``_activate_owned`` /
``_deactivate_owned``; the AST guard below is what keeps it funnelled.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from custom_components.solar_energy_management.coordinator import surplus_controller as sc
from custom_components.solar_energy_management.devices.base import (
    ControllableDevice,
    DeviceControlMode,
)

SOURCE = Path(sc.__file__)
OWNERSHIP_HELPERS = {"_activate_owned", "_deactivate_owned"}


class _FakeDevice:
    """Minimal stand-in with the real ownership bookkeeping."""

    def __init__(self, rated=600.0):
        self.device_id = "towel"
        self.name = "Towel heater"
        self.rated_power = rated
        self.control_mode = DeviceControlMode.SURPLUS
        self._active = False
        self._sem_owned = False
        self._sem_commanded = False   # (#847) did SEM issue the ON itself?
        self._observed_off_since = None
        self._last_activated = None
        self._last_deactivated = None
        self.refuse_stop = False
        self.activate_calls = 0
        self.deactivate_calls = 0
        self.adjust_calls = 0

    @property
    def is_active(self):
        return self._active

    def get_current_consumption(self):
        return self.rated_power if self._active else 0.0

    async def activate(self, watts):
        self.activate_calls += 1
        self._active = True
        return self.rated_power

    async def deactivate(self):
        self.deactivate_calls += 1
        if not self.refuse_stop:
            self._active = False

    async def adjust_power(self, watts):
        self.adjust_calls += 1
        return self.get_current_consumption()

    # anti-flicker is not what these tests are about
    def can_activate(self):
        return True

    def can_deactivate(self):
        return True

    def reset_surplus_timer(self):
        pass

    # the real bookkeeping (devices/base.py)
    record_activated = ControllableDevice.record_activated
    record_deactivated = ControllableDevice.record_deactivated


@pytest.mark.unit
class TestOwnershipChokePoint:

    async def test_activation_records_ownership(self):
        dev = _FakeDevice()
        consumed = await sc._activate_owned(dev, 600.0)
        assert consumed == 600.0
        assert dev._sem_owned is True

    async def test_a_refused_activation_does_not_claim_ownership(self):
        dev = _FakeDevice()

        async def refuse(_watts):
            return 0.0

        dev.activate = refuse
        assert await sc._activate_owned(dev, 600.0) == 0.0
        assert dev._sem_owned is False

    async def test_deactivation_releases_ownership(self):
        dev = _FakeDevice()
        await sc._activate_owned(dev, 600.0)
        assert await sc._deactivate_owned(dev) is True
        assert dev._sem_owned is False

    async def test_anti_flicker_refusal_keeps_ownership(self):
        """min_on can refuse the stop. SEM still owns a load it is still
        driving — releasing early would strand it exactly the same way."""
        dev = _FakeDevice()
        await sc._activate_owned(dev, 600.0)
        dev.refuse_stop = True
        assert await sc._deactivate_owned(dev) is False
        assert dev._sem_owned is True


@pytest.mark.unit
class TestModeOffReleasesEveryStartPath:
    """The live PROD repro, as a unit test: whichever pass started the load,
    Mode → Off must yield an ``on=False`` intent."""

    @pytest.mark.parametrize("marker", [
        "_batt_overnight_forced",   # Tier-2 overnight battery pass
        "_offpeak_forced",          # cheap-hours grid pass
        None,                       # main surplus pass
    ])
    async def test_mode_off_releases_the_load(self, marker):
        dev = _FakeDevice()
        await sc._activate_owned(dev, 600.0)      # started by SEM
        if marker:
            setattr(dev, marker, True)
        dev.control_mode = DeviceControlMode.OFF

        intent = sc.compute_load_intent(dev, remaining_surplus_w=0.0)
        assert intent.on is False
        assert "SEM-started" in intent.reason

    async def test_an_adopted_load_is_released_without_a_write(self):
        """(#847) The third case, between the two below: SEM ADOPTED a load
        it never started (running at registration / turned on externally
        while in Surplus — claimed so goal gates could stop it). Mode → Off
        releases the claim and writes NOTHING: the strand this file guards
        cannot happen (SEM never started it), and switching off a load the
        user is running is the harm #847 reported."""
        dev = _FakeDevice()
        dev._active = True
        dev.control_mode = DeviceControlMode.SURPLUS
        dev._adopt_ownership = ControllableDevice._adopt_ownership.__get__(dev)
        assert dev._adopt_ownership() is True          # owned, not commanded
        assert dev._sem_owned and not dev._sem_commanded
        dev.control_mode = DeviceControlMode.OFF

        intent = sc.compute_load_intent(dev, remaining_surplus_w=0.0)
        assert intent.on is True                        # left exactly as it is
        assert intent.reason == "off — monitor only"
        assert dev._sem_owned is False                  # claim handed back
        assert dev.deactivate_calls == 0                # and nothing written

    async def test_a_user_started_load_is_left_alone(self):
        """The other half of the contract: Off means hands off a load the
        USER turned on. Ownership is what distinguishes the two."""
        dev = _FakeDevice()
        dev._active = True                        # external actor, no ownership
        dev.control_mode = DeviceControlMode.OFF

        intent = sc.compute_load_intent(dev, remaining_surplus_w=0.0)
        assert intent.on is True
        assert intent.reason == "off — monitor only"


@pytest.mark.unit
class TestOffIsAOneShotRelease:
    """Off means: stop it ONCE, then hands off.

    The release is not "SEM now keeps this device off" — it is SEM handing the
    device back. After the stop, ownership is gone and the device is the user's:
    SEM must not command it again, and must not stop it if the user runs it.
    """

    async def test_stop_once_then_never_touch_it_again(self):
        dev = _FakeDevice()
        await sc._activate_owned(dev, 600.0)       # SEM starts it overnight
        dev._batt_overnight_forced = True

        dev.control_mode = DeviceControlMode.OFF
        intent = sc.compute_load_intent(dev, remaining_surplus_w=0.0)
        await sc.reconcile_load(dev, intent)
        assert dev.is_active is False
        assert dev._sem_owned is False              # handed back, not just stopped
        assert dev.deactivate_calls == 1

        # Subsequent cycles — including ones with surplus available — are
        # monitor-only. No second stop, no re-start, no re-tune.
        for _ in range(3):
            nxt = sc.compute_load_intent(dev, remaining_surplus_w=5000.0)
            assert nxt.reason == "off — monitor only"
            await sc.reconcile_load(dev, nxt)
        assert dev.activate_calls == 1
        assert dev.deactivate_calls == 1
        assert dev.adjust_calls == 0

    async def test_a_manual_turn_on_after_the_release_is_left_running(self):
        dev = _FakeDevice()
        await sc._activate_owned(dev, 600.0)
        dev.control_mode = DeviceControlMode.OFF
        await sc.reconcile_load(
            dev, sc.compute_load_intent(dev, remaining_surplus_w=0.0)
        )

        dev._active = True                          # the user flips it back on
        intent = sc.compute_load_intent(dev, remaining_surplus_w=0.0)
        assert intent.on is True
        assert intent.reason == "off — monitor only"
        await sc.reconcile_load(dev, intent)
        assert dev.is_active is True                # SEM left the user's run alone
        assert dev.deactivate_calls == 1
        assert dev.adjust_calls == 0


@pytest.mark.unit
class TestOwnershipAstGuard:
    """Structural close-out. Ownership was forgotten at 4 of 5 call sites
    because it was the call site's job; this asserts it can't be again."""

    def test_no_raw_actuation_outside_the_helpers(self):
        tree = ast.parse(SOURCE.read_text())

        # Map every node to its enclosing top-level function/method name.
        offenders = []
        for scope in ast.walk(tree):
            if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if scope.name in OWNERSHIP_HELPERS:
                continue
            for node in ast.walk(scope):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                if not isinstance(fn, ast.Attribute):
                    continue
                if fn.attr not in ("activate", "deactivate"):
                    continue
                # self.activate(...) style helpers on the controller itself are
                # not device actuation; only <device>.activate/deactivate is.
                if isinstance(fn.value, ast.Name) and fn.value.id == "self":
                    continue
                offenders.append(f"{scope.name}:{node.lineno} → .{fn.attr}()")

        assert not offenders, (
            "Device actuation must go through _activate_owned/_deactivate_owned "
            "so ownership is recorded. Raw call sites found:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_helpers_still_exist_and_are_used(self):
        src = SOURCE.read_text()
        for helper in OWNERSHIP_HELPERS:
            assert f"async def {helper}(" in src, f"{helper} was removed"
            # defined once, called at least once
            assert src.count(f"await {helper}(") >= 1, f"{helper} is unused"


@pytest.mark.unit
def test_no_activate_implementation_is_expected_to_own():
    """Guard against the fix drifting back into the device layer.

    Ownership deliberately lives at the controller choke point, not in each
    ``activate()`` — a device does not know whether SEM or a user asked for it.
    If someone adds ``record_activated()`` inside a device implementation this
    fails, so the two places can't silently both claim it.
    """
    from custom_components.solar_energy_management.devices import base as devbase

    for name, obj in vars(devbase).items():
        if not inspect.isclass(obj) or not issubclass(obj, ControllableDevice):
            continue
        activate = obj.__dict__.get("activate")
        if activate is None:
            continue
        src = inspect.getsource(activate)
        assert "record_activated" not in src, (
            f"{name}.activate() records ownership — that belongs to "
            "surplus_controller._activate_owned"
        )
