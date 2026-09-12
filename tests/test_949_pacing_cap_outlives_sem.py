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


class TestTheObserverSeam:
    """ruflo REFUTED the first version of this fix here.

    Flipping observer ON mid-engagement dropped the in-memory capture, left
    the record on disk alone, and kept the writer marked adopted. The next
    real cycle then re-captured the live register — still holding SEM's own
    cap — and persisted THAT as the hardware maximum. The bug this whole
    change exists to kill, reached through a switch the user is invited to
    use, with no restart involved.
    """

    def test_an_observer_toggle_does_not_eat_the_real_maximum(self):
        store = FakeStore()
        w = ChargePacingWriter(store=store)
        # A real engagement: the register held 5000 W, SEM wrote 350 W.
        assert _run(w.apply(_hass("5000"), ENTITY, 350.0, observer=False)) == "wrote"

        # Observer goes on, and the decision drops to "no cap" — target
        # reached, trust lost, any of the several None branches.
        assert _run(w.apply(_hass("350"), ENTITY, None, observer=True)) == "observer"
        assert store.data is not None, "the record of a real cap must stand"

        # Observer goes off and pacing wants a cap again. The register still
        # reads SEM's own 350 W, because nothing ever restored it.
        h = _hass("350")
        _run(w.apply(h, ENTITY, 300.0, observer=False))
        assert w.restore_value == 5000.0, (
            "the writer re-captured its own cap as the hardware maximum")
        assert store.data["restore_value"] == 5000.0

    def test_and_the_maximum_still_comes_back_afterwards(self):
        store = FakeStore()
        w = ChargePacingWriter(store=store)
        _run(w.apply(_hass("5000"), ENTITY, 350.0, observer=False))
        _run(w.apply(_hass("350"), ENTITY, None, observer=True))
        _run(w.apply(_hass("350"), ENTITY, 300.0, observer=False))
        h = _hass("300")
        assert _run(w.apply(h, ENTITY, None, observer=False)) == "restored"
        assert _values_written(h) == [5000.0]


class TestARegisterSEMCannotReadIsOneItMustNotWrite:
    """The capture is the only way back, so an unreadable baseline is a
    refusal, not a write with a silent hole where the restore should be."""

    def test_an_unavailable_entity_is_not_written(self):
        for dark in ("unavailable", "unknown", "", None):
            h = _hass(dark)
            w = ChargePacingWriter()
            assert _run(w.apply(h, ENTITY, 400.0, observer=False)) == "limit_unreadable"
            assert h.services.async_call.await_count == 0
            assert not w.engaged

    def test_a_missing_entity_is_not_written(self):
        h = _hass()
        h.states.get = MagicMock(return_value=None)
        w = ChargePacingWriter()
        assert _run(w.apply(h, ENTITY, 400.0, observer=False)) == "limit_unreadable"
        assert h.services.async_call.await_count == 0

    def test_it_engages_as_soon_as_the_entity_reads(self):
        w = ChargePacingWriter(store=FakeStore())
        _run(w.apply(_hass("unavailable"), ENTITY, 400.0, observer=False))
        assert _run(w.apply(_hass("5000"), ENTITY, 400.0, observer=False)) == "wrote"
        assert w.restore_value == 5000.0

    def test_a_hold_with_nothing_to_restore_keeps_its_record(self):
        """An old record with no captured value: the cap cannot be lifted, so
        the record is the only trace that a register is still held down."""
        store = FakeStore({"entity_id": ENTITY, "restore_value": None,
                           "cap_w": 400.0})
        w = ChargePacingWriter(store=store)
        h = _hass("400")
        assert _run(w.apply(h, ENTITY, None, observer=False)) == "idle"
        assert h.services.async_call.await_count == 0
        assert store.data is not None and store.removes == 0


class TestSEMGoingAwayHandsTheRegisterBack:
    """#936 hands back what the battery ADAPTERS commanded. The pacer writes a
    user-named number directly and was not in that path, so a disabled or
    removed entry left the cap on the register with no next lifetime to adopt
    it — the claim's real hole, found by ruflo."""

    def _engaged_coordinator(self):
        from custom_components.solar_energy_management.coordinator.charge_pacing import (
            pending_pacing_release,
        )
        store = FakeStore()
        w = ChargePacingWriter(store=store)
        _run(w.apply(_hass("5000"), ENTITY, 400.0, observer=False))
        return SimpleNamespace(_charge_pacing_writer=w), pending_pacing_release, store

    def test_an_engaged_pacer_reports_what_it_holds(self):
        coord, pending, store = self._engaged_coordinator()
        held = pending(coord)
        assert held[0] == ENTITY and held[1] == 5000.0 and held[2] is store

    def test_an_idle_pacer_holds_nothing(self):
        from custom_components.solar_energy_management.coordinator.charge_pacing import (
            pending_pacing_release,
        )
        assert pending_pacing_release(SimpleNamespace()) is None
        assert pending_pacing_release(
            SimpleNamespace(_charge_pacing_writer=ChargePacingWriter())) is None

    def test_releasing_puts_the_maximum_back_and_drops_the_record(self):
        from custom_components.solar_energy_management.coordinator.charge_pacing import (
            async_release_pacing,
        )
        coord, pending, store = self._engaged_coordinator()
        h = _hass("400")
        said = _run(async_release_pacing(h, pending(coord), "integration removed"))
        assert _values_written(h) == [5000.0]
        assert store.data is None
        assert said and "integration removed" in said

    def test_releasing_nothing_is_a_no_op(self):
        from custom_components.solar_energy_management.coordinator.charge_pacing import (
            async_release_pacing,
        )
        h = _hass()
        assert _run(async_release_pacing(h, None, "disabled")) is None
        assert h.services.async_call.await_count == 0


class TestTheUnloadWiring:
    """The helpers above are only worth having if the lifecycle calls them.
    ruflo's Defect 2 was precisely that nothing did."""

    def _hass_for_unload(self):
        from unittest.mock import AsyncMock as AM, MagicMock as MM, Mock
        h = MM()
        h.config_entries = MM()
        h.config_entries.async_unload_platforms = AM(return_value=True)
        h.services = MM()
        h.services.async_remove = Mock()
        h.services.async_call = AM()
        return h

    def _engaged_coordinator(self):
        from unittest.mock import MagicMock as MM
        store = FakeStore()
        w = ChargePacingWriter(store=store)
        _run(w.apply(_hass("5000"), ENTITY, 400.0, observer=False))
        coord = MM()
        coord._observer_mode = False
        coord._battery_adapters = {}
        coord._surplus_controller = None
        coord._charge_pacing_writer = w
        return coord, store

    async def _unload(self, hass, coord, entry_id, disabled_by=None):
        from unittest.mock import MagicMock as MM
        from custom_components.solar_energy_management import async_unload_entry
        hass.data = {"solar_energy_management": {entry_id: coord}}
        entry = MM()
        entry.entry_id = entry_id
        entry.disabled_by = disabled_by
        return await async_unload_entry(hass, entry)

    def test_a_reload_leaves_the_cap_alone(self):
        """The next lifetime adopts it; restoring here would be a write pair
        on every options change (#934's lesson)."""
        import custom_components.solar_energy_management as sem
        hass = self._hass_for_unload()
        coord, store = self._engaged_coordinator()
        _run(self._unload(hass, coord, "entry-reload"))
        assert hass.services.async_call.await_count == 0
        assert store.data is not None
        assert "entry-reload" in sem._PENDING_PACING_RESTORE

    def test_a_disabled_entry_gets_its_register_back_now(self):
        hass = self._hass_for_unload()
        coord, store = self._engaged_coordinator()
        _run(self._unload(hass, coord, "entry-off", disabled_by="user"))
        assert _values_written(hass) == [5000.0]
        assert store.data is None

    def test_a_removal_replays_the_parked_restore(self):
        from unittest.mock import MagicMock as MM
        from custom_components.solar_energy_management import async_remove_entry
        hass = self._hass_for_unload()
        coord, store = self._engaged_coordinator()
        _run(self._unload(hass, coord, "entry-gone"))
        entry = MM()
        entry.entry_id = "entry-gone"
        _run(async_remove_entry(hass, entry))
        assert _values_written(hass) == [5000.0]
        assert store.data is None

    def test_an_idle_pacer_parks_nothing(self):
        import custom_components.solar_energy_management as sem
        from unittest.mock import MagicMock as MM
        hass = self._hass_for_unload()
        coord = MM()
        coord._observer_mode = False
        coord._battery_adapters = {}
        coord._surplus_controller = None
        coord._charge_pacing_writer = ChargePacingWriter()
        _run(self._unload(hass, coord, "entry-idle"))
        assert "entry-idle" not in sem._PENDING_PACING_RESTORE
