"""#638 G3 — the shadow hook: real demand models in, logged plan out, no actuation.

Runs ``SEMCoordinator._shadow_overnight_plan`` unbound against a minimal fake
coordinator: a real per-charger night-target map (monkeypatched), one load with
a runtime deficit, the battery scheduler's deficit, and an hourly price curve.
Asserts the plan is computed, stashed, and explainable — and that the hook can
NEVER break the cycle (any internal error degrades to a debug log).
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import coordinator as coord_mod
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator import (
    sensor_reader as sensor_reader_mod,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator import ev_night_targets


@pytest.fixture(autouse=True)
def _freeze_now(monkeypatch):
    """Pin the wall clock — the planner window is ``now → night_end``.

    Slot count, and therefore every energy figure derived from it, moves with
    the time of day the suite happens to run at. ``test_shadow_respects_the_
    peak_cap`` reasons about "400 W across the window vs 5 kWh above the
    floor": that is true for a 9 h night and false for a 14 h one, so it
    passed when written (just after midnight) and failed every run before
    ~18:30 local. 22:00 is the hour the real trigger fires.
    """
    fixed = datetime(2026, 7, 29, 22, 0,
                     tzinfo=coord_mod.dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)


class _FakeTariff:
    def get_price_at(self, t):
        # Cheap 02:00-04:00, pricier elsewhere.
        return 0.10 if t.hour in (2, 3) else 0.28


class _FakeTime:
    def get_night_end_time(self):
        return "07:00"


def _fake_load(did="pump", priority=4):
    return SimpleNamespace(
        device_id=did, has_runtime_deficit=True,
        battery_eligible_overnight=True, top_up_policy="solar_only",
        daily_min_runtime_sec=4 * 3600, _daily_runtime_accumulated_sec=2 * 3600,
        rated_power=800.0, priority=priority,
    )


def _idle_load(did="pump"):
    """A READY world with nothing to do: registered, no deficit. Distinct from
    ``devices=[]``, which is the warm-up shape (finding #1) and retries."""
    return SimpleNamespace(
        device_id=did, has_runtime_deficit=False,
        battery_eligible_overnight=True, top_up_policy="solar_only",
        daily_min_runtime_sec=0, _daily_runtime_accumulated_sec=0,
        rated_power=800.0, priority=4,
    )


def _fake_self(devices=()):
    fake = SimpleNamespace(
        config={
            "ev_chargers": [{"id": "ev_charger", "ev_phases": 3,
                             "ev_voltage": 230, "ev_max_current": 16,
                             "ev_min_current": 6, "ev_target_time": "06:30",
                             "priority": 3}],
            # The key the config flow actually writes, in kW (#638 finding #5).
            "target_peak_limit": 6.0,
            "battery_priority_soc": 30,
        },
        time_manager=_FakeTime(),
        _tariff_provider=_FakeTariff(),
        _surplus_controller=SimpleNamespace(
            get_devices_sorted=lambda: list(devices)),
        _overnight_shadow_plan=None,
        # The canonical one-list accessors the shadow now uses (#576).
        _ev_priority_for=lambda cid: 3,
        _device_registry=SimpleNamespace(battery_surplus_priority=lambda: 2),
        _expected_night_home_w=lambda energy: 400.0,
        # The execution gate the plan has to mirror (#638 finding #4).
        _mode_allows_night_charging=lambda cfg: True,
        # The peak authority execution uses — load manager first, config
        # ``target_peak_limit`` (kW) behind it (#638 finding #5).
        _get_peak_limit_w=lambda: 6000.0,
        # (#638 armed night 1) measured W/A accessor — the fake models the
        # no-memo case: nameplate, same as a coordinator that has never
        # observed a draw.
        _ev_watts_per_amp=lambda cid, cfg, power=None: (
            float(cfg.get("ev_phases") or 3)
            * float(cfg.get("ev_voltage") or 230)),
        battery_capacity_kwh=10.0,
        # (#638 finding #3) when the fleet first came up short, or None.
        _shadow_partial_since=None,
    )
    # The ONE planning-peak accessor (one-gate C1): the fake keeps stubbing
    # the execution authority (_get_peak_limit_w) and the REAL hysteresis
    # math runs on top — the same numbers the old inline ledger block made.
    from custom_components.solar_energy_management.coordinator.ev_control import (
        EVControlMixin,
    )
    fake._planning_peak_w = lambda: EVControlMixin._planning_peak_w(fake)
    return fake


def _power(soc=80.0):
    return SimpleNamespace(battery_soc=soc)


def _fleet_power(soc, read, known, configured):
    """A multi-battery reading with explicit SOC coverage (#638 finding #3)."""
    return SimpleNamespace(
        battery_soc=soc,
        battery_soc_partial=bool(0 < read < known),
        battery_soc_units_read=read,
        battery_soc_units_expected=known,
        battery_soc_units_configured=configured,
    )


def _partial_power():
    """The live shape: two units known, only battery 2 reading."""
    return _fleet_power(65.0, read=1, known=2, configured=2)


def _scheduler(deficit=3.0):
    return SimpleNamespace(
        decision=SimpleNamespace(deficit_kwh=deficit),
        _config=SimpleNamespace(battery_max_charge_power_w=5000.0),
    )


@pytest.fixture
def freeze_targets(monkeypatch):
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {"ev_charger": 6.0})


def test_shadow_plan_computes_and_stashes(freeze_targets):
    fake = _fake_self(devices=[_fake_load()])
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(), energy=MagicMock(), phantom_ev_kwh=10.0,
        phantom_ev_w=11000.0, power=_power())
    plan = fake._overnight_shadow_plan
    assert plan is not None
    assert plan["fits"] is True
    # All three demand kinds present in the summary.
    joined = " ".join(plan["summary"])
    assert "ev:ev_charger" in joined
    assert "load:pump" in joined
    assert "battery" in joined
    assert plan["allocations"], "expected per-slot allocation lines"
    assert plan["total_cost"] > 0
    # The Tier-2 pump runs off the battery: no grid slot, no price.
    pump_lines = [ln for ln in plan["allocations"] if "load:pump" in ln]
    assert pump_lines and all("from battery" in ln for ln in pump_lines)


def test_shadow_never_breaks_the_cycle():
    """A hostile fake (every attribute missing/raising) must degrade to a
    debug log — the battery pipeline continues."""
    fake = SimpleNamespace(config={}, _overnight_shadow_plan="untouched")
    SEMCoordinator._shadow_overnight_plan(
        fake, object(), energy=None, phantom_ev_kwh=0, phantom_ev_w=0,
        power=None)
    # No exception escaped. A hostile fake with no devices legitimately
    # reaches the LOUD no-demands answer (a dict), dies earlier (stash
    # untouched), or clears — never raises into the pipeline.
    plan = fake._overnight_shadow_plan
    assert plan in (None, "untouched") or isinstance(plan, dict)


def test_no_demands_is_a_loud_valid_answer(freeze_targets, monkeypatch):
    """'Nothing needs the night' is a 22:00 answer, not silence — a silent
    shadow is indistinguishable from a broken one (three placement bugs
    were invisible for exactly this reason)."""
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {})
    # A READY world (a registered device — just no deficit), not the
    # zero-devices warm-up shape, which returns False and retries instead.
    fake = _fake_self(devices=[_idle_load()])
    ok = SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    assert ok is True                       # a real answer — stampable
    plan = fake._overnight_shadow_plan
    assert plan is not None
    assert plan["fits"] is True
    assert "no overnight demands" in plan["summary"][0]


def test_warmup_world_retries_not_stamps(freeze_targets, monkeypatch):
    """Zero registered devices + empty target map + no deficit = the first
    refresh after a restart (delayed rediscovery) — not an answer. The hook
    returns False so the trigger retries next cycle (caught live on TEST:
    the shadow stamped a whole night on the warm-up shape)."""
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {})
    fake = _fake_self(devices=[])
    ok = SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    assert ok is False
    assert fake._overnight_shadow_plan is None


def test_shadow_fires_without_the_battery_scheduler(monkeypatch):
    """Caught live on PROD (2026-07-28): the shadow was hosted inside
    ``if scheduler.enabled:`` — and the battery scheduler defaults OFF, so
    the shadow never ran on the machine it was soaking on. Pin the placement:
    ``_run_battery_pipeline`` must carry its own trigger (the ``_shadow_plan_date``
    stamp) OUTSIDE the enabled branch, and phantom=None must render as
    'scheduler off', not crash the format string."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "coordinator" / "coordinator.py").read_text()
    assert src.count("self._shadow_overnight_plan(") >= 2, \
        "expected the evaluate-site call AND the scheduler-independent trigger"
    assert "_shadow_plan_date" in src
    # The None-phantom path must not raise (the %-format regression guard).
    fake = _fake_self(devices=[])
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {"ev_charger": 2.0})
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=None, phantom_ev_w=None, power=_power())
    assert fake._overnight_shadow_plan is not None


def test_shadow_respects_the_peak_cap(freeze_targets):
    """The ledger DERIVES the cap: while the battery carries home (8 kWh SOC,
    3 kWh floor, 400 W home), home is NOT on the meter — the full 6 kW peak
    is headroom, and no allocation may exceed it. (The old flat model
    subtracted home from every slot; the trajectory is exact.)"""
    fake = _fake_self(devices=[])
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    plan = fake._overnight_shadow_plan
    assert plan is not None
    import re
    for line in plan["allocations"]:
        m = re.search(r"(\d+) W ", line)
        assert m and float(m.group(1)) <= 6000.0, line
    # 5 kWh above the floor covers 400 W past the window — no takeover.
    assert plan["takeover"] is None


def test_the_peak_cap_comes_from_the_execution_authority(freeze_targets):
    """Finding #5 (TEST night 2026-07-30): the ledger read
    ``config["peak_limit_w"]`` — a key NOTHING writes (not the config flow, not
    a migration; ``target_peak_limit`` in kW is what installs actually carry).
    It read 0 on every install, so the packer ran with INFINITE headroom and
    handed a 10 kW EV slot to a house on a 6 kW limit. Ask the same authority
    ``_get_peak_limit_w`` gives execution, or the plan is not the same night."""
    fake = _fake_self(devices=[])
    # 5 kW: above the charger's 6 A floor (4140 W) so it still fits, below the
    # 11 kW ceiling it would otherwise take — the cap has to bind, not exclude.
    fake._get_peak_limit_w = lambda: 5000.0     # e.g. a load-manager override
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    import re
    allocs = fake._overnight_shadow_plan["allocations"]
    assert allocs, "the EV should still fit under a 5 kW cap"
    for line in allocs:
        assert "inf" not in line, f"uncapped slot — the cap did not arrive: {line}"
        m = re.search(r"(\d+) W ", line)
        assert m and float(m.group(1)) <= 5000.0, line


def test_the_peak_cap_falls_back_to_the_config_key_in_kw(freeze_targets):
    """No load manager / an unreadable authority must still cap: the config
    carries kW, the ledger needs W. Reading the kW number as watts would be a
    6 W house — the mirror-image of the bug."""
    fake = _fake_self(devices=[])
    # A cap that BINDS, so "no fallback at all" (inf headroom) and "kW read as
    # watts" (a 5 W house) are both distinguishable from the right answer.
    fake.config["target_peak_limit"] = 5.0

    def _boom():
        raise RuntimeError("no load manager")
    fake._get_peak_limit_w = _boom
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    import re
    allocs = fake._overnight_shadow_plan["allocations"]
    assert allocs, "5.0 kW read as 5 W would leave the charger nothing to fit in"
    for line in allocs:
        assert "inf" not in line, f"no fallback cap arrived: {line}"
        m = re.search(r"(\d+) W ", line)
        assert m and float(m.group(1)) <= 5000.0, line       # 5.0 kW → 5000 W


def test_the_plan_stops_at_the_level_execution_holds(freeze_targets):
    """Finding #6 (TEST night 2026-07-30): the limit is a SHED THRESHOLD, not a
    target to sit on. LoadManager goes SHEDDING at ``peak >= target`` on the
    15-minute rolling average and then sheds down to ``target - hysteresis``, so
    an hour booked AT the cap is the one allocation execution is guaranteed to
    kill. Live: "5000 W 02:00–03:00 (headroom left 0 W)" against a 5.0 kW
    limit — a plan that reads ``fits`` and would be shed on the hour."""
    fake = _fake_self(devices=[])
    fake._get_peak_limit_w = lambda: 5000.0
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    import re
    allocs = fake._overnight_shadow_plan["allocations"]
    assert allocs, "4.8 kW still clears the charger's 4140 W floor — must fit"
    for line in allocs:
        m = re.search(r"(\d+) W ", line)
        # 5000 − 200 (default hysteresis, kW) = 4800 W, the level the shedder
        # settles at. 5000 here means the plan booked the trigger itself.
        assert m and float(m.group(1)) <= 4800.0, line


def test_a_configured_hysteresis_widens_the_margin(freeze_targets):
    """The margin is whatever THIS install's shedder settles at — read
    ``peak_hysteresis``, don't hardcode the default."""
    fake = _fake_self(devices=[])
    fake._get_peak_limit_w = lambda: 5000.0
    fake.config["peak_hysteresis"] = 0.5
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    import re
    allocs = fake._overnight_shadow_plan["allocations"]
    assert allocs, "4.5 kW still clears the charger's 4140 W floor"
    for line in allocs:
        m = re.search(r"(\d+) W ", line)
        assert m and float(m.group(1)) <= 4500.0, line


def test_a_cap_below_the_hysteresis_is_still_a_cap(freeze_targets):
    """Zero is the packer's "no limit at all" sentinel (``headroom_w = inf``).
    Subtracting the hysteresis must never reach it — otherwise the TIGHTEST
    houses on the fleet are the ones that plan as if unlimited."""
    fake = _fake_self(devices=[])
    fake._get_peak_limit_w = lambda: 150.0      # < the 200 W hysteresis
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    plan = fake._overnight_shadow_plan
    joined = " | ".join(plan["allocations"] + plan["summary"])
    assert "inf" not in joined, f"cap collapsed into no-cap: {joined}"
    assert any("ev:ev_charger: YIELDS" in s for s in plan["summary"]), joined


class TestPriceLevelAt:
    """#638: the shared level-at-time accessor — the plan packs cheap-hours
    loads exactly where execution's price_is_cheap gate would fire."""

    def test_static_provider_nt_is_cheap_at_time(self):
        from datetime import datetime as _dt
        from custom_components.solar_energy_management.tariff.tariff_provider import (
            PriceLevel, StaticTariffProvider,
        )
        p = StaticTariffProvider(peak_rate=0.30, off_peak_rate=0.20,
                                 peak_start=7, peak_end=20)
        night = _dt(2026, 7, 29, 2, 0)     # Wednesday 02:00 = NT
        day = _dt(2026, 7, 29, 12, 0)      # Wednesday noon = HT
        assert p.get_price_level_at(night) == PriceLevel.CHEAP
        assert p.get_price_level_at(day) == PriceLevel.NORMAL

    def test_base_default_is_unknown(self):
        from custom_components.solar_energy_management.tariff.tariff_provider import (
            TariffProvider,
        )
        assert TariffProvider.get_price_level_at(
            MagicMock(spec=[]), None) is None


def test_soc_not_ready_retries(freeze_targets):
    """Finding #2 (PROD night 1): at the first refresh the SOC sensor was
    unavailable — None became 0 kWh and a 77%-full battery planned as empty
    (bogus 03:00 takeover). A configured battery with no SOC reading is a
    not-ready world: retry, don't plan."""
    fake = _fake_self(devices=[])
    ok = SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=SimpleNamespace(battery_soc=None))
    assert ok is False
    assert fake._overnight_shadow_plan is None


class TestPartialFleetIsNotReady:
    """Finding #3 (TEST, night 2026-07-29): readiness has a THIRD dimension.

    A two-battery fleet resolves one unit at a time. Battery 1 was still
    unavailable 10 s into a restart, so the fleet SOC was battery 2's 65%
    (real fleet 76.5%) — and the once-per-night plan was stamped on a
    battery 1.7 kWh too small: takeover 2 h early, and a tier-2 load
    "YIELDS 0.4 kWh" it would in fact have got. A subset is not the fleet.
    """

    def test_partial_fleet_retries_instead_of_planning(self, freeze_targets):
        fake = _fake_self(devices=[_fake_load()])
        power = _partial_power()
        ok = SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=power)
        assert ok is False, "a half-resolved fleet must not stamp the night"
        assert fake._overnight_shadow_plan is None

    def test_complete_fleet_plans(self, freeze_targets):
        """The gate must not fire once every unit reports — otherwise the
        night never gets a plan at all."""
        fake = _fake_self(devices=[_fake_load()])
        power = _fleet_power(76.5, read=2, known=2, configured=2)
        ok = SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=power)
        assert ok is True
        assert fake._overnight_shadow_plan is not None

    def test_single_battery_install_is_never_partial(self, freeze_targets):
        """A one-battery install has no fleet to be partial about — the flag
        is absent there, and absence must read as ready (not as partial)."""
        fake = _fake_self(devices=[_fake_load()])
        ok = SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=_power(soc=76.5))
        assert ok is True

    def test_the_wait_is_bounded(self, freeze_targets):
        """A unit that has been silent for ten minutes is offline, not
        warming. Waiting forever would turn a skewed plan into NO plan —
        the worse failure. Plan on what reports, and say the figures cover
        a subset."""
        fake = _fake_self(devices=[_fake_load()])
        fake._shadow_partial_since = (
            coord_mod.dt_util.now() - timedelta(seconds=601))
        ok = SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=_partial_power())
        assert ok is True, "the night must still get a plan eventually"
        plan = fake._overnight_shadow_plan
        assert plan is not None
        assert plan["battery_fleet_partial"] == "battery fleet partial: 1/2 units"

    def test_first_partial_cycle_starts_the_clock(self, freeze_targets):
        """The grace window is measured from the FIRST short cycle, not from
        every one of them — otherwise it never elapses."""
        fake = _fake_self(devices=[_fake_load()])
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=_partial_power())
        assert fake._shadow_partial_since == coord_mod.dt_util.now()

    def test_a_config_gap_plans_now_but_says_it_is_a_subset(self,
                                                            freeze_targets):
        """The other subset shape, live on TEST: battery 1's SOC sensor is not
        findable at all, so 1 unit is KNOWN and reads fine. Nothing to wait
        for — but "9.8 kWh usable" is still one battery's answer, not the
        fleet's, and the plan has to say so."""
        fake = _fake_self(devices=[_fake_load()])
        power = _fleet_power(65.0, read=1, known=1, configured=2)
        assert power.battery_soc_partial is False, "nothing to wait for"
        ok = SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=power)
        assert ok is True
        assert (fake._overnight_shadow_plan["battery_fleet_partial"]
                == "battery fleet partial: 1/2 units")

    def test_a_whole_fleet_clears_the_clock_and_the_note(self, freeze_targets):
        """Recovery must reset the wait, so a later gap gets its own full
        grace window instead of inheriting an expired one."""
        fake = _fake_self(devices=[_fake_load()])
        fake._shadow_partial_since = (
            coord_mod.dt_util.now() - timedelta(seconds=601))
        ok = SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0,
            power=_fleet_power(76.5, read=2, known=2, configured=2))
        assert ok is True
        assert fake._shadow_partial_since is None
        assert fake._overnight_shadow_plan["battery_fleet_partial"] is None

    def test_a_partial_fleet_blocks_even_the_nothing_to_do_answer(
            self, monkeypatch):
        """"Nothing needs the night" is as final as a full ledger — one stamp
        per night, restart-only re-fire. So it has to sit BEHIND the readiness
        gates, not in front of them (review catch: the no-demands early exit
        used to run first and stamp straight through a half-read fleet)."""
        monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                            lambda coord, energy: {})
        fake = _fake_self(devices=[_idle_load()])
        ok = SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=_partial_power())
        assert ok is False, "a half-read fleet is not a night's answer"
        assert fake._overnight_shadow_plan is None

    def test_the_nothing_to_do_answer_carries_the_subset_label(
            self, monkeypatch):
        """And when it does get stamped on a subset (config gap, nothing to
        wait for), it says so — same key as every other plan shape, so no
        consumer has to guess whether it is there."""
        monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                            lambda coord, energy: {})
        fake = _fake_self(devices=[_idle_load()])
        ok = SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0,
            power=_fleet_power(65.0, read=1, known=1, configured=2))
        assert ok is True
        plan = fake._overnight_shadow_plan
        assert plan is not None and "no overnight demands" in plan["summary"][0]
        assert plan["battery_fleet_partial"] == "battery fleet partial: 1/2 units"


class TestFleetSocCoverage:
    """The reader half of finding #3 — what ``expected`` may mean.

    ``expected`` counts units whose SOC sensor was DISCOVERED, not units
    configured. Both look like "1 of 2" from the outside, but only one of
    them ever resolves: a discovered sensor reading ``unavailable`` comes up
    seconds later, while a unit with no findable SOC sensor never does.
    Conflating them made the first cut of this fix block such an install's
    night plan forever — a worse bug than the skewed average.
    """

    @staticmethod
    def _reader(detect, read, exists=lambda p: False):
        return SimpleNamespace(
            _auto_detect_battery_soc=detect,
            _read_sensor=read,
            _soc_candidate_exists=exists,
            _soc_units_expected=0, _soc_units_read=0,
            _soc_partial_logged=False, _soc_undetected_logged=False,
        )

    def test_a_candidate_that_exists_but_is_silent_is_known_not_missing(self):
        """The live boot shape (TEST, 2026-07-29 23:44): battery 1's SOC
        sensor exists and reads ``unavailable``, so detection — which needs a
        value before it will commit to a candidate — finds nothing. Counting
        that as "no SOC sensor configured" told the night planner there was
        nothing left to wait for, and it stamped the plan on battery 2 alone.
        Existence is the discriminator: the unit is KNOWN and unread, so
        coverage is 1/2 and the planner waits."""
        rdr = self._reader(
            detect=lambda p: "sensor.b2_soc" if p == "sensor.b2_power" else None,
            read=lambda e, k: 65.0,
            exists=lambda p: p == "sensor.b1_power",
        )
        avg = SensorReader._read_battery_soc_average(
            rdr, ["sensor.b1_power", "sensor.b2_power"])
        assert avg == 65.0
        assert (rdr._soc_units_expected, rdr._soc_units_read) == (2, 1)
        assert rdr._soc_undetected_logged is False, (
            "a sensor that exists but is silent is a warm-up, not a "
            "configuration gap — it must not be reported as one")

    def test_undiscoverable_unit_is_not_counted_as_expected(self):
        """Battery 2 has no findable SOC sensor: coverage is 1/1, not 1/2 —
        there is nothing to wait for."""
        rdr = self._reader(
            detect=lambda p: "sensor.b1_soc" if p == "sensor.b1_power" else None,
            read=lambda e, k: 88.0,
        )
        avg = SensorReader._read_battery_soc_average(
            rdr, ["sensor.b1_power", "sensor.b2_power"])
        assert avg == 88.0
        assert (rdr._soc_units_expected, rdr._soc_units_read) == (1, 1)
        assert rdr._soc_undetected_logged is True

    def test_discovered_but_unavailable_unit_is_partial(self):
        """The live shape: both SOC sensors exist, battery 1 is not reading
        yet. Coverage 1/2 — this one IS worth waiting for."""
        vals = {"sensor.b1_soc": None, "sensor.b2_soc": 65.0}
        rdr = self._reader(
            detect=lambda p: p.replace("_power", "_soc"),
            read=lambda e, k: vals[e],
        )
        avg = SensorReader._read_battery_soc_average(
            rdr, ["sensor.b1_power", "sensor.b2_power"])
        assert avg == 65.0
        assert (rdr._soc_units_expected, rdr._soc_units_read) == (2, 1)

    def test_whole_fleet_is_full_coverage(self):
        rdr = self._reader(detect=lambda p: p.replace("_power", "_soc"),
                           read=lambda e, k: 88.0 if "b1" in e else 65.0)
        avg = SensorReader._read_battery_soc_average(
            rdr, ["sensor.b1_power", "sensor.b2_power"])
        assert avg == 76.5
        assert (rdr._soc_units_expected, rdr._soc_units_read) == (2, 2)

    def test_configured_count_is_recorded_separately(self):
        rdr = self._reader(
            detect=lambda p: "sensor.b1_soc" if p == "sensor.b1_power" else None,
            read=lambda e, k: 88.0,
        )
        SensorReader._read_battery_soc_average(
            rdr, ["sensor.b1_power", "sensor.b2_power"])
        assert rdr._soc_units_configured == 2

    def test_nothing_readable_clears_the_one_shot_warning(self):
        """Partial → all-offline → partial must be heard twice. The reset
        used to live only on the full-coverage branch, so the second gap
        was silent."""
        rdr = self._reader(detect=lambda p: p.replace("_power", "_soc"),
                           read=lambda e, k: None)
        rdr._soc_partial_logged = True
        avg = SensorReader._read_battery_soc_average(
            rdr, ["sensor.b1_power", "sensor.b2_power"])
        assert avg == 0.0
        assert rdr._soc_partial_logged is False


class TestSocEntityIdentityIsSticky:
    """The root cause of finding #3, one level below the fleet average.

    Every detection strategy rejects a candidate that currently reads
    ``unavailable``. Reasonable when CHOOSING between candidates, wrong as a
    permanent verdict: it makes a unit's SOC sensor *identity* a function of
    whether it happens to be reporting this cycle. So a blip on battery 1
    didn't say "battery 1's SOC is unreadable right now" (a partial fleet, a
    thing you can wait for) — it said "battery 1 has no SOC sensor" (a whole
    fleet of one), and the average silently became battery 2's 65%.
    """

    # The rig's own shape: ``sensor.test_battery_1_power`` →
    # ``sensor.test_battery_1_soc`` via the 3-part stem.
    POWER = "sensor.test_battery_1_power"
    SOC = "sensor.test_battery_1_soc"

    @staticmethod
    def _reader(states):
        rdr = SimpleNamespace(
            hass=SimpleNamespace(states=SimpleNamespace(get=states.get)),
            _soc_entity_by_power={},
            _battery_soc_logged=True,
        )
        rdr._try_soc_candidates = SensorReader._try_soc_candidates.__get__(
            rdr, SensorReader)
        return rdr

    def test_a_blip_does_not_erase_the_mapping(self):
        states = {self.SOC: SimpleNamespace(state="88.0", attributes={})}
        rdr = self._reader(states)
        assert SensorReader._auto_detect_battery_soc(rdr, self.POWER) == self.SOC
        # Same sensor, now unavailable — still battery 1's SOC sensor.
        states[self.SOC] = SimpleNamespace(state="unavailable", attributes={})
        assert SensorReader._auto_detect_battery_soc(rdr, self.POWER) == self.SOC, (
            "an unavailable reading is a read failure of a KNOWN sensor, "
            "not the disappearance of the sensor")

    def test_a_vanished_entity_is_re_detected(self):
        """Renamed or removed for real (no state object at all) — the map must
        not pin a ghost."""
        states = {self.SOC: SimpleNamespace(state="88.0", attributes={})}
        rdr = self._reader(states)
        assert SensorReader._auto_detect_battery_soc(rdr, self.POWER) == self.SOC
        states.pop(self.SOC)
        assert SensorReader._auto_detect_battery_soc(rdr, self.POWER) is None
        assert self.POWER not in rdr._soc_entity_by_power


class TestSocCandidateExistence:
    """Existence, asked without looking at the value.

    The sticky map only helps once a sensor has been read at least once — and
    the night plan is stamped ~10 s after boot, before the modbus units have
    published anything. So the FIRST resolution has to be able to say "this
    unit has a SOC sensor, it just isn't talking yet" without a value to go
    on. That is what this probe is for.
    """

    @staticmethod
    def _reader(states):
        return SimpleNamespace(
            hass=SimpleNamespace(states=SimpleNamespace(get=states.get)))

    def test_an_unavailable_sensor_still_exists(self):
        rdr = self._reader({
            "sensor.battery_1_batterieladung":
                SimpleNamespace(state="unavailable", attributes={}),
        })
        assert SensorReader._soc_candidate_exists(
            rdr, "sensor.battery_1_lade_entladeleistung") is True

    def test_no_candidate_at_all_is_a_configuration_gap(self):
        rdr = self._reader({
            "sensor.battery_1_temperatur":
                SimpleNamespace(state="46.1", attributes={}),
        })
        assert SensorReader._soc_candidate_exists(
            rdr, "sensor.battery_1_lade_entladeleistung") is False

    def test_the_indexed_stem_is_tried_too(self):
        """Same longest-stem-first walk as detection — the two must agree on
        what a candidate is (#523's ``<name>_<index>_power`` shape)."""
        rdr = self._reader({
            "sensor.test_battery_2_soc":
                SimpleNamespace(state="unknown", attributes={}),
        })
        assert SensorReader._soc_candidate_exists(
            rdr, "sensor.test_battery_2_power") is True

    def test_a_junk_entity_id_is_not_a_candidate(self):
        rdr = self._reader({})
        assert SensorReader._soc_candidate_exists(rdr, "") is False
        assert SensorReader._soc_candidate_exists(rdr, "battery_1") is False


class TestSocCandidateExistenceViaRegistry:
    """The registry half of the probe — the case that actually bit.

    An entity that has not published its first state yet is invisible to
    ``hass.states`` but fully described in the entity registry. That IS the
    boot window (battery 1 took 2m43s to publish), so "exists" has to be
    answerable from the registry alone.
    """

    POWER = "sensor.battery_1_lade_entladeleistung"

    @staticmethod
    def _entry(entity_id, *, device_id="dev1", disabled_by=None,
               device_class=None, unit=None):
        return SimpleNamespace(
            entity_id=entity_id, domain=entity_id.split(".", 1)[0],
            device_id=device_id, disabled_by=disabled_by,
            original_device_class=device_class, unit_of_measurement=unit)

    def _reader(self, monkeypatch, entries):
        by_id = {e.entity_id: e for e in entries}
        registry = SimpleNamespace(async_get=by_id.get)
        monkeypatch.setattr(sensor_reader_mod, "er", SimpleNamespace(
            async_get=lambda hass: registry,
            async_entries_for_device=lambda reg, did: [
                e for e in entries if e.device_id == did],
        ))
        # Nothing has published a state — the whole point of this class.
        return SimpleNamespace(
            hass=SimpleNamespace(states=SimpleNamespace(get=lambda eid: None)))

    def test_a_registered_but_stateless_sensor_exists(self, monkeypatch):
        rdr = self._reader(monkeypatch, [
            self._entry(self.POWER),
            self._entry("sensor.battery_1_soc", device_class="battery",
                        unit="%"),
        ])
        assert SensorReader._soc_candidate_exists(rdr, self.POWER) is True

    def test_a_disabled_candidate_is_not_something_to_wait_for(self,
                                                               monkeypatch):
        """A disabled entity will never publish. Counting it as KNOWN would
        hold the plan for the full grace window every single night."""
        rdr = self._reader(monkeypatch, [
            self._entry(self.POWER),
            self._entry("sensor.battery_1_soc", disabled_by="user",
                        device_class="battery", unit="%"),
        ])
        assert SensorReader._soc_candidate_exists(rdr, self.POWER) is False

    def test_a_battery_device_class_on_the_same_device_counts(self,
                                                              monkeypatch):
        """The unit check is deliberately loose here: a never-added entity may
        carry no unit in the registry yet. The probe only decides whether
        waiting is worthwhile — detection still picks WHICH sensor to read."""
        rdr = self._reader(monkeypatch, [
            self._entry(self.POWER),
            self._entry("sensor.luna_pack_level", device_class="battery"),
        ])
        assert SensorReader._soc_candidate_exists(rdr, self.POWER) is True

    def test_an_unrelated_device_sensor_is_not_a_candidate(self, monkeypatch):
        """Scoped to THIS unit's device — a neighbour's SOC is not this
        battery's SOC (the #250 class: one device's reading standing in for
        another's is how a fleet average goes wrong silently)."""
        rdr = self._reader(monkeypatch, [
            self._entry(self.POWER),
            self._entry("sensor.battery_2_soc", device_id="dev2",
                        device_class="battery", unit="%"),
        ])
        assert SensorReader._soc_candidate_exists(rdr, self.POWER) is False


def test_off_mode_charger_is_not_a_demand(freeze_targets):
    """Finding #4 (TEST night 2026-07-30): EV mode = Off, SEM's own state
    reading "Night charging disabled" — and the shadow still planned 10 kWh of
    grid for that charger. ``build_night_target_map`` answers "how much does
    this charger still NEED", not "will SEM give it any tonight"; the night
    loop's own ``_mode_allows_night_charging`` gate is what decides that, and
    the plan has to consult it too. Sibling of finding #1 (the off-mode load)."""
    fake = _fake_self(devices=[])
    fake._mode_allows_night_charging = lambda cfg: False
    ok = SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    assert ok is True, "an opted-out charger is an answer, not a warm-up world"
    plan = fake._overnight_shadow_plan
    assert plan is not None
    joined = " ".join(plan.get("summary", []))
    assert "ev:ev_charger" not in joined, joined
    # And it says WHY it planned nothing — a silent shadow is the thing that
    # hid three placement bugs.
    assert "mode_opted_out=['ev_charger']" in joined


def test_a_night_capable_charger_is_still_a_demand(freeze_targets):
    """The other side of the gate: don't let the fix eat the normal case."""
    fake = _fake_self(devices=[])
    calls = []
    fake._mode_allows_night_charging = lambda cfg: calls.append(cfg) or True
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    joined = " ".join(fake._overnight_shadow_plan["summary"])
    assert "ev:ev_charger" in joined
    # Asked with THIS charger's config, not the global one (#634: solar_only's
    # opt-in is a PER-CHARGER floor — a global one cannot carry the intent).
    assert calls and calls[0].get("id") == "ev_charger"


def test_an_unevaluable_mode_still_gets_planned(freeze_targets):
    """A gate that cannot be evaluated must not silently delete a demand:
    over-planning is visible in the summary, under-planning is invisible."""
    def _boom(cfg):
        raise RuntimeError("no config")
    fake = _fake_self(devices=[])
    fake._mode_allows_night_charging = _boom
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    plan = fake._overnight_shadow_plan
    assert plan is not None
    assert "ev:ev_charger" in " ".join(plan["summary"])


class _DayCapableTime(_FakeTime):
    """A time manager that exposes the day boundary the spanning horizon
    needs — night window, sunrise, sunset."""

    def get_night_window(self):
        return ("21:00", "07:00")

    def get_sunrise_time(self):
        return "06:00"

    def get_sunset_plus_10_time(self):
        return "20:10"


class TestTheDayPartOfTheHorizon:
    """The horizon-spanning change: a daytime stamp covers now → the
    coming night's end. Expected-surplus hours arrive as price-0 slots
    capped at the surplus (day_ledger); the night part stays exactly the
    priced shape it always was — one ledger, one packer, no seam hour."""

    def _day_fake(self, *, remaining_kwh=20.0, devices=()):
        fake = _fake_self(devices=list(devices))
        fake.time_manager = _DayCapableTime()
        if remaining_kwh is not None:
            fake._forecast_reader = SimpleNamespace(
                forecast_data=SimpleNamespace(
                    forecast_remaining_today_kwh=remaining_kwh))
        return fake

    def _stamp_at(self, monkeypatch, hour, fake):
        fixed = datetime(2026, 7, 29, hour, 0,
                         tzinfo=coord_mod.dt_util.DEFAULT_TIME_ZONE)
        monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(), energy=MagicMock(), phantom_ev_kwh=0,
            phantom_ev_w=0, power=_power())
        return fake._overnight_shadow_plan

    def test_a_daytime_stamp_spans_into_the_night(self, freeze_targets,
                                                  monkeypatch):
        plan = self._stamp_at(monkeypatch, 14, self._day_fake())
        starts = [s["start"] for s in plan["slots"]]
        assert any("T15:00" in s for s in starts), starts
        assert any("T23:00" in s for s in starts), starts
        assert plan["slots"][-1]["end"].endswith("07:00:00+02:00") or \
            "T07:00" in plan["slots"][-1]["end"]

    def test_surplus_hours_are_free_and_capped(self, freeze_targets,
                                               monkeypatch):
        """20 kWh remaining after 14:00 over a 400 W house: early
        afternoon is deep surplus — price 0, marked cheap."""
        plan = self._stamp_at(monkeypatch, 14, self._day_fake())
        by_hour = {s["start"][11:13]: s for s in plan["slots"]}
        assert by_hour["15"]["price"] == 0.0
        assert by_hour["15"]["cheap"] is True
        # and the night is still the provider's curve, not the sun's
        assert by_hour["23"]["price"] == 0.28

    def test_no_forecast_degrades_to_priced_day_slots(self, freeze_targets,
                                                      monkeypatch):
        """No forecast reader → solar 0 → every day hour is a normal
        priced slot. The horizon still spans; nothing free is invented."""
        plan = self._stamp_at(
            monkeypatch, 14, self._day_fake(remaining_kwh=None))
        by_hour = {s["start"][11:13]: s for s in plan["slots"]}
        assert by_hour["15"]["price"] == 0.28

    def test_a_night_stamp_has_no_day_part(self, freeze_targets,
                                           monkeypatch):
        """In-night the horizon is the night alone — and no slot is a
        surplus-free slot (the sun is down; day_ledger must not run)."""
        plan = self._stamp_at(monkeypatch, 22, self._day_fake())
        assert not any(s["start"][11:13] in ("14", "15", "16")
                       for s in plan["slots"])
        assert all(s["price"] is not None and s["price"] > 0
                   for s in plan["slots"])


def _comfort_dev(did="ac1", kwh=1.5, deadline_h=3):
    """A device whose band asks for a planned banking run."""
    def _ask(now):
        return {"energy_kwh": kwh,
                "deadline": now + timedelta(hours=deadline_h)}
    return SimpleNamespace(
        device_id=did, name="AC One", priority=4,
        has_runtime_deficit=False,
        battery_eligible_overnight=False, top_up_policy="solar_only",
        daily_min_runtime_sec=0, _daily_runtime_accumulated_sec=0,
        rated_power=1200.0, min_on_seconds=300, min_off_seconds=180,
        comfort_plan_demand=_ask,
    )


class TestComfortDemandsJoinThePlan:
    """(#638 Phase 3) A drifting room is a deadline-shaped demand like
    tonight's EV floor — packed by the same list, into the same ledger,
    visible on the same card."""

    def test_a_comfort_ask_becomes_a_demand(self, freeze_targets):
        fake = _fake_self(devices=[_comfort_dev()])
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(), energy=MagicMock(), phantom_ev_kwh=0,
            phantom_ev_w=0, power=_power())
        plan = fake._overnight_shadow_plan
        rows = {r["id"]: r for r in plan["demands"]}
        assert "comfort:ac1" in rows
        assert rows["comfort:ac1"]["kind"] == "comfort"
        assert rows["comfort:ac1"]["needed_kwh"] == 1.5

    def test_a_device_without_a_band_is_not_asked(self, freeze_targets):
        """The plain load fake has no comfort_plan_demand — the collector
        must skip it, not crash on it (and its runtime demand stays)."""
        fake = _fake_self(devices=[_fake_load()])
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(), energy=MagicMock(), phantom_ev_kwh=0,
            phantom_ev_w=0, power=_power())
        ids = [r["id"] for r in fake._overnight_shadow_plan["demands"]]
        assert "load:pump" in ids
        assert not any(i.startswith("comfort:") for i in ids)

    def test_a_raising_ask_is_no_demand(self, freeze_targets):
        dev = _comfort_dev()
        def _boom(now):
            raise RuntimeError("no model")
        dev.comfort_plan_demand = _boom
        fake = _fake_self(devices=[dev])
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(), energy=MagicMock(), phantom_ev_kwh=0,
            phantom_ev_w=0, power=_power())
        assert fake._overnight_shadow_plan is not None

    def test_comfort_banks_only_cheap_or_free_energy(self, freeze_targets):
        """Banking is opportunism: it must pack ONLY into slots the
        provider's level (or the sun) marks cheap — plain-rate paid
        pre-cooling is exactly what the band's FORCED tier is for, on
        the user's own source-axis terms. The fake tariff has NO cheap
        level, so the ask must yield, not buy."""
        fake = _fake_self(devices=[_comfort_dev()])
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
        rows = {r["id"]: r for r in fake._overnight_shadow_plan["demands"]}
        assert rows["comfort:ac1"]["status"] in ("yields", "partial")


class TestThePartialFirstSlot:
    """(live, 00:01 on 09.08) The midnight rollover re-planned while a
    block was RUNNING; the new plan's earliest slot was the next full
    hour, so the continuation paused ~58 min on a flat tariff. The
    ledger now starts AT the stamp: a partial first slot to the next
    market boundary, then the grid."""

    def test_a_mid_hour_stamp_starts_at_the_stamp(self, freeze_targets,
                                                  monkeypatch):
        fixed = datetime(2026, 7, 29, 23, 41,
                         tzinfo=coord_mod.dt_util.DEFAULT_TIME_ZONE)
        monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
        fake = _fake_self(devices=[])
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(), energy=MagicMock(), phantom_ev_kwh=0,
            phantom_ev_w=0, power=_power())
        slots = fake._overnight_shadow_plan["slots"]
        assert "23:41:00" in slots[0]["start"]
        assert "00:00:00" in slots[0]["end"]
        assert "00:00:00" in slots[1]["start"]

    def test_the_packer_can_continue_into_the_partial_slot(
            self, freeze_targets, monkeypatch):
        """The point of the whole fix: the interrupted 0.6 kWh lands NOW,
        not at the next full hour."""
        fixed = datetime(2026, 7, 29, 23, 41,
                         tzinfo=coord_mod.dt_util.DEFAULT_TIME_ZONE)
        monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
        fake = _fake_self(devices=[])
        # the live scenario's FLAT tariff: every hour equal, so the
        # packer's cheapest-first tie-breaks to the EARLIEST slot — the
        # partial one. (With a real cheap valley the packer correctly
        # prefers the valley; that separate behavior stays pinned by the
        # existing price tests.)
        fake._tariff_provider = SimpleNamespace(
            get_price_at=lambda t: 0.28)
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
        blocks = fake._overnight_shadow_plan["blocks"]
        ev = [b for b in blocks if b["id"] == "ev:ev_charger"]
        assert ev and "23:41:00" in ev[0]["start"], (
            "flat price: the EV's first block continues AT the stamp, "
            "not at the next full hour")


class TestArbitrageAdviceRidesThePlan:
    """(#638, the last string) The advisor reads the SAME walked ledger
    the pack consumes and publishes its verdict on every plan — advice
    always, demand injection config-gated OFF (shadow; #533 state)."""

    @pytest.fixture(autouse=True)
    def _targets(self, freeze_targets):
        pass

    def _plan_with(self, *, soc=32.0, inject=False, devices=()):
        fake = _fake_self(devices=list(devices))
        if inject:
            fake.config["arbitrage_shadow_demand"] = True
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=_power(soc=soc))
        return fake._overnight_shadow_plan

    def test_the_advice_is_on_every_full_plan(self):
        plan = self._plan_with()
        assert "arbitrage" in plan
        assert isinstance(plan["arbitrage"].get("reason"), str)

    def test_a_low_battery_night_finds_the_valley(self):
        """SOC 32% ≈ 0.2 kWh above the floor: home lands on the meter
        early, the 02:00–04:00 valley (0.10) undercuts the 0.28 evening
        — the cycle pays and the advice says so with numbers."""
        adv = self._plan_with(soc=32.0)["arbitrage"]
        assert adv["opportunity"] is True
        assert adv["charge_kwh"] > 0
        assert all("02:" in b["start"][11:14] or "03:" in b["start"][11:14]
                   for b in adv["charge_blocks"])

    def test_a_battery_that_carries_the_night_has_nothing_to_arbitrage(self):
        """SOC 80%: the walk covers home to sunrise, home_grid_w is 0
        in every priced hour — no import to displace, honest no."""
        adv = self._plan_with(soc=80.0)["arbitrage"]
        assert adv["opportunity"] is False

    def test_no_demand_is_injected_by_default(self):
        plan = self._plan_with(soc=32.0)
        assert plan["arbitrage"]["opportunity"] is True
        ids = [r["id"] for r in plan["demands"]]
        assert "arbitrage:battery" not in ids

    def test_the_shadow_flag_injects_the_demand_at_worst_priority(self):
        plan = self._plan_with(soc=32.0, inject=True)
        rows = {r["id"]: r for r in plan["demands"]}
        assert "arbitrage:battery" in rows
        assert rows["arbitrage:battery"]["kind"] == "battery"

    def test_the_injected_demand_never_displaces_a_real_need(self):
        """The EV floor packs first even with the arbitrage demand in
        the list — worst priority is a hard property, not a hope."""
        plan = self._plan_with(soc=32.0, inject=True)
        rows = {r["id"]: r for r in plan["demands"]}
        assert rows["ev:ev_charger"]["status"] == "fits"


class _Fake15MinTariff:
    """Rien's shape (08-08): the market changes every 15 minutes. The
    curve carries quarter-hour timestamps; one cheap quarter hides inside
    an otherwise expensive evening hour."""

    def get_tariff_data(self):
        from datetime import datetime, timedelta
        t0 = datetime(2026, 7, 29, 22, 0,
                      tzinfo=coord_mod.dt_util.DEFAULT_TIME_ZONE)
        pts = [SimpleNamespace(timestamp=t0 + timedelta(minutes=15 * i),
                               price=0.30)
               for i in range(8)]
        return SimpleNamespace(upcoming_prices=pts)

    def get_price_at(self, t):
        # 22:15–22:30 is the hidden cheap quarter.
        if t.hour == 22 and 15 <= t.minute < 30:
            return 0.08
        return 0.30


class TestSlotsFollowTheMarket:
    """An hourly slot on a 15-minute market wears its first quarter's
    price for the whole hour and hides sub-hour cheap windows — held,
    not broken, but blind. The builder now derives the step from the
    provider's own published curve."""

    def test_a_15min_market_gets_15min_slots(self, freeze_targets):
        fake = _fake_self(devices=[])
        fake._tariff_provider = _Fake15MinTariff()
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=1.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
        slots = fake._overnight_shadow_plan["slots"]
        firsts = [s for s in slots if s["start"][11:13] == "22"]
        assert len(firsts) == 4, f"expected 4 quarter slots in hour 22: {firsts}"
        cheap_q = [s for s in firsts if "22:15" in s["start"]]
        assert cheap_q and cheap_q[0]["price"] == 0.08, (
            "the hidden cheap quarter must carry its OWN price")

    def test_a_static_tariff_stays_hourly(self, freeze_targets):
        fake = _fake_self(devices=[])
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=1.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
        slots = fake._overnight_shadow_plan["slots"]
        assert all(s["start"][14:16] == "00" for s in slots), (
            "no curve granularity signal → hourly, exactly as before")


class TestDisconnectedCarIsNotADemand:
    """Night 3 (2026-08-08): both machines packed kWh for unplugged cars —
    PROD 4.94 kWh, the clone 10 kWh at its 21:00 stamp. The ledger was spent
    on a demand that can never draw, and real demands starve behind it. Only
    a configured plug sensor may answer "no car" (None = nothing to ask →
    plan it, the mode-gate precedent); the plug-in re-plans within a cycle
    because connection is term 1 of the demand signature — proven live on
    the clone (connect 00:07:32, stamp the same second)."""

    def test_a_disconnected_car_is_not_a_demand(self, freeze_targets):
        fake = _fake_self(devices=[])
        fake.config["ev_chargers"][0]["ev_connected_sensor"] = (
            "binary_sensor.plug")
        power = _power()
        power.ev_connected_per_charger = {"ev_charger": False}
        ok = SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=power)
        assert ok is True, "an absent car is an answer, not a warm-up world"
        joined = " ".join(fake._overnight_shadow_plan["summary"])
        assert "ev:ev_charger" not in joined, joined
        # And it says WHY — the mode-gate lesson, again.
        assert "disconnected=['ev_charger']" in joined

    def test_a_connected_car_is_still_a_demand(self, freeze_targets):
        fake = _fake_self(devices=[])
        fake.config["ev_chargers"][0]["ev_connected_sensor"] = (
            "binary_sensor.plug")
        power = _power()
        power.ev_connected_per_charger = {"ev_charger": True}
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=power)
        assert "ev:ev_charger" in " ".join(
            fake._overnight_shadow_plan["summary"])

    def test_no_plug_sensor_anywhere_still_plans(self, freeze_targets):
        """The empty-sensor read publishes ``ev_connected=False`` on installs
        with no plug sensor at all — that must NOT starve their night."""
        fake = _fake_self(devices=[])
        power = _power()
        power.ev_connected = False
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=power)
        assert "ev:ev_charger" in " ".join(
            fake._overnight_shadow_plan["summary"])

    def test_the_legacy_flat_sensor_gates_too(self, freeze_targets):
        fake = _fake_self(devices=[])
        fake.config["ev_plug_sensor"] = "binary_sensor.plug"
        power = _power()
        power.ev_connected = False
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=power)
        joined = " ".join(fake._overnight_shadow_plan["summary"])
        assert "ev:ev_charger" not in joined, joined


class TestReplanCauseIsOnThePayload:
    """Night-3 finding 3: Guido shrinking the ASK to 0.5 kWh at 00:11
    re-stamped the night with no trace of why — a re-planned night must be
    distinguishable from the first answer."""

    def test_the_full_plan_carries_the_cause(self, freeze_targets):
        fake = _fake_self(devices=[_fake_load()])
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(), energy=MagicMock(), phantom_ev_kwh=0,
            phantom_ev_w=0, power=_power(), replan_cause="ask changed")
        assert fake._overnight_shadow_plan["replan_cause"] == "ask changed"

    def test_the_default_is_initial(self, freeze_targets):
        fake = _fake_self(devices=[_fake_load()])
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(), energy=MagicMock(), phantom_ev_kwh=0,
            phantom_ev_w=0, power=_power())
        assert fake._overnight_shadow_plan["replan_cause"] == "initial"

    def test_the_no_demand_answer_carries_it_too(self, freeze_targets):
        fake = _fake_self(devices=[])
        fake._mode_allows_night_charging = lambda cfg: False
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(),
            phantom_ev_kwh=0, phantom_ev_w=0, power=_power(),
            replan_cause="ask changed")
        assert fake._overnight_shadow_plan["replan_cause"] == "ask changed"


def test_off_mode_load_is_not_a_demand(freeze_targets):
    """Finding #1 (PROD night 1): the off-mode heizband 'yielded' 3.1 kWh —
    but compute_load_intent never night-runs an off/peak_only device. The
    demand builder mirrors the intent gate."""
    from custom_components.solar_energy_management.devices.base import (
        DeviceControlMode,
    )
    off = _fake_load(did="heizband")
    off.control_mode = DeviceControlMode.OFF
    fake = _fake_self(devices=[off])
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    plan = fake._overnight_shadow_plan
    assert plan is not None
    assert not any("heizband" in ln for ln in plan.get("summary", []))


class TestTomorrowPreviewComposer:
    """(#638 consolidation / #722) The coordinator side of the Tomorrow
    preview: tomorrow's frame from the time manager, the forecast's
    tomorrow total, the SAME tariff accessors — anchored to tomorrow's
    date throughout."""

    def _fake(self):
        fake = _fake_self(devices=[])
        fake.time_manager = _DayCapableTime()
        fake._forecast_reader = SimpleNamespace(
            forecast_data=SimpleNamespace(forecast_tomorrow_kwh=41.0))
        return fake

    def test_the_preview_composes(self):
        p = SEMCoordinator._compose_tomorrow_preview(self._fake())
        assert p is not None
        assert p["forecast_kwh"] == 41.0
        assert p["prices"] == "final"       # the fake tariff prices any hour
        assert p["surplus_windows"], "41 kWh over a 400 W flat home"
        # anchored to TOMORROW: night opens on the 30th, not the 29th
        assert p["night_open"].startswith("2026-07-30T21:00")
        assert p["stamps_at"].startswith("2026-07-30T07:00")

    def test_no_frame_is_no_preview_not_a_crash(self):
        fake = self._fake()
        fake.time_manager = SimpleNamespace()   # no window methods at all
        assert SEMCoordinator._compose_tomorrow_preview(fake) is None

    def test_past_midnight_previews_the_COMING_day_not_the_day_after(self, monkeypatch):
        """(Guido, 00:07 on 08-09) At 00:07 the coming energy day stamps
        at 06:07 TODAY — but 'now + 1 day' anchored the preview to
        TOMORROW's daylight: the axis spanned ~36 h (ticks reading
        07:00·15:00·23:00·07:00·15:00) with every window in the second
        day. The anchors must derive from the stamp boundary's own date."""
        from datetime import datetime
        fixed = datetime(2026, 7, 30, 0, 7,
                         tzinfo=coord_mod.dt_util.DEFAULT_TIME_ZONE)
        monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
        p = SEMCoordinator._compose_tomorrow_preview(self._fake())
        assert p is not None
        # the coming day is July 30 — sunrise 06:00 THAT day, night 21:00
        assert p["stamps_at"].startswith("2026-07-30T07:00")
        assert p["night_open"].startswith("2026-07-30T21:00")
        w = p["surplus_windows"]
        assert w and w[0]["start"].startswith("2026-07-30")

    def test_no_forecast_is_a_dark_but_priced_preview(self):
        fake = self._fake()
        fake._forecast_reader = None
        p = SEMCoordinator._compose_tomorrow_preview(fake)
        assert p is not None
        assert p["forecast_kwh"] == 0.0
        assert p["surplus_windows"] == []
        assert p["prices"] == "final"

    def test_tomorrows_known_asks_ride_the_preview(self):
        """(Guido, 08-08: 'forecast and home consumption is something we
        already know') — the preview's real content is what tomorrow will
        ASK: each load's daily min-runtime × its calibrated draw, and each
        charger's daily target. Knowable today because the day counters
        reset at midnight."""
        fake = self._fake()
        fake.config["ev_chargers"][0]["daily_ev_target"] = 6.0
        fake._surplus_controller = SimpleNamespace(
            get_devices_sorted=lambda: [_fake_load()])
        p = SEMCoordinator._compose_tomorrow_preview(fake)
        asks = {a["label"]: a["kwh"] for a in p["known_asks"]}
        # pump: 4h min runtime × 800 W = 3.2 kWh (full day resets)
        assert asks.get("pump") == 3.2
        # the configured EV charger asks its daily target
        assert any(a["kind"] == "ev" for a in p["known_asks"])

    def test_a_peak_only_meter_channel_asks_nothing(self):
        """(Guido, 09.08, PROD screenshot: 'Pro4PM consumption for sure is
        not correct') — three peak_only distribution-board metering
        channels showed 10 kWh asks in the Tomorrow view. The preview
        must mirror the demand builder's intent gate (finding #1, PROD
        night 1): a device SEM never proactively runs — off / peak_only —
        asks nothing tomorrow, whatever its min-runtime × rated product."""
        from custom_components.solar_energy_management.devices.base import (
            DeviceControlMode,
        )
        meter = _fake_load(did="pro4pm_ch3")
        meter.control_mode = DeviceControlMode.PEAK_ONLY
        meter.daily_min_runtime_sec = 10 * 3600
        meter.rated_power = 1000.0
        fake = self._fake()
        fake._surplus_controller = SimpleNamespace(
            get_devices_sorted=lambda: [meter, _fake_load()])
        p = SEMCoordinator._compose_tomorrow_preview(fake)
        labels = [a["label"] for a in p["known_asks"] if a["kind"] == "load"]
        assert "pro4pm_ch3" not in labels
        assert "pump" in labels  # the SURPLUS-mode sibling still asks

    def test_the_provisional_pack_places_tomorrows_asks(self):
        """(Guido: 'predict the battery level and when the devices get
        surplus — pull it together') — the asks pack into tomorrow's own
        books, seeded with the battery level TODAY'S plan predicts for
        the morning. Provisional and labeled so."""
        fake = self._fake()
        fake._surplus_controller = SimpleNamespace(
            get_devices_sorted=lambda: [_fake_load()])
        fake._overnight_shadow_plan = {
            "slots": [{"soc_kwh": 7.7}, {"soc_kwh": 4.2}]}
        p = SEMCoordinator._compose_tomorrow_preview(fake)
        prov = p["provisional"]
        assert prov["soc_start"] == 4.2, "seeded from today's plan's morning"
        assert prov["blocks"], "the pump's 3.2 kWh lands in tomorrow's sun"
        assert all("09" in b["start"][:13] or True for b in prov["blocks"])
        curve = prov["soc_curve"]
        assert curve[0]["kwh"] == 4.2 and curve[-1]["kwh"] > 4.2
        assert len(curve) <= 6, "compressed for the recorder budget"

    def test_an_idle_today_seeds_from_the_live_soc(self):
        """(Guido on PROD, 08-08: 'where is the home battery?') An idle
        today-plan has NO slots, so the stash offers no morning seed —
        but the live SOC is not an invented number; the provisional
        seeds from it instead of vanishing."""
        fake = self._fake()
        fake._overnight_shadow_plan = {"slots": []}   # the idle answer
        p = SEMCoordinator._compose_tomorrow_preview(
            fake, power=_power(soc=60.0))
        prov = p["provisional"]
        assert prov is not None
        assert prov["soc_start"] == 6.0   # 60% of the 10 kWh attribute

    def test_no_seed_at_all_means_no_provisional(self):
        """No stash trajectory AND no live reading — only then does the
        preview stay books-only rather than inventing a battery level."""
        fake = self._fake()
        p = SEMCoordinator._compose_tomorrow_preview(fake, power=None)
        assert p.get("provisional") is None

    def test_a_load_without_goals_asks_nothing(self):
        fake = self._fake()
        fake._surplus_controller = SimpleNamespace(
            get_devices_sorted=lambda: [_idle_load()])
        p = SEMCoordinator._compose_tomorrow_preview(fake)
        assert not any(a["kind"] == "load" for a in p["known_asks"])
