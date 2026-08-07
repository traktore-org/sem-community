"""#716 — the night plan's hardware model must come from config, not literals.

@Azlinon's install clamps overnight charging at the 6 A floor. The arithmetic
behind it: the night rate is ``(peak_limit - home - committed) / watts_per_amp``,
and ``watts_per_amp`` is built in ``_compute_night_plan``. Two of its three
inputs are read from the wrong place:

* ``max_amps`` reads the FLEET ``ev_max_current`` — while the very next line
  reads ``ev_phases`` per-charger-then-fleet. In a mixed fleet the 16 A box is
  planned as if it were the 32 A one.
* ``watts_per_amp`` hardcodes 230 V. Seven other sites — including
  ``_night_deliverable_kwh`` forty lines further down the SAME file, plus every
  ``decide.py`` conversion — read ``ev_voltage``. North America runs 240 V.

Neither literal is safe-by-default: an over-large ``watts_per_amp`` under-commands
the charger (slow), an over-large ``max_amps`` over-commands it (claims fleet
budget the box cannot draw). These tests pin both reads to the same
per-charger-then-fleet resolution the rest of the planner already uses.
"""
from unittest.mock import MagicMock, patch

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.consts.states import ChargingState
from custom_components.solar_energy_management.coordinator import SEMCoordinator


def _coordinator(fleet=None, charger=None):
    """A coordinator whose night plan depends only on the config under test.

    No predictor and no energy object, so ``_expected_night_home_w`` falls
    through to ``daily_home_consumption_estimate / 24`` — 18 kWh/day = 750 W,
    a fixed, stated number rather than a learned one.
    """
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)
    cfg = {
        "id": "keba",
        "ev_min_current": 6,
        "charge_mode": "min_plus_solar",
    }
    cfg.update(charger or {})
    coord.config = {
        "ev_chargers": [cfg],
        "ev_max_current": 32,
        "ev_phases": 1,          # single-phase, as on the reporter's install
        "target_peak_limit": 6.0,
        "daily_home_consumption_estimate": 18.0,
    }
    coord.config.update(fleet or {})

    coord._load_manager = None
    coord._surplus_controller = None
    coord._night_committed_w = 0.0
    coord._ev_device = None
    coord.time_manager = MagicMock()
    coord.time_manager.get_night_end_time = MagicMock(return_value="07:00")
    coord.time_manager.get_night_window_hours = MagicMock(return_value=8.0)
    coord.hass = MagicMock()
    coord._tariff_provider = None
    coord._state_machine = MagicMock()
    coord._state_machine.current_state = ChargingState.SOLAR_IDLE
    return coord, cfg


def _top_up_amps(coord, cfg, remaining_kwh=10.0):
    base = dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0)
    with patch.object(dt_util, "now", return_value=base):
        return coord._compute_night_plan(cfg, remaining_to_min_kwh=remaining_kwh).top_up_amps


class TestVoltageComesFromConfig:
    """6000 W ceiling − 750 W home = 5250 W of headroom, single phase."""

    def test_the_default_is_still_230_volts(self):
        # Pin the unchanged case first: nothing set, nothing moves.
        coord, cfg = _coordinator()
        assert _top_up_amps(coord, cfg) == 23        # 5250 / 230 = 22.8

    def test_a_fleet_voltage_is_honoured(self):
        coord, cfg = _coordinator(fleet={"ev_voltage": 240})
        assert _top_up_amps(coord, cfg) == 22        # 5250 / 240 = 21.9

    def test_a_per_charger_voltage_beats_the_fleet_one(self):
        coord, cfg = _coordinator(
            fleet={"ev_voltage": 230}, charger={"ev_voltage": 240},
        )
        assert _top_up_amps(coord, cfg) == 22

    def test_a_junk_voltage_falls_back_rather_than_failing_open(self):
        # ``amps_from_headroom`` floors watts-per-amp at 1.0, so a zero here
        # would not crash — it would saturate the charger to max current on
        # a bad config value. That is the same fails-open shape the peak
        # limit itself was hardened against in this issue. Fall back to the
        # default instead: wrong-and-conservative beats wrong-and-unlimited.
        coord, cfg = _coordinator(fleet={"ev_voltage": 0})
        assert _top_up_amps(coord, cfg) == 23


class TestMaxCurrentIsPerCharger:
    """A ceiling declared on the charger is the charger's, not the fleet's."""

    def test_a_per_charger_max_beats_the_fleet_max(self):
        # 30 kW ceiling − 750 W home = 29250 W at 230 W/A = 127 A, so the
        # result is whichever max applies. The charger says 16.
        coord, cfg = _coordinator(
            fleet={"target_peak_limit": 30.0, "ev_max_current": 32},
            charger={"ev_max_current": 16},
        )
        assert _top_up_amps(coord, cfg) == 16

    def test_the_fleet_max_still_applies_when_the_charger_is_silent(self):
        coord, cfg = _coordinator(fleet={"target_peak_limit": 30.0, "ev_max_current": 32})
        assert _top_up_amps(coord, cfg) == 32

    def test_the_device_rating_still_wins_over_config(self):
        # Unchanged precedence: what the hardware reports it can do is the
        # last word, because config can out-claim the box.
        coord, cfg = _coordinator(
            fleet={"target_peak_limit": 30.0}, charger={"ev_max_current": 16},
        )
        coord._ev_device = MagicMock(max_current=20)
        assert _top_up_amps(coord, cfg) == 20


class TestTheReportedClamp:
    """#716 — the 5 kW ceiling that lands on the 6 A floor, and why.

    Characterisation, not a driver: both of these already hold, because the
    reporter's 2.9x error comes from the phase count and not from the volts.
    They are here so the arithmetic in the issue reply is pinned to running
    code, and so the phases workaround cannot regress unnoticed.
    """

    # Reporter's numbers: 5 kW target peak, 6 A min, 240 V split-phase
    # measured at 7800 W / 32 A = 244 W per amp.
    FLEET = {"target_peak_limit": 5.0, "ev_voltage": 240}

    def test_three_phases_starves_a_single_phase_charger(self):
        # 4250 W of headroom at a believed 3 x 240 = 720 W/A is 5.9 A —
        # under the floor. 6 A x 244 V is the ~1.5 kW the reporter saw.
        coord, cfg = _coordinator(fleet=dict(self.FLEET, ev_phases=3))
        assert _top_up_amps(coord, cfg) == 6

    def test_declaring_one_phase_recovers_the_rate(self):
        # The same headroom at the true 240 W/A is 17.7 A -> 18, about
        # 4.3 kW. This is the workaround available today.
        coord, cfg = _coordinator(fleet=dict(self.FLEET, ev_phases=1))
        assert _top_up_amps(coord, cfg) == 18
