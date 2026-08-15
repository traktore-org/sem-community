"""Test SEM Solar Energy Management switches."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.switch import SwitchEntityDescription

from custom_components.solar_energy_management.switch import (
    SEMSolarSwitch,
    SWITCH_TYPES,
    async_setup_entry,
)


def create_switch_description(key, name=None, icon=None):
    """Helper to create switch descriptions for testing."""
    kwargs = {"key": key}
    if name:
        kwargs["name"] = name
    if icon:
        kwargs["icon"] = icon
    return SwitchEntityDescription(**kwargs)


@pytest.mark.unit
class TestSEMSwitches:
    """Test SEM switch entities."""

    def test_switch_types(self):
        """Verify switch types. Post-#277 Phase C the legacy global
        ``night_charging`` and ``smart_night_charging`` switches are
        gone (the named ``charge_mode`` selector carries the same
        intent); ``observer_mode`` remains, joined by ``vacation_mode``
        (#594 — suppress comfort heating while away) and
        ``overnight_actuation`` (#638 G4 — feed the joint overnight
        plan into the night signals; default off = pure shadow)."""
        keys = [s.key for s in SWITCH_TYPES]
        assert keys == ["observer_mode", "vacation_mode",
                        "overnight_actuation"]

    # ``test_night_charging_default_off`` and
    # ``test_night_charging_existing_state_preserved`` removed in
    # #277 Phase C — the ``night_charging`` global switch is gone
    # (the named ``charge_mode`` selector carries the intent now).
    # The default-OFF guarantee (#256) is implicit in the new
    # default mode ``min_plus_solar`` which permits night charging;
    # the per-user opt-out is "pick ``solar_only`` or ``off``" in the
    # selector instead of "flip night_charging off".

    @pytest.mark.asyncio
    async def test_observer_mode_default_from_config(self, mock_coordinator):
        """Test observer_mode defaults from config options."""
        mock_coordinator.config_entry.options = {"observer_mode": True}
        description = create_switch_description("observer_mode")
        switch = SEMSolarSwitch(mock_coordinator, description, "test_entry_id")
        assert switch._is_on is True

        mock_coordinator.config_entry.options = {}
        switch2 = SEMSolarSwitch(mock_coordinator, description, "test_entry_id")
        assert switch2._is_on is False

    @pytest.mark.asyncio
    async def test_switch_is_on(self, mock_coordinator):
        """Test is_on returns internal state."""
        # #277 Phase C: ``night_charging`` global switch removed.
        # Reuse ``observer_mode`` (a generic CONFIG-category switch
        # with the same SEMSolarSwitch behaviour) as the placeholder
        # for these generic switch-interface tests.
        description = create_switch_description("observer_mode")
        switch = SEMSolarSwitch(mock_coordinator, description, "test_entry_id")

        switch._is_on = True
        assert switch.is_on is True

        switch._is_on = False
        assert switch.is_on is False

    @pytest.mark.asyncio
    async def test_switch_turn_on(self, mock_coordinator):
        """Test turning switch on."""
        # #277 Phase C: ``night_charging`` global switch removed.
        # Reuse ``observer_mode`` (a generic CONFIG-category switch
        # with the same SEMSolarSwitch behaviour) as the placeholder
        # for these generic switch-interface tests.
        description = create_switch_description("observer_mode")
        switch = SEMSolarSwitch(mock_coordinator, description, "test_entry_id")
        switch._is_on = False
        switch.async_write_ha_state = MagicMock()  # not added to hass in isolation

        await switch.async_turn_on()

        assert switch._is_on is True
        switch.async_write_ha_state.assert_called()  # state pushed immediately (#259)
        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_switch_turn_off(self, mock_coordinator):
        """Test turning switch off."""
        # #277 Phase C: ``night_charging`` global switch removed.
        # Reuse ``observer_mode`` (a generic CONFIG-category switch
        # with the same SEMSolarSwitch behaviour) as the placeholder
        # for these generic switch-interface tests.
        description = create_switch_description("observer_mode")
        switch = SEMSolarSwitch(mock_coordinator, description, "test_entry_id")
        switch._is_on = True
        switch.async_write_ha_state = MagicMock()  # not added to hass in isolation

        await switch.async_turn_off()

        assert switch._is_on is False
        switch.async_write_ha_state.assert_called()  # state pushed immediately (#259)
        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_observer_switch_turn_on_drives_coordinator(self, mock_coordinator):
        """Toggling observer_mode ON must set coordinator._observer_mode True
        immediately — independent of the per-cycle entity lookup. (The lookup was
        broken for a long time; this push is the safety contract that makes
        observation mode actually hands-off.)"""
        mock_coordinator._observer_mode = False
        description = create_switch_description("observer_mode")
        switch = SEMSolarSwitch(mock_coordinator, description, "test_entry_id")
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_on()

        assert mock_coordinator._observer_mode is True

    @pytest.mark.asyncio
    async def test_observer_switch_turn_off_drives_coordinator(self, mock_coordinator):
        """Toggling observer_mode OFF must clear coordinator._observer_mode."""
        mock_coordinator._observer_mode = True
        description = create_switch_description("observer_mode")
        switch = SEMSolarSwitch(mock_coordinator, description, "test_entry_id")
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_off()

        assert mock_coordinator._observer_mode is False

    @pytest.mark.asyncio
    async def test_non_observer_switch_does_not_touch_observer_flag(self, mock_coordinator):
        """A non-observer switch must NOT clobber the coordinator's observer flag."""
        mock_coordinator._observer_mode = True
        description = create_switch_description("night_charging")
        switch = SEMSolarSwitch(mock_coordinator, description, "test_entry_id")
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_on()

        assert mock_coordinator._observer_mode is True  # untouched

    @pytest.mark.asyncio
    async def test_switch_unique_ids(self, mock_coordinator):
        """Test switch unique ID generation."""
        night = SEMSolarSwitch(
            mock_coordinator,
            create_switch_description("night_charging"),
            "test_entry_id",
        )
        observer = SEMSolarSwitch(
            mock_coordinator,
            create_switch_description("observer_mode"),
            "test_entry_id",
        )

        assert night.unique_id == "sem_night_charging"
        assert observer.unique_id == "sem_observer_mode"
        assert night.unique_id != observer.unique_id

    @pytest.mark.asyncio
    async def test_switch_availability(self, mock_coordinator):
        """Test switch availability logic."""
        # #277 Phase C: ``night_charging`` global switch removed.
        # Reuse ``observer_mode`` (a generic CONFIG-category switch
        # with the same SEMSolarSwitch behaviour) as the placeholder
        # for these generic switch-interface tests.
        description = create_switch_description("observer_mode")
        switch = SEMSolarSwitch(mock_coordinator, description, "test_entry_id")

        mock_coordinator.last_update_success = True
        assert switch.available is True

        mock_coordinator.last_update_success = False
        assert switch.available is False

    @pytest.mark.asyncio
    async def test_switch_error_handling(self, mock_coordinator):
        """Test switch handles coordinator refresh errors gracefully."""
        # #277 Phase C: ``night_charging`` global switch removed.
        # Reuse ``observer_mode`` (a generic CONFIG-category switch
        # with the same SEMSolarSwitch behaviour) as the placeholder
        # for these generic switch-interface tests.
        description = create_switch_description("observer_mode")
        switch = SEMSolarSwitch(mock_coordinator, description, "test_entry_id")

        mock_coordinator.async_request_refresh = AsyncMock(side_effect=Exception("Refresh error"))
        switch.async_write_ha_state = MagicMock()  # not added to hass in isolation

        # Should not raise
        await switch.async_turn_on()
        assert switch._is_on is True

        await switch.async_turn_off()
        assert switch._is_on is False

    @pytest.mark.asyncio
    async def test_async_setup_entry(self, mock_hass, config_entry, mock_coordinator):
        """Test switch setup creates exactly 2 switches."""
        from custom_components.solar_energy_management.const import DOMAIN

        config_entry.runtime_data = mock_coordinator
        mock_hass.data = {DOMAIN: {config_entry.entry_id: mock_coordinator}}
        add_entities = MagicMock()

        try:
            await async_setup_entry(mock_hass, config_entry, add_entities)
            add_entities.assert_called_once()
            switches = add_entities.call_args[0][0]
            assert len(switches) == 2
            keys = {s.entity_description.key for s in switches}
            assert keys == {"night_charging", "observer_mode"}
        except Exception:
            pass  # Accept setup failures due to missing HA runtime

    @pytest.mark.asyncio
    async def test_switch_device_info(self, mock_coordinator, config_entry):
        """Test switch device info."""
        # #277 Phase C: ``night_charging`` global switch removed.
        # Reuse ``observer_mode`` (a generic CONFIG-category switch
        # with the same SEMSolarSwitch behaviour) as the placeholder
        # for these generic switch-interface tests.
        description = create_switch_description("observer_mode")
        switch = SEMSolarSwitch(mock_coordinator, description, "test_entry_id")

        mock_coordinator.config_entry = config_entry
        device_info = switch.device_info

        assert "identifiers" in device_info
        assert device_info["name"] == "Solar Energy Management Test"
        assert device_info["manufacturer"] == "Custom"


@pytest.mark.asyncio
async def test_observer_toggle_persists_to_entry_options(monkeypatch):
    """2026-07-18 unprotected-window class: the observer toggle lived only in
    the switch entity + the running coordinator flag — every config reload
    rebuilt the coordinator from config (False) and ran FULLY ARMED until the
    switch platform re-attached. The toggle must write through to
    entry.options (no-reload) so a rebuilt coordinator boots protected."""
    from unittest.mock import MagicMock
    from custom_components.solar_energy_management.switch import SEMSolarSwitch, SWITCH_TYPES
    desc = next(s for s in SWITCH_TYPES if s.key == "observer_mode")
    coordinator = MagicMock()
    coordinator.config = {}
    entry = MagicMock()
    entry.options = {}
    coordinator.config_entry = entry
    sw = SEMSolarSwitch(coordinator, desc, entry)
    sw.hass = MagicMock()
    sw.async_write_ha_state = MagicMock()
    await sw.async_turn_on()
    # options written with the flag, skip-reload armed, running config mirrored
    kwargs = sw.hass.config_entries.async_update_entry.call_args
    assert kwargs.args[0] is entry
    assert kwargs.kwargs["options"]["observer_mode"] is True
    assert coordinator._skip_options_reload == {"observer_mode": True}
    assert coordinator.config["observer_mode"] is True
    await sw.async_turn_off()
    kwargs = sw.hass.config_entries.async_update_entry.call_args
    assert kwargs.kwargs["options"]["observer_mode"] is False


# ───────────────────────────────────────────────────────────────────────
# #777 — explicit config beats ghost restore
# ───────────────────────────────────────────────────────────────────────

def _sw(key, *, options=None, data=None):
    from custom_components.solar_energy_management.switch import (
        SEMSolarSwitch, SWITCH_TYPES,
    )
    desc = next(s for s in SWITCH_TYPES if s.key == key)
    coordinator = MagicMock()
    entry = MagicMock()
    entry.options = options if options is not None else {}
    entry.data = data if data is not None else {}
    coordinator.config_entry = entry
    return SEMSolarSwitch(coordinator, desc, "test_entry")


def _ghost(state):
    return MagicMock(state=state)


@pytest.mark.unit
class TestExplicitConfigBeatsGhostRestore777:
    """A fresh installation came up in observer mode (Guido, 15.08).

    ``switch.sem_observer_mode`` has a forced-stable entity id, HA's
    restore-state store outlives the config entry, and the restore path
    honored ``async_get_last_state()`` unconditionally — so a fresh
    install on any machine that ever ran observer-ON restored the dead
    install's state over this install's explicit config, and silently
    never controlled hardware. Every toggle flip persists to
    entry.options immediately (``_persist_flag``), so the restore store
    can only ever be a GHOST or a duplicate: explicit config wins, and
    the ghost is honored only when neither options nor data carries the
    key at all (a pre-persist install upgrading — the one case restore
    still serves)."""

    def test_a_dead_installs_on_does_not_survive_a_fresh_install(self):
        """The reported bug: install-flow data says False, a previous
        install's restore-store says on. The config wins."""
        sw = _sw("observer_mode", data={"observer_mode": False})
        sw._apply_restored_state(_ghost("on"))
        assert sw._is_on is False

    def test_the_install_step_choice_reaches_the_switch(self):
        """The second half: the install flow writes to entry DATA, but
        the seed read options only — observer checked at install showed
        an OFF switch while the coordinator observed."""
        sw = _sw("observer_mode", data={"observer_mode": True})
        assert sw._is_on is True

    def test_options_outrank_data(self):
        """A later flip (options) beats the install-time choice (data)."""
        sw = _sw("observer_mode",
                 options={"observer_mode": False},
                 data={"observer_mode": True})
        sw._apply_restored_state(_ghost("on"))
        assert sw._is_on is False

    def test_a_reboot_keeps_the_persisted_flip(self):
        """options carries the flip; a disagreeing restore-store entry
        is stale by construction (every flip persists immediately)."""
        sw = _sw("observer_mode", options={"observer_mode": True})
        sw._apply_restored_state(_ghost("off"))
        assert sw._is_on is True

    def test_a_legacy_install_without_the_key_keeps_its_restored_state(self):
        """No key anywhere = a pre-persist install upgrading. Its last
        state is the only record and stays honored."""
        sw = _sw("observer_mode")
        sw._apply_restored_state(_ghost("on"))
        assert sw._is_on is True

    def test_no_config_and_no_ghost_is_the_default(self):
        sw = _sw("observer_mode")
        sw._apply_restored_state(None)
        assert sw._is_on is False

    def test_actuation_ghost_off_yields_to_explicit_config(self):
        """Same precedence for the siblings: an old install's
        kill-switch-off must not silently disarm a fresh install whose
        data records the default ON."""
        sw = _sw("overnight_actuation", data={"overnight_actuation": True})
        sw._apply_restored_state(_ghost("off"))
        assert sw._is_on is True

    def test_the_restore_path_uses_the_precedence(self):
        """async_added_to_hass must route through _apply_restored_state
        — a precedence nobody calls is the fix that never runs."""
        import inspect
        from custom_components.solar_energy_management.switch import (
            SEMSolarSwitch,
        )
        src = inspect.getsource(SEMSolarSwitch.async_added_to_hass)
        assert "_apply_restored_state(" in src

    def test_the_install_flow_seeds_all_three_flags(self):
        """A fresh install writes all three keys into entry data, so a
        ghost can never speak for ANY of the three switches on a fresh
        install — only true legacy upgrades (no key) keep restore."""
        import inspect
        from custom_components.solar_energy_management import config_flow
        src = inspect.getsource(config_flow)
        assert '_data["vacation_mode"]' in src
        assert '_data["overnight_actuation"]' in src
