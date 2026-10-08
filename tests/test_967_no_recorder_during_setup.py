"""#967 — setup must not read the recorder.

@alexmc1510 added his EV charger to the Energy Dashboard and SEM stopped
loading. One line in his log:

    Setup of config entry 'Solar Energy Management' ... cancelled
    asyncio.exceptions.CancelledError: Global task timeout:
        Bootstrap stage 2 timeout

Home Assistant gives every integration a shared budget to start in. SEM
spent it on the recorder: 60 days of EV power history for the taper
detector, 7 days per load for the rated-power seed, a statistics scan for
the install date, another for the yearly totals — all awaited inside
``async_setup_entry``. One more power sensor took it over the line, HA
cancelled the setup task, and because a cancel is not an ``Exception``,
every "this must never cost us the setup" handler on the way up let it
through.

What these tests pin
--------------------
1. A boot-shaped setup reads the recorder **zero** times.
2. The same reads still happen once Home Assistant has started — so test 1
   is not passing because the work quietly disappeared.
3. The rated-power seed defers rather than drops: a load skipped during
   setup is not marked as tried.
4. Every history read goes through one module, so a new caller cannot
   re-open the hole by writing its own query.
5. That module's query is the cheap shape: no attributes, and never a
   longer window than the recorder keeps.
"""
from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

from custom_components.solar_energy_management.const import DOMAIN  # noqa: E402

_PKG = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# The tripwire: every way SEM can reach the recorder, wired to a list
# ---------------------------------------------------------------------------


@contextmanager
def _recorder_tripwire(reads: list):
    """Catch every recorder read, whichever door it comes through.

    ``get_instance`` is the door for history and for anything handed to the
    recorder's executor; ``statistics_during_period`` is called directly by
    the yearly seed. Both record the call and answer with nothing, so a
    caller that gets through is visible but not broken.
    """

    class _FakeInstance:
        keep_days = 10

        async def async_add_executor_job(self, func, *args):
            reads.append(getattr(func, "__name__", repr(func)))
            return {}

    def _get_instance(_hass):
        return _FakeInstance()

    def _statistics(*args, **kwargs):
        reads.append("statistics_during_period")
        return {}

    with patch(
        "homeassistant.components.recorder.get_instance", _get_instance,
    ), patch(
        "homeassistant.components.recorder.statistics.statistics_during_period",
        _statistics,
    ):
        yield


async def _boot(hass, entry) -> None:
    """Set the entry up the way a real boot does — HA still starting."""
    from homeassistant.core import CoreState

    hass.set_state(CoreState.starting)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _start(hass) -> None:
    """Finish the boot: HA is running and says so."""
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
    from homeassistant.core import CoreState

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# 1 + 2 — the oracle, and the proof it is not empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_reads_the_recorder_not_once(
    hass, sem_config_entry, enable_custom_integrations,
) -> None:
    """The bug itself. Every read here is charged to Home Assistant's
    start-up budget, and the bill arrives as a cancelled setup."""
    reads: list = []
    with _recorder_tripwire(reads):
        await _boot(hass, sem_config_entry)

    assert reads == [], (
        f"setup read the recorder {len(reads)} time(s): {reads} — "
        "that is the budget @alexmc1510's install ran out of"
    )
    assert sem_config_entry.entry_id in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_the_reads_still_happen_once_home_assistant_has_started(
    hass, sem_config_entry, enable_custom_integrations,
) -> None:
    """The other half. If the reads had simply been deleted, the test above
    would pass and SEM would have lost its cold start — no history for the
    taper detector, no real rating for a load, no install date."""
    reads: list = []
    with _recorder_tripwire(reads):
        await _boot(hass, sem_config_entry)
        assert reads == []
        await _start(hass)

    assert reads, (
        "nothing read the recorder after start either — the setup test "
        "above proves nothing"
    )

    # Name the two switches as well. The read above could come from any one
    # caller; these say that EVERY deferred seed was handed its turn — and
    # they are what goes red if the hand-over is deleted rather than moved.
    coordinator = hass.data[DOMAIN][sem_config_entry.entry_id]
    assert coordinator._recorder_seeds_ready is True, (
        "the coordinator never got its turn — the EV history seed, the "
        "install date and the yearly totals are gone, not deferred"
    )
    assert coordinator._device_registry._history_seeds_enabled is True, (
        "the rated-power seed never got its turn — every load keeps the "
        "1 kW placeholder for the whole session"
    )


# ---------------------------------------------------------------------------
# 3 — deferred, not dropped
# ---------------------------------------------------------------------------


def _registry():
    from custom_components.solar_energy_management.features.device_registry import (
        UnifiedDeviceRegistry,
    )

    reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    dev = MagicMock()
    dev.is_ev = False
    dev.power_entity_id = "sensor.pool_pump_power"
    dev.rated_power = 1000.0
    dev.rated_power_measured = False
    reg._surplus_controller = MagicMock()
    reg._surplus_controller._devices = {"pool": dev}
    reg._rated_power_overrides = {}
    reg._rating_seed_attempted = set()
    reg._save_storage = AsyncMock()
    reg._history_held_power = AsyncMock(return_value=430.0)
    return reg, dev


@pytest.mark.asyncio
async def test_the_rating_seed_waits_and_then_runs() -> None:
    """During setup the load is left alone — and left UNTRIED, so the seed
    happens one pass later instead of being lost for the session."""
    reg, dev = _registry()

    await reg._seed_and_apply_ratings()
    assert reg._history_held_power.await_count == 0
    assert reg._rating_seed_attempted == set(), (
        "the load was marked as tried while the recorder was off limits — "
        "it would never be seeded again this session"
    )

    await reg.async_seed_ratings_from_history()
    assert reg._history_held_power.await_count == 1
    assert dev.rated_power == 430.0
    reg._save_storage.assert_awaited()


# ---------------------------------------------------------------------------
# 4 — one door, so a new caller cannot re-open the hole
# ---------------------------------------------------------------------------


#: Every way Home Assistant offers to read an entity's past. All of them
#: belong to ``recorder_history.py`` — a caller reaching for a different
#: name is how this bug comes back.
_HISTORY_APIS = (
    "state_changes_during_period",
    "get_significant_states",
    "get_last_state_changes",
    "get_full_significant_states_with_session",
)


def test_history_is_read_in_one_place_only() -> None:
    """The cheap shape and the after-start rule both live behind one door."""
    offenders = []
    for path in _PKG.rglob("*.py"):
        if "tests" in path.parts or path.name == "recorder_history.py":
            continue
        if "scripts" in path.parts:
            continue                      # offline tools, no Home Assistant
        text = path.read_text(encoding="utf-8")
        for api in _HISTORY_APIS:
            if api in text:
                offenders.append(f"{path.relative_to(_PKG)}: {api}")
    assert not offenders, (
        f"these read history directly instead of through "
        f"coordinator/recorder_history.py: {offenders}"
    )


# ---------------------------------------------------------------------------
# 5 — the cheap shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_query_leaves_the_attributes_in_the_database() -> None:
    """Loading attributes is most of the cost of a long window, and no
    reader here wants them."""
    from custom_components.solar_energy_management.coordinator import (
        recorder_history,
    )

    seen = {}

    def _query(hass, start, end, entity_id, **kwargs):
        seen.update(kwargs)
        seen["days"] = round((end - start).total_seconds() / 86400)
        return {entity_id: []}

    class _Instance:
        keep_days = 10
        auto_purge = True

        async def async_add_executor_job(self, func, *args):
            return func(*args)

    with patch(
        "homeassistant.components.recorder.get_instance", lambda _h: _Instance(),
    ), patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _query,
    ):
        out = await recorder_history.read_states(MagicMock(), "sensor.x", 60)

    assert out == []
    assert seen["no_attributes"] is True
    assert "include_start_time_state" not in seen, (
        "the state in force when the window opened is wanted — a sensor "
        "that held one value all week has no state change to find"
    )
    assert seen["days"] == 10, (
        "asked for 60 days from a recorder that keeps 10 — 50 days of "
        "database work with nothing to find"
    )


@pytest.mark.asyncio
async def test_a_recorder_that_cannot_answer_says_so() -> None:
    """``None`` is "the recorder could not answer", ``[]`` is "it answered
    and there was nothing". The EV seed raises a Repair on the first and
    stays quiet on the second."""
    from custom_components.solar_energy_management.coordinator import (
        recorder_history,
    )

    def _boom(_hass):
        raise KeyError("recorder")

    with patch("homeassistant.components.recorder.get_instance", _boom):
        assert await recorder_history.read_states(MagicMock(), "sensor.x", 7) is None


@pytest.mark.asyncio
async def test_a_recorder_nobody_purges_keeps_its_whole_history() -> None:
    """``keep_days`` is what auto-purge deletes past. With auto-purge off
    the database holds everything, and cutting the window there would throw
    away the history the seed came for."""
    from custom_components.solar_energy_management.coordinator import (
        recorder_history,
    )

    seen = {}

    def _query(hass, start, end, entity_id, **kwargs):
        seen["days"] = round((end - start).total_seconds() / 86400)
        return {}

    class _Instance:
        keep_days = 10
        auto_purge = False

        async def async_add_executor_job(self, func, *args):
            return func(*args)

    with patch(
        "homeassistant.components.recorder.get_instance", lambda _h: _Instance(),
    ), patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _query,
    ):
        await recorder_history.read_states(MagicMock(), "sensor.x", 60)

    assert seen["days"] == 60


@pytest.mark.asyncio
async def test_a_recorder_that_cannot_answer_is_not_no_history() -> None:
    """The charger report is read by users. "No history" means the charger
    has none; a recorder that was busy must not be filed under it."""
    from custom_components.solar_energy_management.coordinator import wpa_replay

    async def _nothing(*_a, **_k):
        return None

    with patch(
        "custom_components.solar_energy_management.coordinator"
        ".recorder_history.read_states", _nothing,
    ):
        with pytest.raises(RuntimeError):
            await wpa_replay.read_series(MagicMock(), "sensor.x", 7)


def test_the_replay_is_forgotten_when_the_entry_goes_away() -> None:
    """A reload during the boot leaves the torn-down coordinator on the
    start event. Both would then replay, the old one through a storage
    nobody owns any more."""
    from types import SimpleNamespace

    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )

    cancelled = []
    obj = SimpleNamespace(_wpa_replay_unsub=lambda: cancelled.append(True))
    SEMCoordinator.cancel_pending_recorder_work(obj)
    assert cancelled == [True]
    assert obj._wpa_replay_unsub is None

    SEMCoordinator.cancel_pending_recorder_work(obj)   # idempotent
    assert cancelled == [True]
