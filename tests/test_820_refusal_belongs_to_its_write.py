"""#820 (05.10.2026) — a refusal belongs to the write it judged.

@ArneGollin1987 on 2.2.0-beta.8+: "SEM still said the inverter did not take
the limit, though it did follow different limits during pacing time".

The writer judges each write: the register either shows the sent cap
(taken) or it does not within the window (refused). That verdict is about
ONE write — ``last_written_w``. The pacing line on the Battery tab reads it
as "what pacing is doing now". So once one write was lost (a dropped Modbus
write, a template script that was still running), "the inverter refused the
limit" stayed on the card while the register sat at exactly the cap SEM
wanted: the wish came back to the register's value, there was nothing left
to write, and the old verdict was all the action could say.

Bug class 83 (a latch scoped wider than the evidence that set it): the
verdict's key is the write; the reader's key is the current wish. When the
register already holds the wish, the action is ``held`` whatever an older
write's verdict was. A register away from the wish still says
``write_refused`` — the alarm is kept where it is true.
"""
from __future__ import annotations

import asyncio
import random
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.charge_pacing import (
    ChargePacingWriter,
)
from custom_components.solar_energy_management.utils.log_gate import (
    reset_log_gate,
)

ENTITY = "number.battery_max_charge_power_inv_1"


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class SungrowTemplateNumber:
    """Arne's mkaiser template number: min 10, max 9720, step 100. Its
    set_value writes register 33046 with value/10 and refreshes the sensor
    at once, so a write that lands shows on the next read. ``drop`` loses
    the next N writes (a Modbus error, or "Already running")."""

    def __init__(self, value: float):
        self.state = SimpleNamespace(
            state=str(float(value)),
            attributes={"min": 10.0, "max": 9720.0, "step": 100.0,
                        "unit_of_measurement": "W"})
        self.writes: list[float] = []
        self.drop = 0

    @property
    def watts(self) -> float:
        return float(self.state.state)

    async def call(self, domain, service, data, blocking=False):
        value = float(data["value"])
        self.writes.append(value)
        if self.drop > 0:
            self.drop -= 1
            return
        self.state.state = str(float(round(value / 10.0) * 10))

    def hass(self):
        async def _call(domain, service, data, blocking=False):
            await self.call(domain, service, data, blocking)
        return SimpleNamespace(
            states=SimpleNamespace(get=lambda _eid: self.state),
            services=SimpleNamespace(async_call=_call))


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_log_gate():
    reset_log_gate()
    yield
    reset_log_gate()


def _cycles(w, h, clock, cap, n, *, every_s=10.0):
    out = []
    for _ in range(n):
        clock.t += every_s
        out.append(_run(w.apply(h, ENTITY, cap, observer=False,
                                hw_max_w=5000.0)))
    return out


def _refused_at_1700_wanting_1500():
    """The live shape: 1700 W taken in the morning; the afternoon re-solve
    wants 1500 W and that one write is lost. The register keeps 1700."""
    clock = Clock()
    reg = SungrowTemplateNumber(5000.0)
    w = ChargePacingWriter()
    w._clock = clock
    h = reg.hass()
    assert _run(w.apply(h, ENTITY, 1750.0, observer=False,
                        hw_max_w=5000.0)) == "wrote"
    assert _cycles(w, h, clock, 1750.0, 3) == ["held"] * 3
    assert reg.watts == 1700.0 and w._taken is True
    clock.t += 600.0
    reg.drop = 1
    assert _run(w.apply(h, ENTITY, 1550.0, observer=False,
                        hw_max_w=5000.0)) == "wrote"
    out = _cycles(w, h, clock, 1550.0, 12)
    # pinned: the writer really reached a refusal — the test below cannot
    # pass on a writer that never refused
    assert out[-1] == "write_refused", out
    assert w._taken is False and w.last_written_w == 1500.0
    assert reg.watts == 1700.0
    return clock, reg, w, h


class TestTheRegisterAtTheWishIsHeld:
    def test_the_wish_comes_back_to_the_register(self):
        """A cloud raises the re-solve to 1700 W — exactly what the register
        holds. Pacing is in effect; the card must not say refused."""
        clock, reg, w, h = _refused_at_1700_wanting_1500()
        writes = len(reg.writes)
        out = _cycles(w, h, clock, 1750.0, 30, every_s=60.0)
        assert "write_refused" not in out, out
        assert set(out) == {"held"}
        assert len(reg.writes) == writes, "nothing to write: it is there"

    def test_a_wish_within_the_deadband_of_the_register(self):
        """1600 W wanted, 1700 W held: one step apart, inside the writer's
        own deadband — SEM would not write, so it is not a refusal either."""
        clock, reg, w, h = _refused_at_1700_wanting_1500()
        writes = len(reg.writes)
        out = _cycles(w, h, clock, 1650.0, 10)
        assert set(out) == {"held"}, out
        assert len(reg.writes) == writes

    def test_the_alarm_stays_where_it_is_true(self):
        """Still wanting 1500 W with 1700 W on the register: that IS a cap
        the inverter did not take. The card keeps saying so (and, by the
        02.10 decision, the same cap is not re-sent)."""
        clock, reg, w, h = _refused_at_1700_wanting_1500()
        writes = len(reg.writes)
        out = _cycles(w, h, clock, 1550.0, 60)
        assert set(out) == {"write_refused"}, out
        assert len(reg.writes) == writes

    def test_the_alarm_comes_back_when_the_wish_leaves_the_register(self):
        """held at 1700 (the wish came back), then the wish drops to 1200
        and that write is lost too: refused again."""
        clock, reg, w, h = _refused_at_1700_wanting_1500()
        assert set(_cycles(w, h, clock, 1750.0, 5)) == {"held"}
        clock.t += 600.0
        reg.drop = 1
        out = _cycles(w, h, clock, 1250.0, 15)
        assert out[0] == "wrote" and out[-1] == "write_refused", out
        assert reg.watts == 1700.0

    def test_a_late_landing_is_still_taken(self):
        """The register reaches the refused cap after all: taken, as
        before — this change does not touch the verdict itself."""
        clock, reg, w, h = _refused_at_1700_wanting_1500()
        reg.state.state = "1500.0"
        out = _cycles(w, h, clock, 1550.0, 3)
        assert set(out) == {"held"}
        assert w._taken is True and w._accepted_w == 1500.0

    def test_the_verdict_is_kept_so_the_refused_cap_is_not_sent_again(self):
        """Held at the wish is about the ACTION only. The 02.10 rule — a
        refused cap is not sent again while the wish stays near it — is
        keyed to the verdict, so the wish going back to 1500 W says refused
        and writes nothing, an hour later too (review 2, 06.10: retiring
        the verdict re-sent refused caps up to every 5 minutes on a
        register that never takes a write)."""
        clock, reg, w, h = _refused_at_1700_wanting_1500()
        assert set(_cycles(w, h, clock, 1750.0, 3)) == {"held"}
        assert w._taken is False and w.last_written_w == 1500.0
        writes = len(reg.writes)
        out = _cycles(w, h, clock, 1550.0, 60, every_s=60.0)
        assert set(out) == {"write_refused"}, out
        assert len(reg.writes) == writes

    def test_a_cap_jittering_across_the_register_writes_nothing(self):
        """1500 W lost, 1700 W held, the cap jitters 1590↔1610 W — on the
        step grid 1500 (refused, register away) and 1600 (register at the
        wish). The action follows the truth of each cycle; no write goes
        out. (The sensor's recorded ``cap_w`` attribute moves with the
        same jitter, so the action adds no recorder rows of its own.)"""
        clock, reg, w, h = _refused_at_1700_wanting_1500()
        writes = len(reg.writes)
        for i in range(360):
            clock.t += 10.0
            cap = 1610.0 if i % 2 else 1590.0
            out = _run(w.apply(h, ENTITY, cap, observer=False,
                               hw_max_w=5000.0))
            assert out == ("held" if cap == 1610.0 else "write_refused"), (i, out)
        assert len(reg.writes) == writes


class TestAfterARestart:
    """Review (06.10): the first cycle after adoption wrote whenever the
    register was out of the persisted cap's band — even when the register
    already held what SEM wants. A write equal to the register can never
    read as taken (it does not change), so 90 s later a healthy inverter
    was 'refusing'."""

    class Store:
        def __init__(self, record):
            self.record = dict(record)

        async def async_load(self):
            return dict(self.record)

        async def async_save(self, data):
            self.record = dict(data)

        async def async_remove(self):
            self.record = None

    def test_a_register_at_the_wish_is_taken_without_a_write(self):
        clock = Clock()
        reg = SungrowTemplateNumber(1700.0)
        store = self.Store({"entity_id": ENTITY, "restore_value": 9720.0,
                            "cap_w": 1500.0, "accepted_w": None,
                            "applied_differs": None})
        w = ChargePacingWriter(store=store)
        w._clock = clock
        h = reg.hass()
        out = _cycles(w, h, clock, 1750.0, 12)
        assert set(out) == {"held"}, out
        assert reg.writes == [], "the register already holds the cap"
        assert w._taken is True and w.last_written_w == 1700.0
        assert store.record["cap_w"] == 1700.0
        assert store.record["restore_value"] == 9720.0
        # the cap moves: one write at once (no real write yet, no interval)
        out = _cycles(w, h, clock, 1550.0, 12)
        assert "write_refused" not in out, out
        assert reg.writes == [1500.0]

    def test_a_register_back_at_the_users_value_is_not_taken(self):
        """Review 3 (06.10): SEM captured the user's 5000 W and paced at
        1500 W; while SEM was down the inverter rebooted to 5000 W. The wish
        is 4950 W — at the register — but 5000 W is the value to put back.
        Taken as SEM's cap, the #949 own-cap rule would erase it from the
        record at the next adoption. So SEM writes its cap (as before this
        change) and the value to put back survives."""
        clock = Clock()
        reg = SungrowTemplateNumber(5000.0)
        store = self.Store({"entity_id": ENTITY, "restore_value": 5000.0,
                            "cap_w": 1500.0, "accepted_w": 1500.0,
                            "applied_differs": None})
        w = ChargePacingWriter(store=store)
        w._clock = clock
        h = reg.hass()
        out = _cycles(w, h, clock, 4950.0, 6)
        assert out[0] == "wrote" and set(out[1:]) == {"held"}, out
        assert reg.writes == [4900.0]
        assert store.record["restore_value"] == 5000.0
        assert store.record["cap_w"] == 4900.0
        # the next lifetime still knows what to put back
        w2 = ChargePacingWriter(store=store)
        w2._clock = clock
        assert _run(w2.apply(h, ENTITY, None, observer=False,
                             hw_max_w=None)) == "restored"
        assert reg.writes[-1] == 5000.0

    def test_a_register_away_from_the_wish_is_still_rewritten(self):
        """The review-3 rule is kept: moved while SEM was away, and not at
        the wish — one rewrite at once."""
        clock = Clock()
        reg = SungrowTemplateNumber(3000.0)
        store = self.Store({"entity_id": ENTITY, "restore_value": 9720.0,
                            "cap_w": 1500.0, "accepted_w": 1500.0,
                            "applied_differs": None})
        w = ChargePacingWriter(store=store)
        w._clock = clock
        h = reg.hass()
        out = _cycles(w, h, clock, 1750.0, 6)
        assert out[0] == "wrote" and set(out[1:]) == {"held"}, out
        assert reg.writes == [1700.0]


class TestNeverRefusedAtTheWish:
    """The property, over a day of random wishes and lost writes: the
    action is never ``write_refused`` on a cycle where the register holds
    what SEM wants (inside the writer's own deadband). Liveness twin: the
    lost writes do produce refusals, and the register does come back to the
    wish under a refused verdict — so the property is tested, not idle."""

    @pytest.mark.parametrize("seed", range(6))
    def test_a_day_with_lost_writes(self, seed):
        rnd = random.Random(seed)
        clock = Clock()
        reg = SungrowTemplateNumber(5000.0)
        w = ChargePacingWriter()
        w._clock = clock
        h = reg.hass()
        cap = 1800.0
        refused = 0
        refused_verdict_at_wish = 0
        for _ in range(3000):
            clock.t += 10.0
            cap = max(300.0, min(5000.0, cap + rnd.uniform(-40.0, 40.0)))
            if rnd.random() < 0.1:
                reg.drop = 1
            was_refused = w._taken is False
            action = _run(w.apply(h, ENTITY, cap, observer=False,
                                  hw_max_w=5000.0))
            wish = (int(cap) // 100) * 100.0
            at_wish = abs(reg.watts - wish) <= max(100.0, 0.05 * wish)
            if action == "write_refused":
                refused += 1
                assert not at_wish, (reg.watts, wish, w.last_written_w)
            if at_wish and was_refused:
                refused_verdict_at_wish += 1
        assert refused > 0, "no lost write was ever judged — vacuous"
        assert refused_verdict_at_wish > 0, (
            "the register never came back to the wish under a refused "
            "verdict — the property was never exercised")
