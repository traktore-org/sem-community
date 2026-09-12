"""#949 — the paced cap must not outlive SEM as the user's own setting.

Found on PROD, 12.09.2026, while proving #820: the switch was on, the
sensor read ``cap_w: 403`` with the reason "paced to land full at day's
end", and the battery charged at 3 kW all morning. Two defects met there.

**The one that damages hardware.** ``ChargePacingWriter`` captures the
inverter's max-charge-power on first engage and restores it on disengage,
and both halves lived in memory. An HA restart never unloads the config
entry (``async_unload_entry`` says so in its own comment), and the pacer is
not in the battery adapters' unload release (#936) — so the register keeps
the cap. The next lifetime's fresh writer then reads the register, finds
SEM's own 400 W, and stores THAT as the value to restore to. The real
hardware maximum is gone, every later restore puts the cap back, and the
surface says healthy throughout.

**The one that hides it.** ``apply`` returned ``idle`` both for "nothing to
pace" and for "a cap, and no entity to write it to" — #925's rule, one
layer along: "I could not act" is its own value.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.coordinator.charge_pacing import (
    ChargePacingWriter,
)

ENTITY = "number.batteries_maximale_ladeleistung"


class FakeStore:
    """The three methods the writer duck-types, plus a visible payload."""

    def __init__(self, data=None):
        self.data = data
        self.saves = 0
        self.removes = 0

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = dict(data)
        self.saves += 1

    async def async_remove(self):
        self.data = None
        self.removes += 1


def _hass(current="5000"):
    st = SimpleNamespace(state=current)
    return SimpleNamespace(
        states=SimpleNamespace(get=MagicMock(return_value=st)),
        services=SimpleNamespace(async_call=AsyncMock()),
    )


def _run(coro):
    return asyncio.run(coro)


def _values_written(hass):
    return [c.args[2]["value"] for c in hass.services.async_call.await_args_list]


class TestACapWithNowhereToGo:
    def test_a_decided_cap_and_no_entity_says_so(self):
        w = ChargePacingWriter()
        assert _run(w.apply(_hass(), "", 403.0, observer=False)) == "no_limit_entity"

    def test_no_cap_and_no_entity_is_still_idle(self):
        """Nothing to pace is not the same complaint, and must not shout."""
        w = ChargePacingWriter()
        assert _run(w.apply(_hass(), "", None, observer=False)) == "idle"

    def test_it_writes_nothing(self):
        h = _hass()
        w = ChargePacingWriter()
        _run(w.apply(h, "", 403.0, observer=False))
        assert h.services.async_call.await_count == 0


class TestTheEngagementSurvivesARestart:
    def test_engaging_persists_what_the_register_held(self):
        store = FakeStore()
        w = ChargePacingWriter(store=store)
        assert _run(w.apply(_hass("5000"), ENTITY, 400.0, observer=False)) == "wrote"
        assert store.data == {"entity_id": ENTITY, "restore_value": 5000.0,
                              "cap_w": 400.0}

    def test_the_next_lifetime_restores_the_REAL_maximum(self):
        """The regression, end to end: restart with the cap on the register."""
        store = FakeStore()
        first = ChargePacingWriter(store=store)
        _run(first.apply(_hass("5000"), ENTITY, 400.0, observer=False))

        # SEM restarts. The register still reads SEM's own cap — that is
        # exactly what an unloaded-nothing restart leaves behind.
        second = ChargePacingWriter(store=store)
        h = _hass("400")
        out = _run(second.apply(h, ENTITY, None, observer=False))
        assert out == "restored"
        assert _values_written(h) == [5000.0], (
            "without the adopted record the writer captures its own cap and "
            "the pack is throttled to 400 W for good")

    def test_without_the_record_the_old_fault_is_still_reproducible(self):
        """Proof the test above is testing the record and not a tautology."""
        blind = ChargePacingWriter()  # no store — the pre-#949 writer
        h = _hass("400")
        _run(blind.apply(h, ENTITY, 400.0, observer=False))
        assert blind.restore_value == 400.0

    def test_adoption_writes_nothing_when_the_cap_still_stands(self):
        store = FakeStore({"entity_id": ENTITY, "restore_value": 5000.0,
                           "cap_w": 400.0})
        w = ChargePacingWriter(store=store)
        h = _hass("400")
        assert _run(w.apply(h, ENTITY, 420.0, observer=False)) == "held"
        assert h.services.async_call.await_count == 0
        assert w.restore_value == 5000.0

    def test_a_finished_pacing_clears_the_record(self):
        store = FakeStore({"entity_id": ENTITY, "restore_value": 5000.0,
                           "cap_w": 400.0})
        w = ChargePacingWriter(store=store)
        assert _run(w.apply(_hass("400"), ENTITY, None, observer=False)) == "restored"
        assert store.data is None and store.removes == 1

    def test_adoption_happens_once(self):
        store = FakeStore({"entity_id": ENTITY, "restore_value": 5000.0,
                           "cap_w": 400.0})
        w = ChargePacingWriter(store=store)
        h = _hass("400")
        _run(w.apply(h, ENTITY, 420.0, observer=False))
        _run(w.apply(h, ENTITY, 430.0, observer=False))
        assert w.restore_value == 5000.0

    def test_a_corrupt_record_is_not_an_engagement(self):
        for junk in (None, [], {"entity_id": ""}, "nonsense"):
            w = ChargePacingWriter(store=FakeStore(junk))
            h = _hass("5000")
            assert _run(w.apply(h, ENTITY, 400.0, observer=False)) == "wrote"
            assert w.restore_value == 5000.0

    def test_a_store_that_throws_never_costs_a_cycle(self):
        class Broken(FakeStore):
            async def async_load(self):
                raise RuntimeError("storage is having a day")

            async def async_save(self, data):
                raise RuntimeError("storage is having a day")

        w = ChargePacingWriter(store=Broken())
        assert _run(w.apply(_hass("5000"), ENTITY, 400.0, observer=False)) == "wrote"


class TestTheEntityCanMove:
    def test_a_repointed_setting_hands_the_old_register_back(self):
        store = FakeStore({"entity_id": "number.old_limit",
                           "restore_value": 5000.0, "cap_w": 400.0})
        w = ChargePacingWriter(store=store)
        h = _hass("3000")
        _run(w.apply(h, ENTITY, None, observer=False))
        assert h.services.async_call.await_args_list[0].args[2] == {
            "entity_id": "number.old_limit", "value": 5000.0}
        assert store.data is None

    def test_a_cleared_setting_hands_the_old_register_back(self):
        store = FakeStore({"entity_id": "number.old_limit",
                           "restore_value": 5000.0, "cap_w": 400.0})
        w = ChargePacingWriter(store=store)
        h = _hass("400")
        assert _run(w.apply(h, "", 400.0, observer=False)) == "no_limit_entity"
        assert _values_written(h) == [5000.0]


class TestAnObserverHasNoSideEffects:
    def test_it_never_adopts_and_never_writes(self):
        store = FakeStore({"entity_id": ENTITY, "restore_value": 5000.0,
                           "cap_w": 400.0})
        w = ChargePacingWriter(store=store)
        h = _hass("400")
        assert _run(w.apply(h, ENTITY, 400.0, observer=True)) == "observer"
        assert h.services.async_call.await_count == 0
        assert store.data is not None, "the record of a real engagement stands"
        assert not w.engaged

    def test_leaving_observer_mode_still_adopts(self):
        store = FakeStore({"entity_id": ENTITY, "restore_value": 5000.0,
                           "cap_w": 400.0})
        w = ChargePacingWriter(store=store)
        _run(w.apply(_hass("400"), ENTITY, 400.0, observer=True))
        h = _hass("400")
        assert _run(w.apply(h, ENTITY, None, observer=False)) == "restored"
        assert _values_written(h) == [5000.0]


class TestTheStoreIsScopedToTheEntry:
    """The record must never be shared between two SEM config entries, and a
    coordinator without an entry must get no record rather than a shared one.
    """

    def _make(self, hass, entry_id):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        stand_in = SimpleNamespace(
            hass=hass,
            config_entry=SimpleNamespace(entry_id=entry_id) if entry_id else None,
        )
        return SEMCoordinator._charge_pacing_store(stand_in)

    def test_the_key_carries_the_entry_id(self, hass):
        store = self._make(hass, "01ABCDEF")
        assert store is not None, "a real hass must yield a real store"
        assert "01ABCDEF" in str(getattr(store, "key", ""))

    def test_two_entries_never_share_one(self, hass):
        a = self._make(hass, "entry_a")
        b = self._make(hass, "entry_b")
        assert a.key != b.key

    def test_no_entry_means_no_record(self, hass):
        assert self._make(hass, None) is None
