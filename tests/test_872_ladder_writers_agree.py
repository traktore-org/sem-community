"""#872 item 3 — a writer must never store a ladder its own form rejects.

RienduPre's log, 30.08:

    Peak levels out of order (warning 7.5 / target 12.0 / emergency 8.0 kW)
    — using 7.5 / 12.0 / 14.4 for shedding decisions.

He filed it as his own misconfiguration and only flagged the *silence*. It
is not his misconfiguration, and the silence is the second half of a defect
we already fixed once.

#813 established the rule after it bit on PROD at 6.0/6.0: **a writer must
leave a state its own form accepts.** ``update_target_peak_limit`` carries
the other two levels with it for exactly that reason. The other two writers
— reachable from the Config tab through ``set_option`` (``__init__.py``'s
``_LM_LIVE_KEYS``) — never got the same treatment, so raising the warning
above the target, or dropping the emergency below it, stores precisely the
inverted ladder the options page then refuses to save.

That is why Rien met a warning about numbers he never typed together: the
decision path repairs the ladder in memory every cycle (``_effective_levels``)
while the store keeps the broken one. Two places, two answers.

One rule, applied by every writer AND by the decision path, so the stored
ladder and the effective ladder are the same ladder.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.features.load_management import (
    LoadManagementCoordinator,
)
from custom_components.solar_energy_management.consts.core import (
    EMERGENCY_PEAK_RATIO,
    WARNING_PEAK_RATIO,
)


def _lm(*, target=6.0, warning=4.5, emergency=7.2):
    lm = LoadManagementCoordinator.__new__(LoadManagementCoordinator)
    lm.hass = MagicMock()
    lm.config_entry = MagicMock(options={})
    lm.config_entry.runtime_data = MagicMock()
    lm._target_peak_limit = target
    lm._warning_level = warning
    lm._emergency_level = emergency
    lm._peak_unlimited = False
    lm._logged_ladder_repair = False
    lm._trigger_callbacks = MagicMock()
    return lm


def _stored(lm) -> dict:
    """The options dict actually handed to async_update_entry."""
    call = lm.hass.config_entries.async_update_entry.call_args
    assert call is not None, "nothing was persisted"
    return call.kwargs["options"]


@pytest.mark.asyncio
class TestTheStoreMatchesTheDecision:
    """Whatever a writer persists must be what the decision path uses."""

    async def test_warning_above_target_is_not_stored_inverted(self):
        lm = _lm(target=6.0)
        await lm.update_warning_peak_level(8.0)          # above the target
        stored = _stored(lm)
        assert stored["warning_peak_level"] < 6.0, (
            "stored a warning level above the target — the options page "
            "refuses to save this, on a page the user never touched (#813)"
        )
        assert lm._warning_level == stored["warning_peak_level"]

    async def test_emergency_below_target_is_not_stored_inverted(self):
        lm = _lm(target=6.0)
        await lm.update_emergency_peak_level(5.0)        # below the target
        stored = _stored(lm)
        assert stored["emergency_peak_level"] > 6.0, (
            "an emergency at or below the target makes the EMERGENCY branch "
            "win before SHEDDING is ever considered — SEM dumps loads the "
            "moment the target is touched"
        )
        assert lm._emergency_level == stored["emergency_peak_level"]

    async def test_the_repaired_value_is_the_one_the_ladder_uses(self):
        """Store and decision path agree, so no cycle logs a repair."""
        lm = _lm(target=6.0)
        await lm.update_warning_peak_level(8.0)
        await lm.update_emergency_peak_level(5.0)
        warning, emergency = lm._effective_levels()
        assert warning == lm._warning_level
        assert emergency == lm._emergency_level
        assert lm._logged_ladder_repair is False, (
            "the decision path repaired a ladder a writer had just stored — "
            "the two disagree, which is the whole defect"
        )

    async def test_repair_uses_the_install_flow_ratios(self):
        lm = _lm(target=10.0)
        await lm.update_warning_peak_level(12.0)
        await lm.update_emergency_peak_level(9.0)
        assert lm._warning_level == round(10.0 * WARNING_PEAK_RATIO, 1)
        assert lm._emergency_level == round(10.0 * EMERGENCY_PEAK_RATIO, 1)


@pytest.mark.asyncio
class TestValidLaddersAreLeftAlone:
    """The repair is for inverted input only — it must not move a good value."""

    async def test_a_warning_below_the_target_is_stored_verbatim(self):
        lm = _lm(target=6.0)
        await lm.update_warning_peak_level(3.0)
        assert lm._warning_level == 3.0
        assert _stored(lm)["warning_peak_level"] == 3.0

    async def test_an_emergency_above_the_target_is_stored_verbatim(self):
        lm = _lm(target=6.0)
        await lm.update_emergency_peak_level(7.5)
        assert lm._emergency_level == 7.5
        assert _stored(lm)["emergency_peak_level"] == 7.5

    async def test_an_unlimited_install_has_no_ladder_to_order(self):
        """(#716) No grid ceiling → the three numbers are meaningless, so
        the writer must not invent a repair the config flow itself skips."""
        lm = _lm(target=6.0)
        lm._peak_unlimited = True
        await lm.update_warning_peak_level(8.0)
        assert lm._warning_level == 8.0
        assert _stored(lm)["warning_peak_level"] == 8.0
