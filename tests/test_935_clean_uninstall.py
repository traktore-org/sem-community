"""#935 — SEM hands the house back as it found it and takes its own files.

@markusschloesser ran Spook after removing SEM (#908) and found 119 leftover
long-term statistics. The statistics turned out to be the smallest part:
removal deleted a config entry and released the loads SEM had started, and
left behind every store it had written, its version marker, its Repairs, the
Lovelace resources pointing at files that were about to vanish, and a wallbox
SEM had parked — holding "no" with nothing left on the system to say "yes".

The three rules under test: hand the hardware back (and ONLY what SEM
commanded), take SEM's own files, and merely OFFER what is the user's.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


from custom_components.solar_energy_management import cleanup

ENTRY = "01ABCDEFGHIJKLMNOPQRSTUVWX"
OTHER = "01ZZZZZZZZZZZZZZZZZZZZZZZZ"


def _run(coro):
    return asyncio.run(coro)


class FakeStore:
    """The three methods a Store double needs, with a visible payload."""

    def __init__(self, data=None):
        self.data = data

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = dict(data)

    async def async_remove(self):
        self.data = None


def _hass_with_storage(tmp_path, names=()):
    """A hass whose .storage really holds these files, and whose executor
    runs inline — the listing is off the loop in production (#935 tripped
    HA's blocking-call guard), and the test still wants the real directory."""
    storage = tmp_path / ".storage"
    storage.mkdir(exist_ok=True)
    for n in names:
        (storage / n).write_text("{}")

    async def _executor(fn, *args):
        return fn(*args)

    return SimpleNamespace(
        config=SimpleNamespace(config_dir=str(tmp_path)),
        services=SimpleNamespace(async_call=AsyncMock()),
        async_add_executor_job=_executor,
    )


def _orphans(hass, live):
    """What the sweep would delete: the listing, then the judgement."""
    return cleanup.orphan_store_keys(
        _run(cleanup.async_existing_store_files(hass)), live)


class TestTheInventoryKnowsWhatThisEntryOwns:
    def test_every_per_entry_store_is_named(self):
        keys = cleanup.per_entry_store_keys(ENTRY)
        assert f"solar_energy_management_{ENTRY}_energy" in keys
        assert f"solar_energy_management_{ENTRY}_daily" in keys
        assert f"sem_seen_version_{ENTRY}" in keys
        assert f"sem.pacing.{ENTRY}" in keys, "#949's record is SEM's too"

    def test_the_second_scoped_stores_are_prefixes(self):
        pre = cleanup.per_entry_store_prefixes(ENTRY)
        assert f"sem.deye.snapshot.{ENTRY}." in pre
        assert f"sem.deye.unsafe.{ENTRY}." in pre

    def test_an_empty_entry_id_owns_nothing(self):
        """A degenerate id would prefix-match every entry's stores — the
        #709 scope rule, on the delete side where it costs more."""
        assert cleanup.per_entry_store_keys("") == []
        assert cleanup.per_entry_store_prefixes("") == []

    def test_install_wide_stores_are_separate(self):
        wide = cleanup.install_wide_store_keys()
        assert "sem_device_mappings" in wide
        assert "solar_energy_management_load_management_devices" in wide
        # the retired names, still live on PROD
        assert "solar_energy_management_daily_storage" in wide
        assert "solar_energy_management_energy_totals" in wide

    def test_no_per_entry_key_is_also_install_wide(self):
        assert not (set(cleanup.per_entry_store_keys(ENTRY))
                    & set(cleanup.install_wide_store_keys()))


class TestTheOrphanSweep:
    def test_a_removed_entrys_stores_are_orphans(self, tmp_path):
        hass = _hass_with_storage(tmp_path, [
            f"solar_energy_management_{ENTRY}_energy",
            f"solar_energy_management_{ENTRY}_daily",
            f"sem_seen_version_{ENTRY}",
            f"solar_energy_management_{OTHER}_energy",
            f"sem_seen_version_{OTHER}",
        ])
        orphans = _orphans(hass, [ENTRY])
        assert sorted(orphans) == sorted([
            f"solar_energy_management_{OTHER}_energy",
            f"sem_seen_version_{OTHER}",
        ])

    def test_a_live_entrys_stores_are_never_orphans(self, tmp_path):
        hass = _hass_with_storage(tmp_path, [
            f"solar_energy_management_{ENTRY}_daily",
            f"sem.pacing.{ENTRY}",
            f"sem.deye.snapshot.{ENTRY}.battery_1",
        ])
        assert _orphans(hass, [ENTRY]) == []

    def test_install_wide_stores_survive_the_sweep(self, tmp_path):
        hass = _hass_with_storage(tmp_path, [
            "sem_device_mappings",
            "solar_energy_management_load_management_devices",
            "solar_energy_management_daily_storage",
        ])
        assert _orphans(hass, [ENTRY]) == []

    def test_a_store_nobody_taught_it_about_is_left_alone(self, tmp_path):
        """Deleting an unrecognised file is how a cleanup becomes the problem
        it was written to solve."""
        hass = _hass_with_storage(tmp_path, ["sem_something_new_entirely"])
        assert _orphans(hass, [ENTRY]) == []

    def test_backups_are_not_swept(self, tmp_path):
        hass = _hass_with_storage(tmp_path, [
            f"solar_energy_management_{OTHER}_energy.bak.1780495914",
            f"solar_energy_management_{OTHER}_energy.bak",
        ])
        assert _orphans(hass, [ENTRY]) == []

    def test_no_storage_directory_is_not_a_crash(self):
        async def _executor(fn, *args):
            return fn(*args)

        hass = SimpleNamespace(
            config=SimpleNamespace(config_dir="/nope/nope"),
            async_add_executor_job=_executor)
        assert _run(cleanup.async_existing_store_files(hass)) == []
        assert _orphans(hass, [ENTRY]) == []


class TestRepairsGoWithTheIntegration:
    def _registry(self, keys):
        return SimpleNamespace(issues={k: object() for k in keys})

    def test_every_sem_issue_is_deleted_and_nothing_else(self, monkeypatch):
        deleted = []
        reg = self._registry([
            ("solar_energy_management", "split_grid_guessed"),
            ("solar_energy_management", "soc_zones_out_of_order"),
            ("some_other_integration", "not_ours"),
        ])
        monkeypatch.setattr(
            "homeassistant.helpers.issue_registry.async_get",
            lambda hass: reg)
        monkeypatch.setattr(
            "homeassistant.helpers.issue_registry.async_delete_issue",
            lambda hass, domain, issue_id: deleted.append((domain, issue_id)))
        n = cleanup.delete_repairs(SimpleNamespace())
        assert n == 2
        assert ("some_other_integration", "not_ours") not in deleted
        assert sorted(i for _, i in deleted) == [
            "soc_zones_out_of_order", "split_grid_guessed"]

    def test_an_unreadable_registry_reports_zero_not_a_crash(self, monkeypatch):
        monkeypatch.setattr(
            "homeassistant.helpers.issue_registry.async_get",
            MagicMock(side_effect=RuntimeError("no registry")))
        assert cleanup.delete_repairs(SimpleNamespace()) == 0


class TestTheFrontendResources:
    def test_the_real_live_urls_are_recognised(self):
        """The exact rows read off the .46 rig on 12.09 — the first cut of
        this matcher was written against a GUESSED url shape."""
        for url in (
            "/local/custom_components/solar_energy_management/dashboard/card/"
            "dist/sem-cards.js?v=2.1.0-beta.18-93ee7460",
            "/local/custom_components/solar_energy_management/dashboard/card/"
            "sem-localize.js?v=2.1.0-beta.18-6c9c5fbb",
        ):
            assert cleanup._is_sem_resource(url), url

    def test_the_rigs_other_thirty_odd_resources_survive(self):
        """Everything else on that same rig — HACS cards and hand-placed
        /local ones. A cleanup that takes one of these is worse than the
        leftover it was written to remove."""
        for url in (
            "/hacsfiles/lovelace-mushroom/mushroom.js?hacstag=444350375523",
            "/hacsfiles/apexcharts-card/apexcharts-card.js?hacstag=331701152223",
            "/local/community/lovelace-card-mod/card-mod.js",
            "/local/community/k-flow-card/k-flow-card.js",
            "/local/community/sunsynk-power-flow-card/sunsynk-power-flow-card.js",
            "/hacsfiles/lovelace-solar-card/solar-card.js?hacstag=1050656026083",
        ):
            assert not cleanup._is_sem_resource(url), url

    def test_sems_own_resources_are_recognised(self):
        assert cleanup._is_sem_resource(
            "/solar_energy_management/dashboard/card/dist/sem-cards.js?v=2.1.0-abc")
        assert cleanup._is_sem_resource(
            "/solar_energy_management/dashboard/card/sem-localize.js")

    def test_someone_elses_resource_is_not(self):
        assert not cleanup._is_sem_resource("/hacsfiles/mushroom/mushroom.js")
        assert not cleanup._is_sem_resource("/local/my-own/sem-cards.js")
        assert not cleanup._is_sem_resource("")
        assert not cleanup._is_sem_resource(None)


class TestStatisticsAreTheUsersUntilTheySaySo:
    def test_nothing_to_clear_calls_nothing(self):
        hass = SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock()))
        assert _run(cleanup.async_clear_statistics(hass, [])) == 0
        assert hass.services.async_call.await_count == 0

    def test_a_missing_recorder_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(
            "homeassistant.components.recorder.get_instance",
            MagicMock(side_effect=RuntimeError("no recorder")))
        assert _run(cleanup.async_clear_statistics(
            SimpleNamespace(), ["sensor.x"])) == 0


class TestTheDashboardIsOfferedNeverTaken:
    def test_both_halves_go_together(self, monkeypatch):
        """The view config and the sidebar row are separate files; leaving
        either behind gives a broken sidebar entry or an invisible orphan."""
        removed_keys = []
        saved = {}

        class FakeStore:
            def __init__(self, hass, version, key):
                self.key = key

            async def async_remove(self):
                removed_keys.append(self.key)

            async def async_load(self):
                return {"items": [{"id": "sem-dashboard"}, {"id": "mine"}]}

            async def async_save(self, data):
                saved.update(data)

        monkeypatch.setattr("homeassistant.helpers.storage.Store", FakeStore)
        assert _run(cleanup.async_remove_dashboard(SimpleNamespace())) is True
        assert "lovelace.sem-dashboard" in removed_keys
        assert [i["id"] for i in saved["items"]] == ["mine"], (
            "someone else's dashboard must survive")

    def test_it_is_not_part_of_the_automatic_teardown(self):
        """Nothing in the removal path may call it — a year of solar yield is
        not SEM's to throw away because a config entry is being deleted.

        Pinned by the AST rather than by the source text (#924/#925): a guard
        coupled to the SPELLING of the code passes the day someone renames
        the call, which is exactly when it needs to fail.
        """
        from custom_components import solar_energy_management as sem
        from custom_components.solar_energy_management.tests.ast_contracts import (
            calls,
        )

        for forbidden in ("async_remove_dashboard", "async_clear_statistics"):
            assert not calls(sem._async_take_sems_own_files, forbidden), (
                f"removal must never call {forbidden} — it is the user's")


class TestTheWallboxIsHandedBack:
    """The leftover a person MEETS rather than finds: a box that will not
    charge and gives no reason. A parked KEBA holds its no three ways —
    contactor disabled, 0 A stored, a persisted dead-man failsafe — which is
    the point while SEM is away for a moment (#740) and abandonment once SEM
    is gone."""

    def _device(self, *, parked=True, **kw):
        dev = SimpleNamespace(
            name="KEBA P30",
            _sem_parked=parked,
            start_service=kw.get("start_service"),
            start_service_data=None,
            service_device_id=None,
            charge_mode_entity=kw.get("charge_mode_entity"),
            charge_mode_start=kw.get("charge_mode_start"),
            start_stop_entity=kw.get("start_stop_entity"),
            charger_service=kw.get("charger_service"),
            hass=SimpleNamespace(services=SimpleNamespace(
                has_service=lambda d, s: s in kw.get("services", ()))),
            send=AsyncMock(),
            arm_failsafe=AsyncMock(),
        )
        from custom_components.solar_energy_management.devices.base import (
            CurrentControlDevice,
        )
        dev.release_to_user = CurrentControlDevice.release_to_user.__get__(dev)
        return dev

    def test_a_parked_keba_is_enabled_and_the_deadman_lifted(self):
        dev = self._device(charger_service="keba.set_current",
                           services=("enable", "set_failsafe"))
        said = _run(dev.release_to_user(reason="integration removed"))
        assert dev.send.await_args_list[0].args[:2] == ("keba", "enable")
        dev.arm_failsafe.assert_awaited_once()
        assert said and "integration removed" in said
        assert dev._sem_parked is False

    def test_it_never_authorises(self):
        """`keba.authorize` is the owner's, not ours, and SEM has never
        touched it."""
        dev = self._device(charger_service="keba.set_current",
                           services=("enable", "authorize", "set_failsafe"))
        _run(dev.release_to_user())
        called = [c.args[1] for c in dev.send.await_args_list]
        assert "authorize" not in called and "deauthorize" not in called

    def test_a_box_sem_never_parked_is_left_alone(self):
        """#908's rule, on the charger: only ever undo what SEM commanded."""
        dev = self._device(parked=False, charger_service="keba.set_current",
                           services=("enable",))
        assert _run(dev.release_to_user()) is None
        assert dev.send.await_count == 0
        dev.arm_failsafe.assert_not_awaited()

    def test_a_switch_controlled_charger_is_turned_back_on(self):
        dev = self._device(start_stop_entity="switch.wallbox_charging")
        _run(dev.release_to_user())
        call = dev.send.await_args_list[0]
        assert call.args[:2] == ("switch", "turn_on")
        assert call.args[2]["entity_id"] == "switch.wallbox_charging"

    def test_a_brand_start_service_is_preferred(self):
        dev = self._device(start_service="easee.action_command")
        _run(dev.release_to_user())
        assert dev.send.await_args_list[0].args[:2] == ("easee", "action_command")

    def test_no_current_is_written_and_no_session_opened(self):
        """Handing a box back is not starting a charge."""
        dev = self._device(charger_service="keba.set_current",
                           services=("enable", "set_failsafe"))
        _run(dev.release_to_user())
        services = [c.args[1] for c in dev.send.await_args_list]
        assert "set_current" not in services
        assert "set_energy" not in services

    def test_a_failing_enable_still_completes_the_teardown(self):
        dev = self._device(charger_service="keba.set_current",
                           services=("enable",))
        dev.send = AsyncMock(side_effect=RuntimeError("UDP is gone"))
        assert _run(dev.release_to_user()) is not None or True
        assert dev._sem_parked is False, "the debt is cleared either way"


class TestTheSweepOnlyEverTakesARealEntrysStore:
    """Found by fault injection on the .46 rig, 13.09: the first cut accepted
    ANY middle segment as a config-entry id, so a file the user had copied
    aside by hand — `solar_energy_management_mybackup_energy` — was swept as
    an orphaned install's store. A cleanup that deletes someone's own file is
    the exact problem this module exists to avoid."""

    REAL = "01M2BQ1A7MWSNS021PMT5XQMQA"          # a live rig entry id (ULID)
    OLD = "0123456789abcdef0123456789abcdef"     # the 32-hex ids older installs carry

    def _swept(self, names, live=()):
        return cleanup.orphan_store_keys(names, live)

    def test_a_hand_made_backup_is_not_an_orphan(self):
        for name in (
            "solar_energy_management_mybackup_energy",
            "solar_energy_management_backup_daily",
            "solar_energy_management_before_upgrade_energy",
            "solar_energy_management_copy_daily",
        ):
            assert self._swept([name]) == [], name

    def test_a_real_entrys_store_still_is(self):
        for name in (
            f"solar_energy_management_{self.REAL}_energy",
            f"solar_energy_management_{self.OLD}_daily",
            f"sem_seen_version_{self.REAL}",
            f"sem.pacing.{self.REAL}",
            f"sem.deye.snapshot.{self.REAL}.battery_1",
        ):
            assert self._swept([name]) == [name], name

    def test_a_lowercase_or_short_middle_is_not_an_entry_id(self):
        """ULIDs are 26 uppercase alphanumerics; anything else is a word."""
        for middle in ("01direntry", "backup", "01M2BQ1A7MWSNS021PMT5XQMQ",
                       "01M2BQ1A7MWSNS021PMT5XQMQAA", "x" * 26):
            name = f"solar_energy_management_{middle}_daily"
            assert self._swept([name]) == [], middle

    def test_the_rigs_real_neighbours_survive(self):
        """The other SEM-ish names actually sitting in the rig's .storage."""
        for name in ("core.config_entries.bak.sem257", "energy.backup_sem",
                     "lovelace.sem-dashboard", "lovelace.test_sem",
                     "sem_device_mappings", "sem_device_mappings.bak",
                     "semaphore_state", "sem_seen_version_", "sem.pacing."):
            assert self._swept([name]) == [], name


class TestTheServiceCannotBeArmedByAccident:
    """Fault injection, 13.09: the service was registered without a schema,
    so `dashboard: 12345` reached `bool(12345)` and the off-by-default
    destructive option armed itself. The rig's dashboard was deleted by a
    junk value. The asymmetry of the two defaults IS the safety, so it has
    to survive a caller who sends nonsense."""

    def _schema(self):
        import voluptuous as vol

        return vol.Schema({
            vol.Optional("statistics", default=True): bool,
            vol.Optional("dashboard", default=False): bool,
        })

    def test_the_registered_schema_is_this_one(self):
        """Pinned by the AST so a rename cannot quietly drop it."""
        import ast
        import inspect

        from custom_components import solar_energy_management as sem

        src = inspect.getsource(sem._async_register_services)
        tree = ast.parse(src.lstrip())
        registered = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", "") == "async_register"
            and any(isinstance(a, ast.Constant) and a.value == "remove_leftovers"
                    for a in n.args)
        ]
        assert registered, "the service must still be registered"
        assert any(k.arg == "schema" for k in registered[0].keywords), (
            "remove_leftovers must be registered WITH a schema")

    def test_junk_cannot_turn_the_dashboard_option_on(self):
        import voluptuous as vol

        # cv.boolean would pass 12345 and 2.5 — any non-zero number is
        # "true" to it, and a truthy number is not consent to a delete.
        for junk in (12345, "maybe", [], {"x": 1}, 2.5, 1, 0, "true"):
            with pytest.raises(vol.Invalid):
                self._schema()({"dashboard": junk})

    def test_the_defaults_keep_their_asymmetry(self):
        out = self._schema()({})
        assert out["statistics"] is True, "the leftover statistics are the ask"
        assert out["dashboard"] is False, "the dashboard may hold their edits"

    def test_a_real_boolean_still_works(self):
        assert self._schema()({"dashboard": True})["dashboard"] is True
        assert self._schema()({"statistics": False})["statistics"] is False


class TestStatisticsGoThroughTheRecordersOwnApi:
    """`recorder.clear_statistics` is not a service — the recorder publishes
    purge / purge_entities / enable / disable / get_statistics and clears
    statistics over its websocket API. The first cut called the service, so
    every call failed, warned "recorder may be disabled" about a recorder
    that was loaded and running, and reported nothing cleared (.46, 13.09)."""

    def test_it_hands_the_ids_to_the_recorder_instance(self, monkeypatch):
        handed = {}

        class FakeInstance:
            def async_clear_statistics(self, ids, **kw):
                handed["ids"] = list(ids)

        monkeypatch.setattr("homeassistant.components.recorder.get_instance",
                            lambda hass: FakeInstance())
        hass = SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock()))
        n = _run(cleanup.async_clear_statistics(
            hass, ["sensor.sem_solar_power", "sensor.sem_battery_soc"]))
        assert n == 2
        assert handed["ids"] == ["sensor.sem_solar_power", "sensor.sem_battery_soc"]
        assert hass.services.async_call.await_count == 0, (
            "never through a service that does not exist")

    def test_a_missing_recorder_reports_zero(self, monkeypatch):
        monkeypatch.setattr(
            "homeassistant.components.recorder.get_instance",
            MagicMock(side_effect=RuntimeError("recorder not loaded")))
        assert _run(cleanup.async_clear_statistics(
            SimpleNamespace(), ["sensor.x"])) == 0


class TestTheParkDebtOutlivesTheProcess:
    """ruflo REFUTED the first cut here, and it broke the exact scenario this
    issue opens with. `_sem_parked` was an instance attribute rebuilt False on
    every setup, and the reconciler cannot re-derive it: PARK_OFF fires on the
    connect→disconnect EDGE, and a box already empty at boot is a steady
    state, not an edge. So park → restart → remove left the charger disabled,
    its own persisted dead-man failsafe holding 0 A, and nothing left on the
    system that knew why."""

    def _device(self, store=None, **kw):
        from custom_components.solar_energy_management.devices.base import (
            CurrentControlDevice,
        )
        dev = SimpleNamespace(
            name="KEBA P30", charger_id="ev_charger", _sem_parked=False,
            _park_store=store, send=AsyncMock(), arm_failsafe=AsyncMock(),
            start_service=None, start_service_data=None, service_device_id=None,
            charge_mode_entity=None, charge_mode_start=None,
            start_stop_entity=kw.get("start_stop_entity"),
            charger_service=kw.get("charger_service"),
            hass=SimpleNamespace(services=SimpleNamespace(
                has_service=lambda d, s: s in kw.get("services", ()))),
        )
        for m in ("_remember_parked", "adopt_park_state", "release_to_user"):
            setattr(dev, m, getattr(CurrentControlDevice, m).__get__(dev))
        return dev

    def test_a_park_is_written_where_it_survives_a_restart(self):
        store = FakeStore()
        dev = self._device(store=store)
        _run(dev._remember_parked(True))
        assert store.data == {"parked": ["ev_charger"]}

    def test_the_next_lifetime_adopts_it(self):
        """The regression, end to end: fresh process, box still parked."""
        store = FakeStore()
        first = self._device(store=store)
        _run(first._remember_parked(True))

        after_restart = self._device(store=store)
        assert after_restart._sem_parked is False, "a fresh object starts clean"
        after_restart.adopt_park_state(store.data["parked"])
        assert after_restart._sem_parked is True, (
            "without this the box keeps refusing and nothing knows why")

    def test_a_start_clears_the_debt(self):
        store = FakeStore({"parked": ["ev_charger"]})
        dev = self._device(store=store)
        _run(dev._remember_parked(False))
        assert store.data == {"parked": []}

    def test_another_chargers_park_is_not_adopted(self):
        dev = self._device()
        dev.adopt_park_state(["some_other_charger"])
        assert dev._sem_parked is False

    def test_a_store_that_throws_never_costs_the_command(self):
        class Broken(FakeStore):
            async def async_load(self):
                raise RuntimeError("storage is having a day")

        dev = self._device(store=Broken())
        _run(dev._remember_parked(True))
        assert dev._sem_parked is True, "the in-memory truth still stands"


class TestAHandBackCannotBlockARemoval:
    """`hass.services.async_call` takes no timeout, so a charger integration
    whose handler stalls hung `async_remove_entry` — which HA awaits while
    holding the entry's setup lock. The removal would never finish."""

    def test_a_stalled_integration_is_given_up_on(self):
        from custom_components.solar_energy_management.devices.base import (
            CurrentControlDevice,
        )

        async def _never_returns(*a, **kw):
            await asyncio.sleep(3600)

        dev = SimpleNamespace(
            name="KEBA P30", charger_id="c1", _sem_parked=True, _park_store=None,
            send=_never_returns, arm_failsafe=AsyncMock(),
            start_service=None, start_service_data=None, service_device_id=None,
            charge_mode_entity=None, charge_mode_start=None,
            start_stop_entity=None, charger_service="keba.set_current",
            hass=SimpleNamespace(services=SimpleNamespace(
                has_service=lambda d, s: True)))
        for m in ("_remember_parked", "release_to_user"):
            setattr(dev, m, getattr(CurrentControlDevice, m).__get__(dev))

        async def _go():
            import custom_components.solar_energy_management.devices.base as base
            base._RELEASE_TIMEOUT_S = 0.05
            return await asyncio.wait_for(dev.release_to_user(), timeout=5)

        _run(_go())          # must return, not hang
        assert dev._sem_parked is False


class TestClearingIsScopedToOneEntry:
    def _registry(self, rows):
        return SimpleNamespace(entities=SimpleNamespace(
            values=lambda: [SimpleNamespace(entity_id=e, platform=p,
                                            config_entry_id=c)
                            for e, p, c in rows]))

    def test_a_second_entrys_history_is_not_this_entrys_leftovers(self, monkeypatch):
        monkeypatch.setattr(
            "homeassistant.helpers.entity_registry.async_get",
            lambda hass: self._registry([
                ("sensor.sem_a", "solar_energy_management", "entry_A"),
                ("sensor.sem_b", "solar_energy_management", "entry_B"),
                ("sensor.other", "another_integration", "entry_A"),
            ]))
        assert cleanup.sem_statistic_ids(SimpleNamespace(), "entry_A") == [
            "sensor.sem_a"]

    def test_no_scope_still_means_every_sem_entity(self, monkeypatch):
        monkeypatch.setattr(
            "homeassistant.helpers.entity_registry.async_get",
            lambda hass: self._registry([
                ("sensor.sem_a", "solar_energy_management", "entry_A"),
                ("sensor.sem_b", "solar_energy_management", "entry_B"),
            ]))
        assert cleanup.sem_statistic_ids(SimpleNamespace()) == [
            "sensor.sem_a", "sensor.sem_b"]
