"""#777 second half — the SETUP path must read the same record the switch does.

2026-07-18 fixed the toggle: every flip now writes ``entry.options``, so a
rebuilt coordinator boots protected. 2026-08-15 (#777) fixed the restore
path: explicit config beats a dead install's ghost.

Neither fixed the install that has NO explicit record at all — the one case
where #777 deliberately keeps honoring the restore store. There the switch
learns the truth from a store the COORDINATOR cannot see, and the coordinator
is built minutes earlier from ``config.get("observer_mode", False)``. So on
every restart of a legacy install:

  coordinator built  ─── ARMED ───────────────►  switch attaches, pushes ON
  (no key in config)      the window               (now, finally, hands-off)

That is the exact class ``_persist_flag``'s docstring describes, still open
for anyone who set the switch before the persist existed. Live-hit on HA-TEST
16.08.2026 — a box wired to the real KEBA and LUNA battery, believed
hands-off, would have run armed for the length of every start.

Worse, it decays: HA prunes the restore store after
``restore_state.STATE_EXPIRATION`` (7 days). An install off for a fortnight
loses its only record and silently reverts to the ARMED default.

The fix reads the store at setup — the third source, the same one the switch
uses — and PROMOTES what it finds into ``entry.options``, so the ambiguity is
resolved once and permanently instead of being re-derived (and eventually
lost) every boot.
"""
import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _hass(restored: dict | None = None):
    """A hass whose restore store holds ``restored`` (entity_id -> state)."""
    hass = MagicMock()
    last_states = {
        eid: SimpleNamespace(state=SimpleNamespace(state=st))
        for eid, st in (restored or {}).items()
    }
    hass.data = {}
    hass._sem_last_states = last_states
    return hass


def _entry(options=None, data=None):
    return SimpleNamespace(
        options=options if options is not None else {},
        data=data if data is not None else {},
    )


@pytest.fixture(autouse=True)
def _patch_restore_store(monkeypatch):
    """Route the helper's restore-store read at the hass built by ``_hass``.

    Patching the module's own accessor keeps the test honest about the
    contract (entity_id -> last state) without standing up HA's storage.
    """
    from custom_components.solar_energy_management import persisted_flags as pf

    def fake(hass, entity_id):
        stored = getattr(hass, "_sem_last_states", {}).get(entity_id)
        return stored.state.state if stored is not None else None

    monkeypatch.setattr(pf, "_restored_switch_state", fake)


@pytest.mark.unit
class TestResolvePrecedence:
    """One resolution order, shared with the switch: options, data, ghost."""

    def test_options_win(self):
        from custom_components.solar_energy_management.persisted_flags import (
            resolve_persisted_flag,
        )
        hass = _hass({"switch.sem_observer_mode": "on"})
        entry = _entry(options={"observer_mode": False},
                       data={"observer_mode": True})
        assert resolve_persisted_flag(hass, entry, "observer_mode") is False

    def test_data_beats_the_ghost(self):
        from custom_components.solar_energy_management.persisted_flags import (
            resolve_persisted_flag,
        )
        hass = _hass({"switch.sem_observer_mode": "on"})
        entry = _entry(data={"observer_mode": False})
        assert resolve_persisted_flag(hass, entry, "observer_mode") is False

    def test_the_ghost_speaks_when_nothing_else_does(self):
        """The legacy install — #777 keeps honoring restore here, so the
        coordinator must honor exactly the same thing."""
        from custom_components.solar_energy_management.persisted_flags import (
            resolve_persisted_flag,
        )
        hass = _hass({"switch.sem_observer_mode": "on"})
        assert resolve_persisted_flag(hass, _entry(), "observer_mode") is True

    def test_silence_everywhere_is_none_not_false(self):
        """None means "never recorded" — distinct from a recorded False.
        Collapsing the two is how the ARMED default won in the first place."""
        from custom_components.solar_energy_management.persisted_flags import (
            resolve_persisted_flag,
        )
        assert resolve_persisted_flag(_hass(), _entry(), "observer_mode") is None

    @pytest.mark.parametrize("junk", ["unavailable", "unknown", "", None])
    def test_a_junk_restore_state_is_not_a_record(self, junk):
        """The switch is a CoordinatorEntity; its state flaps to
        unavailable. Only a definite on/off is a record — the same
        contract ``_sync_observer_mode_from_switch`` holds per cycle."""
        from custom_components.solar_energy_management.persisted_flags import (
            resolve_persisted_flag,
        )
        hass = _hass({"switch.sem_observer_mode": junk})
        assert resolve_persisted_flag(hass, _entry(), "observer_mode") is None


@pytest.mark.unit
class TestPromotion:
    """The window closes because setup learns the truth BEFORE the
    coordinator is built — and writes it down so it never has to guess again."""

    def test_a_legacy_observer_install_boots_observing(self):
        """The live HA-TEST case: no key anywhere, restore store says on.
        The config handed to the coordinator must say True."""
        from custom_components.solar_energy_management.persisted_flags import (
            promote_persisted_flags,
        )
        hass = _hass({"switch.sem_observer_mode": "on"})
        entry = _entry()
        config = {}
        promoted = promote_persisted_flags(hass, entry, config)
        assert config["observer_mode"] is True
        assert promoted == {"observer_mode": True}

    def test_the_promotion_is_written_to_options(self):
        """A read-only fix decays: STATE_EXPIRATION prunes the store after
        7 days and the install silently reverts to the ARMED default.
        Promotion makes the record explicit, permanently."""
        from custom_components.solar_energy_management.persisted_flags import (
            promote_persisted_flags,
        )
        hass = _hass({"switch.sem_observer_mode": "on"})
        entry = _entry()
        promote_persisted_flags(hass, entry, {})
        written = hass.config_entries.async_update_entry.call_args
        assert written.args[0] is entry
        assert written.kwargs["options"]["observer_mode"] is True

    def test_an_explicit_config_is_left_alone(self):
        """Nothing to resolve — and no entry write, so no reload churn on
        every single start."""
        from custom_components.solar_energy_management.persisted_flags import (
            promote_persisted_flags,
        )
        hass = _hass({"switch.sem_observer_mode": "on"})
        entry = _entry(options={"observer_mode": False})
        config = {"observer_mode": False}
        assert promote_persisted_flags(hass, entry, config) == {}
        assert config["observer_mode"] is False
        hass.config_entries.async_update_entry.assert_not_called()

    def test_silence_promotes_nothing(self):
        """No record anywhere: leave the config untouched so the per-key
        default still decides. Never invent a record."""
        from custom_components.solar_energy_management.persisted_flags import (
            promote_persisted_flags,
        )
        hass = _hass()
        config = {}
        assert promote_persisted_flags(hass, _entry(), config) == {}
        assert "observer_mode" not in config
        hass.config_entries.async_update_entry.assert_not_called()

    def test_all_three_flags_are_the_class(self):
        """Systematic: the kill-switch and vacation carry the same hole —
        an install that turned actuation OFF on a legacy entry would boot
        ACTUATING until the switch attached."""
        from custom_components.solar_energy_management.persisted_flags import (
            promote_persisted_flags,
        )
        hass = _hass({
            "switch.sem_observer_mode": "on",
            "switch.sem_vacation_mode": "on",
            "switch.sem_energy_plan_actuation": "off",
        })
        entry = _entry()
        config = {}
        promote_persisted_flags(hass, entry, config)
        assert config == {
            "observer_mode": True,
            "vacation_mode": True,
            "energy_plan_actuation": False,
        }

    def test_one_entry_write_for_all_promotions(self):
        """Three promotions, one options write — not three."""
        from custom_components.solar_energy_management.persisted_flags import (
            promote_persisted_flags,
        )
        hass = _hass({
            "switch.sem_observer_mode": "on",
            "switch.sem_vacation_mode": "on",
            "switch.sem_energy_plan_actuation": "off",
        })
        entry = _entry(options={"update_interval": 10})
        promote_persisted_flags(hass, entry, {})
        assert hass.config_entries.async_update_entry.call_count == 1
        opts = hass.config_entries.async_update_entry.call_args.kwargs["options"]
        assert opts["update_interval"] == 10          # existing options survive
        assert opts["energy_plan_actuation"] is False


@pytest.mark.unit
class TestWiring:
    """A resolution nobody calls is the fix that never runs (#777)."""

    def test_setup_promotes_before_building_the_coordinator(self):
        """Order is the whole point: after the coordinator exists the
        window is already open."""
        import custom_components.solar_energy_management as sem_init
        src = inspect.getsource(sem_init.async_setup_entry)
        assert "promote_persisted_flags(" in src
        assert src.index("promote_persisted_flags(") < src.index("SEMCoordinator(")

    def test_the_welcome_notification_reads_the_resolved_config(self):
        """Same class, smaller blast radius: the #397 first-run welcome is
        meant to skip observer installs, but it asked ``entry.data`` alone
        — so it spammed every install whose observer flag lived anywhere
        else. One source read where three exist is the bug, wherever it
        appears."""
        import custom_components.solar_energy_management as sem_init
        src = inspect.getsource(sem_init.async_setup_entry)
        assert 'entry.data.get("observer_mode")' not in src
        assert 'full_config.get("observer_mode")' in src

    def test_the_switch_and_setup_share_one_default_table(self):
        """Two copies of "what silence means" is how they drift apart."""
        from custom_components.solar_energy_management.persisted_flags import (
            PERSISTED_FLAG_DEFAULTS,
        )
        from custom_components.solar_energy_management.switch import SEMSolarSwitch
        assert SEMSolarSwitch._PERSISTED_DEFAULTS is PERSISTED_FLAG_DEFAULTS

    def test_the_switch_entity_ids_are_the_ones_that_exist(self):
        """The store is keyed by entity_id; the switch forces
        ``switch.sem_<key>``. If that ever changes, the read goes silent —
        and silence here means ARMED."""
        from custom_components.solar_energy_management.persisted_flags import (
            PERSISTED_FLAG_DEFAULTS, switch_entity_id,
        )
        from custom_components.solar_energy_management.switch import SEMSolarSwitch
        src = inspect.getsource(SEMSolarSwitch.__init__)
        assert 'self.entity_id = f"switch.sem_{description.key}"' in src
        for key in PERSISTED_FLAG_DEFAULTS:
            assert switch_entity_id(key) == f"switch.sem_{key}"
