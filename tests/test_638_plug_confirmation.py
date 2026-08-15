"""#638 — the cycle asks the plug once.

Live on .175 (15.08, verification campaign): ``sensor.sem_charging_state``
flapped to "System ready" — the car-AWAY face — three times inside three
minutes while ``binary_sensor.sem_charger_keba_fa87f74cd3_connected``
stayed ``on`` throughout. One ``coordinator.data``, two answers to one
question. On real hardware the same raw read reaches ``decide()``, whose
every mode returns "EV disconnected", so the blip is a contactor stop.

Root cause: the plug question was answered TWICE per cycle from two
different places. ``ev_control._update_session_tracking`` debounced it (a
disconnect counts only after three confirmed cycles, absorbing the UDP-blip
family #35/#595/#753) and left the confirmed answer on
``_last_ev_connected_per_charger`` — which the per-charger entities, the
virtual-SOC decay (#648), the SOC cap (#708) and the notification gate
(#584) read. Everything else read ``power.ev_connected`` RAW: the state
machine (``_build_charging_context``), ``build_charger_view`` → ``decide``,
the plan layer, the fleet entity. ~14 sites, one of them the face the user
was looking at.

The debounce now runs ONCE, at the source: ``_confirm_ev_connection``
filters ``power`` the cycle it is read, before any consumer sees it. There
is no raw answer left in the cycle to disagree with, so the fix is
structural rather than per-site.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.build_view import (
    build_charger_view,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    FleetCycleState,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.ev_availability import (
    confirm_connection,
    operational_ev_connected,
)


@pytest.mark.unit
class TestTheConfirmedAnswer:
    """The rule itself: a connect is immediate, a disconnect is earned."""

    def test_a_connect_is_immediate(self):
        assert confirm_connection(False, True, streak=0, in_warmup=False) == (True, 0)

    def test_one_missed_poll_is_not_an_unplug(self):
        assert confirm_connection(True, False, streak=0, in_warmup=False) == (True, 1)

    def test_three_consecutive_cycles_are_an_unplug(self):
        confirmed, streak = True, 0
        for _ in range(2):
            confirmed, streak = confirm_connection(confirmed, False, streak, False)
            assert confirmed is True
        confirmed, streak = confirm_connection(confirmed, False, streak, False)
        assert confirmed is False

    def test_a_reconnect_disarms_the_streak(self):
        """False, False, True must not leave two counted — the next two
        Falses are a new count, not a third (#753 blip family)."""
        confirmed, streak = True, 2
        confirmed, streak = confirm_connection(confirmed, True, streak, False)
        assert (confirmed, streak) == (True, 0)

    def test_the_boot_warmup_never_confirms_a_disconnect(self):
        """A sensor that has not spoken yet is not a sensor saying no
        (#753: a warm-up 'unplug' finalized a 6 kWh session)."""
        confirmed, streak = True, 0
        for _ in range(6):
            confirmed, streak = confirm_connection(confirmed, False, streak,
                                                   in_warmup=True)
        assert confirmed is True

    def test_an_absent_car_stays_absent_without_counting(self):
        assert confirm_connection(False, False, streak=0, in_warmup=False) == (False, 0)


def _power(*, fleet=True, per_charger=None):
    """PowerReadings-shaped double carrying what build_charger_view reads."""
    p = MagicMock()
    p.solar_power = 8000
    p.home_consumption_power = 1000
    p.battery_power = 0
    p.battery_charge_power = 0
    p.battery_discharge_power = 0
    p.battery_soc = 80
    p.grid_import_power = 0.0
    p.grid_export_power = 0.0
    p.ev_power = 0
    p.ev_power_per_charger = None
    p.ev_connected = fleet
    p.ev_charging = False
    p.ev_connected_per_charger = per_charger
    p.ev_charging_per_charger = None
    return p


def _coord(chargers=("keba",)):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.config = {"ev_chargers": [{"id": cid, "ev_connected_sensor":
                                 f"binary_sensor.{cid}_plug"}
                                for cid in chargers]}
    c._ev_devices = {cid: MagicMock() for cid in chargers}
    c._ev_conn_confirmed = {}
    c._ev_conn_streak = {}
    c._last_ev_connected = False
    c._last_ev_connected_per_charger = {}
    return c


def _view(power, cid):
    state = FleetCycleState(
        power=power, config={"battery_capacity_kwh": 15}, is_night=False,
    )
    return build_charger_view(
        state, charger_id=cid, charger_cfg={"id": cid},
        mode="solar_only", daily_ev_kwh=0.0,
    )


@pytest.mark.unit
class TestOneCycleOneAnswer:
    """``power`` is the cycle's single source for the plug question."""

    def test_the_blip_never_reaches_a_consumer(self):
        """The three surfaces that disagreed live — the state machine's
        input, the per-charger decide() view, and the plan layer — all
        read one confirmed ``power``."""
        c = _coord()
        plugged = _power(fleet=True, per_charger={"keba": True})
        c._confirm_ev_connection(plugged)

        blip = _power(fleet=False, per_charger={"keba": False})
        c._confirm_ev_connection(blip)

        assert blip.ev_connected is True
        assert blip.ev_connected_per_charger == {"keba": True}
        # 1. ChargingContext.ev_connected → ChargingState.SOLAR_IDLE →
        #    "System ready" + stop_session(). The live symptom.
        assert operational_ev_connected(c._ev_devices, blip.ev_connected) is True
        # 2. decide(): every mode returns idle/stop on a disconnected view.
        assert _view(blip, "keba").power.connected is True
        # 3. the plan layer — a restamped night without the car.
        assert c._plan_ev_connected("keba", c.config["ev_chargers"][0], blip) is True

    def test_a_real_unplug_still_lands(self):
        c = _coord()
        c._confirm_ev_connection(_power(per_charger={"keba": True}))
        for _ in range(2):
            held = _power(fleet=False, per_charger={"keba": False})
            c._confirm_ev_connection(held)
            assert held.ev_connected is True
        gone = _power(fleet=False, per_charger={"keba": False})
        c._confirm_ev_connection(gone)
        assert gone.ev_connected is False
        assert gone.ev_connected_per_charger == {"keba": False}
        assert operational_ev_connected(c._ev_devices, gone.ev_connected) is False
        assert _view(gone, "keba").power.connected is False

    def test_a_connect_is_visible_the_same_cycle(self):
        """#638 night 3's proof — connect 00:07:32, stamp the same second —
        must survive: only the NO is second-guessed."""
        c = _coord()
        arrived = _power(per_charger={"keba": True})
        c._confirm_ev_connection(arrived)
        assert arrived.ev_connected is True
        assert _view(arrived, "keba").power.connected is True

    def test_one_charger_blipping_keeps_the_fleet_connected(self):
        c = _coord(chargers=("left", "right"))
        c._confirm_ev_connection(_power(per_charger={"left": True, "right": True}))
        blip = _power(fleet=True, per_charger={"left": False, "right": True})
        c._confirm_ev_connection(blip)
        assert blip.ev_connected_per_charger == {"left": True, "right": True}
        assert blip.ev_connected is True

    def test_an_install_with_no_per_charger_map_is_confirmed_too(self):
        """A flat legacy plug sensor blips the same way."""
        c = _coord()
        c._confirm_ev_connection(_power(fleet=True, per_charger=None))
        blip = _power(fleet=False, per_charger=None)
        c._confirm_ev_connection(blip)
        assert blip.ev_connected is True

    def test_an_empty_map_does_not_invent_a_charger(self):
        c = _coord()
        p = _power(fleet=True, per_charger={})
        c._confirm_ev_connection(p)
        assert p.ev_connected_per_charger == {}


@pytest.mark.unit
class TestTheCycleConfirmsBeforeItDecides:
    """Order is the whole fix: filter at the read, not at each reader."""

    def _src(self, name):
        import inspect
        return inspect.getsource(getattr(SEMCoordinator, name))

    def test_the_confirmation_runs_before_any_consumer(self):
        src = self._src("_async_update_data")
        confirm = src.index("_confirm_ev_connection(")
        assert confirm > src.index("read_power()"), \
            "the confirmation filters the cycle's own reading"
        assert confirm < src.index("_energy_plan_tick("), \
            "the plan tick (step 4.4) must see the confirmed answer"
        assert confirm < src.index("_update_session_tracking("), \
            "session tracking (step 4.5) must see the confirmed answer"

    def test_the_per_charger_swap_reads_the_confirmed_map(self):
        """The swap used to re-read the plug ENTITY from hass.states —
        a raw answer smuggled back in behind the filter."""
        src = self._src("_async_update_data")
        assert "pc_conn_sensor" not in src, \
            "this charger's plug answer comes from the confirmed map"

    def test_the_session_tracker_no_longer_debounces(self):
        """Two debounces in series would make a real unplug take six
        cycles and split the confirmed answer in two again."""
        import inspect
        from custom_components.solar_energy_management.coordinator.ev_control import (
            EVControlMixin,
        )
        src = inspect.getsource(EVControlMixin._update_session_tracking)
        assert "disconnect_streak" not in src
