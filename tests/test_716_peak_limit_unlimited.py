"""#716 — an explicit "this install has no grid ceiling" opt-out.

Azlinon asked whether, instead of raising the cap (#717), peak management could
just be turned off. It can, but only as its OWN switch. Three properties this
module pins, each of which is a way the obvious implementation goes wrong:

1. **Unlimited is a boolean, never a sentinel.** The tempting spelling is
   ``target_peak_limit == 0 → no limit``. #638 finding #5 is what that costs:
   the battery scheduler read ``config["peak_limit_w"]``, a key nothing ever
   wrote, got 0, concluded "no limit" and handed a 5 kW house a 10 kW EV slot.
   A limit whose disabled state is reachable by accident fails OPEN, which is
   the wrong direction for a physical ceiling.

2. **``load_management_enabled = False`` does NOT mean unlimited.** That switch
   governs whether SEM *sheds*; the ceiling still constrains everything SEM
   *sizes*. Conflating them would let "stop shedding my loads" silently hand
   the EV the whole house. (This is not hypothetical: ``coordinator.py`` skips
   constructing the LoadManager when load management is off, and
   ``_get_peak_limit_w`` then falls through to the raw config value — the
   ceiling deliberately survives.)

3. **Infinity is contained to arithmetic.** ``round(float('inf'))`` raises
   ``OverflowError``, and both EV sizing paths round limit-derived headroom.
   The saturating helper exists for that, and no published value — sensor,
   ``get_load_management_data()`` dict, card attribute — may ever carry an inf.
"""
import math
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.const import (
    DEFAULT_PEAK_LIMIT_UNLIMITED,
)
from custom_components.solar_energy_management.coordinator.ev_control import (
    amps_from_headroom,
)

_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# 1. The saturating amps helper — the only thing standing between an
#    unlimited install and an OverflowError in the control loop.
# --------------------------------------------------------------------------
@pytest.mark.unit
class TestAmpsFromHeadroom:
    def test_infinite_headroom_returns_max_not_overflow(self):
        """The regression this helper exists for.

        The pre-#716 expression was ``round(headroom / watts_per_amp)`` with
        the clamp applied to the result. Rounding first means an unlimited
        install raises OverflowError inside the EV control loop — on exactly
        the installs the flag was added to serve.
        """
        assert amps_from_headroom(math.inf, 690.0, 6, 32) == 32

    def test_the_old_expression_would_have_raised(self):
        """Pin the failure mode, so nobody "simplifies" the helper back."""
        with pytest.raises(OverflowError):
            round(math.inf / 690.0)

    def test_negative_infinity_returns_min(self):
        assert amps_from_headroom(-math.inf, 690.0, 6, 32) == 6

    @pytest.mark.parametrize(
        "headroom_w,expected",
        [
            (0.0, 6),            # nothing available → floor
            (690.0 * 3, 6),      # below min → floor
            (690.0 * 10, 10),    # in band → exact
            (690.0 * 10.4, 10),  # in band → rounds down
            (690.0 * 10.6, 11),  # in band → rounds up
            (690.0 * 50, 32),    # above max → ceiling
        ],
    )
    def test_finite_path_unchanged(self, headroom_w, expected):
        """Saturating early must not move any finite answer."""
        assert amps_from_headroom(headroom_w, 690.0, 6, 32) == expected

    def test_zero_watts_per_amp_does_not_divide_by_zero(self):
        assert amps_from_headroom(5000.0, 0.0, 6, 32) == 32


# --------------------------------------------------------------------------
# 2. The EV controller's peak read.
# --------------------------------------------------------------------------
def _ev_host(config):
    """Minimal object exposing the EVControlMixin methods under test."""
    from custom_components.solar_energy_management.coordinator.ev_control import (
        EVControlMixin,
    )

    class _Host(EVControlMixin):
        def __init__(self, cfg):
            self.config = cfg
            self._load_manager = None

    return _Host(config)


@pytest.mark.unit
class TestPeakLimitRead:
    def test_default_is_limited(self):
        assert DEFAULT_PEAK_LIMIT_UNLIMITED is False

    def test_absent_key_is_limited(self):
        """A config that predates the flag keeps its ceiling."""
        host = _ev_host({"target_peak_limit": 5.0})
        assert host._get_peak_limit_w() == 5000.0

    def test_flag_set_returns_infinity(self):
        host = _ev_host({"target_peak_limit": 5.0, "peak_limit_unlimited": True})
        assert host._get_peak_limit_w() == math.inf

    def test_load_management_disabled_is_NOT_unlimited(self):
        """Property 2 — the fail-closed boundary.

        Turning shedding off must leave the sizing ceiling standing. If this
        ever flips, an install that only wanted its loads left alone silently
        hands the EV the whole house.
        """
        host = _ev_host(
            {"target_peak_limit": 5.0, "load_management_enabled": False}
        )
        assert host._get_peak_limit_w() == 5000.0

    def test_zero_target_is_not_a_no_limit_sentinel(self):
        """Property 1 — 0 must stay a number, not a magic word."""
        host = _ev_host({"target_peak_limit": 0.0})
        assert host._get_peak_limit_w() == 0.0
        assert not math.isinf(host._get_peak_limit_w())

    def test_load_manager_value_wins_when_limited(self):
        host = _ev_host({"target_peak_limit": 5.0})
        lm = MagicMock()
        lm.get_load_management_data.return_value = {"target_peak_limit": 9.0}
        host._load_manager = lm
        assert host._get_peak_limit_w() == 9000.0

    def test_flag_beats_the_load_manager(self):
        """The opt-out short-circuits before the LoadManager is consulted, so
        a stale stored limit can't leak back in."""
        host = _ev_host({"target_peak_limit": 5.0, "peak_limit_unlimited": True})
        lm = MagicMock()
        lm.get_load_management_data.return_value = {"target_peak_limit": 9.0}
        host._load_manager = lm
        assert host._get_peak_limit_w() == math.inf


# --------------------------------------------------------------------------
# 3. LoadManager: never escalate when unlimited; repair an inverted ladder.
# --------------------------------------------------------------------------
def _load_manager(**cfg):
    from custom_components.solar_energy_management.features.load_management import (
        LoadManagementCoordinator,
    )

    entry = MagicMock()
    entry.data = {
        "target_peak_limit": 5.0,
        "warning_peak_level": 4.5,
        "emergency_peak_level": 6.0,
        **cfg,
    }
    entry.options = {}
    hass = MagicMock()
    return LoadManagementCoordinator(hass, entry)


@pytest.mark.unit
class TestLoadManagerUnlimited:
    def test_default_ladder_still_escalates(self):
        """Control case — without the flag nothing about shedding changes."""
        from custom_components.solar_energy_management.features.load_management import (
            LoadManagementState,
        )

        lm = _load_manager()
        assert lm._determine_load_management_state(3.0, 3.0) == LoadManagementState.NORMAL
        assert lm._determine_load_management_state(4.6, 4.6) == LoadManagementState.WARNING
        assert lm._determine_load_management_state(5.2, 5.2) == LoadManagementState.SHEDDING
        assert lm._determine_load_management_state(7.0, 7.0) == LoadManagementState.EMERGENCY

    @pytest.mark.parametrize("peak", [3.0, 4.6, 5.2, 7.0, 500.0])
    def test_unlimited_never_escalates(self, peak):
        from custom_components.solar_energy_management.features.load_management import (
            LoadManagementState,
        )

        lm = _load_manager(peak_limit_unlimited=True)
        assert lm._determine_load_management_state(peak, peak) == LoadManagementState.NORMAL
        assert lm._last_state_decision_path == "peak_limit_unlimited_normal"

    def test_unlimited_ignores_stale_levels(self):
        """A user who opts out leaves the old kW numbers in config. They must
        not shed on the way past."""
        from custom_components.solar_energy_management.features.load_management import (
            LoadManagementState,
        )

        lm = _load_manager(
            peak_limit_unlimited=True,
            target_peak_limit=5.0,
            emergency_peak_level=6.0,
        )
        assert lm._determine_load_management_state(50.0, 50.0) == LoadManagementState.NORMAL

    def test_flag_is_published_for_the_cards(self):
        lm = _load_manager(peak_limit_unlimited=True)
        data = lm.get_load_management_data()
        assert data["peak_limit_unlimited"] is True

    def test_published_data_never_carries_an_infinity(self):
        """Containment: inf lives inside ev_control's arithmetic and nowhere
        else. A card rendering `Infinity`/`NaN` is the visible symptom of a
        leak, so assert on every numeric the dict publishes."""
        lm = _load_manager(peak_limit_unlimited=True)
        for key, value in lm.get_load_management_data().items():
            if isinstance(value, float):
                assert math.isfinite(value), f"{key} = {value}"


@pytest.mark.unit
class TestLadderRepairAtReadTime:
    """#717's ordering validation lives in the options flow, which is not the
    only writer: ``set_option`` writes arbitrary keys with no validation, and
    entries created before that check existed may already hold an inverted
    ladder. Repairing at read time covers both."""

    def test_ordered_ladder_is_left_alone(self):
        lm = _load_manager()
        assert lm._effective_levels() == (4.5, 6.0)

    def test_low_emergency_is_repaired_above_the_target(self):
        """The dangerous end. ``emergency <= target`` makes the EMERGENCY
        branch win before SHEDDING is ever considered — SEM dumps loads the
        instant the target is touched. The repair puts it back on its own side
        of the target, at the install flow's ratio (5.0 × 1.2)."""
        lm = _load_manager(emergency_peak_level=3.0)
        warning, emergency = lm._effective_levels()
        assert emergency == 6.0
        assert emergency > lm._target_peak_limit

    def test_low_emergency_does_not_dump_loads_at_the_target(self):
        """Why the repair can't simply clamp *to* the target: the EMERGENCY
        branch tests ``>=``, so ``emergency == target`` still swallows the
        whole SHEDDING stage."""
        from custom_components.solar_energy_management.features.load_management import (
            LoadManagementState,
        )

        lm = _load_manager(emergency_peak_level=3.0)
        # Without the repair this returns EMERGENCY: 5.1 >= 3.0.
        assert lm._determine_load_management_state(5.1, 5.1) == LoadManagementState.SHEDDING
        # And the stage above it is still reachable.
        assert lm._determine_load_management_state(6.5, 6.5) == LoadManagementState.EMERGENCY

    def test_high_warning_is_repaired_below_the_target(self):
        lm = _load_manager(warning_peak_level=9.0)
        warning, _ = lm._effective_levels()
        assert warning == 4.5
        assert warning < lm._target_peak_limit

    def test_repair_does_not_mutate_stored_config(self):
        """The user's numbers stay as they typed them, so they can put the
        ladder back in order themselves."""
        lm = _load_manager(emergency_peak_level=3.0, warning_peak_level=9.0)
        lm._effective_levels()
        assert lm._emergency_level == 3.0
        assert lm._warning_level == 9.0

    def test_repair_logs_once_not_every_cycle(self):
        """This runs on every coordinator cycle; an unconditional warning
        would be a log flood at 10-second cadence."""
        lm = _load_manager(emergency_peak_level=3.0)
        assert lm._logged_ladder_repair is False
        lm._effective_levels()
        assert lm._logged_ladder_repair is True
        lm._effective_levels()
        assert lm._logged_ladder_repair is True

    def test_ordered_ladder_logs_nothing(self):
        lm = _load_manager()
        lm._effective_levels()
        assert lm._logged_ladder_repair is False


# --------------------------------------------------------------------------
# 4. The battery scheduler's own no-limit sentinel.
# --------------------------------------------------------------------------
@pytest.mark.unit
class TestBatterySchedulerSeed:
    """``SchedulerConfig.peak_limit_w`` predates the flag and spells no-limit
    as ``0.0``. #716 translates rather than plumbs infinity through, because
    the slot arithmetic downstream has no infinity handling."""

    def _cfg(self, **kw):
        from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
            SchedulerConfig,
        )

        return SchedulerConfig.from_config({"target_peak_limit": 9.0, **kw})

    def test_limited_seeds_the_target(self):
        assert self._cfg().peak_limit_w == 9000.0

    def test_unlimited_seeds_zero(self):
        assert self._cfg(peak_limit_unlimited=True).peak_limit_w == 0.0

    def test_unlimited_seed_is_finite(self):
        """Not ``inf`` — see the class docstring."""
        cfg = self._cfg(peak_limit_unlimited=True)
        assert math.isfinite(cfg.peak_limit_w)


# --------------------------------------------------------------------------
# 5. Config-flow + string surface.
# --------------------------------------------------------------------------
@pytest.mark.unit
class TestConfigSurface:
    def test_options_flow_offers_the_toggle(self):
        src = (_ROOT / "config_flow.py").read_text()
        assert '"peak_limit_unlimited"' in src

    def test_ordering_validation_is_skipped_when_unlimited(self):
        """An install with no ceiling has no ladder to order. Demanding three
        well-ordered numbers before it can save the opt-out is a dead end."""
        src = (_ROOT / "config_flow.py").read_text()
        assert 'if not user_input.get("peak_limit_unlimited", False):' in src

    def test_declared_in_every_language(self):
        import json

        files = [_ROOT / "strings.json"] + sorted(
            (_ROOT / "translations").glob("*.json")
        )
        assert len(files) == 17, [f.name for f in files]
        missing = []
        for path in files:
            block = json.loads(path.read_text(encoding="utf-8"))
            step = block["options"]["step"]["load_management"]
            for section in ("data", "data_description"):
                if "peak_limit_unlimited" not in step[section]:
                    missing.append(f"{path.name}:{section}")
        assert not missing, missing

    def test_card_strings_declared_in_every_language(self):
        import json

        data = json.loads(
            (_ROOT / "dashboard" / "translations.json").read_text(encoding="utf-8")
        )
        missing = [
            f"{lang}:{key}"
            for lang, block in data.items()
            for key in (
                "config_lm_unlimited",
                "config_help_lm_unlimited",
                "config_lm_unlimited_value",
            )
            if key not in block
        ]
        assert not missing, missing

    def test_config_card_renders_the_toggle(self):
        src = (
            _ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js"
        ).read_text()
        assert "'peak_limit_unlimited'" in src
        assert "config_lm_unlimited_value" in src

    def test_bundle_is_rebuilt(self):
        """Deploy scripts only rsync — an un-rebuilt bundle ships the old
        card (CLAUDE.md gotcha #5)."""
        bundle = (
            _ROOT / "dashboard" / "card" / "dist" / "sem-cards.js"
        ).read_text()
        assert "peak_limit_unlimited" in bundle

    def test_localize_bundle_is_regenerated(self):
        js = (_ROOT / "dashboard" / "card" / "sem-localize.js").read_text()
        assert "config_lm_unlimited_value" in js


# --------------------------------------------------------------------------
# 6. No new 0-as-no-limit sentinels.
# --------------------------------------------------------------------------
@pytest.mark.unit
def test_no_zero_sentinel_reintroduced_for_target_peak_limit():
    """``target_peak_limit`` must never regain a magic zero.

    The battery scheduler's ``peak_limit_w`` keeps its own documented
    ``0 = no limit`` (it predates the flag and is fed by the translation
    above), but the user-facing key must stay a plain number whose disabled
    state is a separate boolean — see this module's docstring, property 1.
    """
    import io
    import re
    import tokenize

    def _code_only(source: str) -> list:
        """The scan looks for a comparison, so it must see code and only code.

        Prose describing the rule — this module's own docstrings, and the
        comment beside ``DEFAULT_PEAK_LIMIT_UNLIMITED`` explaining why the flag
        is a boolean and not ``target_peak_limit == 0`` — otherwise trips the
        guard that documents it. Blank out every comment and string token,
        keeping line numbers intact.
        """
        lines = source.splitlines()
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            return lines
        for tok in tokens:
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                continue
            (srow, scol), (erow, ecol) = tok.start, tok.end
            for row in range(srow, erow + 1):
                line = lines[row - 1]
                start = scol if row == srow else 0
                end = ecol if row == erow else len(line)
                lines[row - 1] = line[:start] + " " * (end - start) + line[end:]
        return lines

    hits = []
    for path in _ROOT.rglob("*.py"):
        if "tests" in path.parts or "node_modules" in path.parts:
            continue
        for num, line in enumerate(_code_only(path.read_text()), 1):
            if "target_peak_limit" not in line:
                continue
            if re.search(r"target_peak_limit[^\n]*==\s*0", line) or re.search(
                r"0\s*==[^\n]*target_peak_limit", line
            ):
                hits.append(f"{path.relative_to(_ROOT)}:{num}: {line.strip()}")
    assert not hits, (
        "target_peak_limit compared against 0 as a no-limit sentinel — use "
        "the explicit peak_limit_unlimited flag (#716):\n  " + "\n  ".join(hits)
    )
