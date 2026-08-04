"""#717 — the peak-limit ceiling has to fit the grid, not a European fuse box.

Azlinon's report: the Target Peak Limit slider stops at 15 kW. His service is
larger, so SEM was permanently convinced his house was over its limit and shed
loads it had no reason to shed. The number is not a preference — it is the size
of the wire coming into the building, and that ranges from a 3 kW South-European
contract to a ~77 kW North-American 400 A split-phase service.

Two things made this worse than "one slider is too short":

* **Ten controls, five different ceilings.** Install form 20 kW; three options
  fields 15/15/20; the ``update_target_peak`` service ``vol.Range`` 20; the
  config card 15/15/20; the load-priority card input 20 *plus* a silent
  ``val <= 20`` guard that dropped the write with no error at all. Raising only
  the 15 kW field Azlinon happened to hit would have moved his wall to 20 kW.
* **The two shed levels did not move with the target.** ``warning_peak_level``
  and ``emergency_peak_level`` were flat 4.5/6.0 kW defaults, and the install
  flow writes them without ever asking. ``LoadManager`` escalates to EMERGENCY
  at ``peak >= emergency_level``, so a 38 kW service with 6.0 kW still in the
  emergency field goes into emergency shedding at an oven plus a dryer. Bug
  class: raising a bound without re-deriving what was scaled to the old one.

The fix makes the levels a RATIO of the target. 0.9/1.2 reproduce 4.5/6.0
exactly at the 5.0 kW default, so a default install is byte-identical — the
first test below is what pins that.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solar_energy_management.config_flow import (
    OptionsFlowHandler,
    derive_peak_levels,
)
from custom_components.solar_energy_management.const import (
    DEFAULT_EMERGENCY_PEAK_LEVEL,
    DEFAULT_TARGET_PEAK_LIMIT,
    DEFAULT_WARNING_PEAK_LEVEL,
    EMERGENCY_PEAK_RATIO,
    MAX_PEAK_LIMIT_KW,
    MIN_PEAK_LIMIT_KW,
    PEAK_LIMIT_STEP_KW,
    WARNING_PEAK_RATIO,
)

_ROOT = Path(__file__).resolve().parent.parent
_CARDS = _ROOT / "dashboard" / "card" / "src" / "cards"


# ---------------------------------------------------------------------------
# The ladder derivation
# ---------------------------------------------------------------------------

def test_the_default_install_is_byte_identical():
    """The whole reason the ratios are 0.9/1.2 and not something rounder.

    Every existing install has 5.0/4.5/6.0 stored. If ``derive_peak_levels``
    produced anything else at the default target, this change would silently
    re-tune load shedding on every European system that never asked for it.
    """
    assert derive_peak_levels(DEFAULT_TARGET_PEAK_LIMIT) == (
        DEFAULT_WARNING_PEAK_LEVEL,
        DEFAULT_EMERGENCY_PEAK_LEVEL,
    )
    assert (DEFAULT_WARNING_PEAK_LEVEL, DEFAULT_EMERGENCY_PEAK_LEVEL) == (4.5, 6.0)


@pytest.mark.parametrize(
    "target",
    [
        MIN_PEAK_LIMIT_KW,
        3.0,
        DEFAULT_TARGET_PEAK_LIMIT,
        11.0,   # 3x16 A European
        17.3,   # 3x25 A European
        38.4,   # 200 A North-American split-phase — Azlinon's shape
        69.0,   # 3x100 A European
        MAX_PEAK_LIMIT_KW,
    ],
)
def test_the_ladder_stays_ordered_at_every_service_size(target):
    """warning < target < emergency, or ``LoadManager`` sheds against the
    wrong number. This is the invariant the options flow now enforces on
    input; here it is checked on everything the install flow can derive."""
    warning, emergency = derive_peak_levels(target)
    assert warning < target < emergency, (target, warning, emergency)


def test_the_levels_actually_scale():
    """Bug class 8 — a derivation that returned the old constants for every
    target would pass the ordering test at 5.0 kW and fail every real user."""
    small = derive_peak_levels(5.0)
    large = derive_peak_levels(38.4)
    assert large[0] > small[0] and large[1] > small[1]
    assert large == (round(38.4 * WARNING_PEAK_RATIO, 1),
                     round(38.4 * EMERGENCY_PEAK_RATIO, 1))


def test_a_target_outside_the_range_is_clamped_not_propagated():
    """Garbage in must not become a 900 kW emergency level in stored config."""
    assert derive_peak_levels(0) == derive_peak_levels(MIN_PEAK_LIMIT_KW)
    assert derive_peak_levels(10_000) == derive_peak_levels(MAX_PEAK_LIMIT_KW)


# ---------------------------------------------------------------------------
# Every surface shares one range
# ---------------------------------------------------------------------------

_PEAK_KEYS = ("target_peak_limit", "warning_peak_level", "emergency_peak_level")


def _number_selector_bounds(source: str, key: str) -> list[tuple[str, str]]:
    """``(min, max)`` source text of every NumberSelector guarding ``key``.

    The gap between the key and its selector must not swallow another schema
    entry — a greedy ``.*?`` happily matched ``"target_peak_limit"`` against a
    ``NumberSelectorConfig`` fifty lines further down and reported that
    field's bounds instead.
    """
    out: list[tuple[str, str]] = []
    for match in re.finditer(
        rf'"{key}",(?:(?!vol\.(?:Required|Optional)).)*?'
        r"NumberSelectorConfig\((.*?)\)\s*\)",
        source,
        re.S,
    ):
        body = match.group(1)
        lo = re.search(r"min=([A-Za-z_0-9.]+)", body)
        hi = re.search(r"max=([A-Za-z_0-9.]+)", body)
        assert lo and hi, f"no min/max in the {key} selector: {body!r}"
        out.append((lo.group(1), hi.group(1)))
    return out


def test_no_python_surface_hard_codes_a_ceiling():
    """The five-different-ceilings failure, pinned.

    Every peak-limit number input in ``config_flow.py`` — install step and
    options step alike — must be bounded by the shared constants. A literal
    here is how the install form ended up 5 kW wider than the options form
    that edits the same key.
    """
    source = (_ROOT / "config_flow.py").read_text(encoding="utf-8")
    seen = 0
    for key in _PEAK_KEYS:
        bounds = _number_selector_bounds(source, key)
        assert bounds, f"no NumberSelector found for {key} — retarget this scan"
        for lo, hi in bounds:
            assert (lo, hi) == ("MIN_PEAK_LIMIT_KW", "MAX_PEAK_LIMIT_KW"), (
                f"{key} is bounded by literals {lo}..{hi} instead of the shared "
                "constants (#717)"
            )
            seen += 1
    assert seen >= 4, f"only {seen} peak selectors found — the scan broke"


def test_the_service_accepts_a_north_american_service():
    """``update_target_peak`` had its own 20 kW ``vol.Range``. Dashboard cards
    and automations go through the service, so a wider form alone would still
    have left Azlinon unable to set his real limit."""
    source = (_ROOT / "__init__.py").read_text(encoding="utf-8")
    match = re.search(
        r'vol\.Required\("target_peak_limit"\)[^\n]*\n(?:[^\n]*\n){0,4}?'
        r"[^\n]*vol\.Range\(min=([A-Za-z_0-9.]+), max=([A-Za-z_0-9.]+)\)",
        source,
    )
    assert match, "update_target_peak's vol.Range is gone — retarget this scan"
    assert match.groups() == ("MIN_PEAK_LIMIT_KW", "MAX_PEAK_LIMIT_KW")

    schema = vol.Schema({
        vol.Required("target_peak_limit"): vol.All(
            vol.Coerce(float),
            vol.Range(min=MIN_PEAK_LIMIT_KW, max=MAX_PEAK_LIMIT_KW),
        ),
    })
    assert schema({"target_peak_limit": 38.4})["target_peak_limit"] == 38.4
    with pytest.raises(vol.Invalid):
        schema({"target_peak_limit": MAX_PEAK_LIMIT_KW + 1})


@pytest.mark.parametrize(
    "card,pattern",
    [
        # The three config-card fields. Number inputs, not sliders: 791 stops
        # at 0.1 kW is not a control, it is a hazard.
        ("sem-config-card.js", r"'(?:target_peak_limit|warning_peak_level|"
                               r"emergency_peak_level)'"),
        # The load-priority card's inline "Set" box.
        ("sem-load-priority-card.js", r'id="targetInput"'),
    ],
)
def test_no_card_hard_codes_the_old_ceiling(card, pattern):
    """The cards are a separate copy of the same bound, and they are what most
    users actually touch — the load-priority card silently *discarded* a value
    over 20 kW, so the user typed their real service size, pressed Set and
    nothing at all happened."""
    source = (_CARDS / card).read_text(encoding="utf-8")
    assert re.search(pattern, source), f"{card}: anchor gone — retarget this scan"
    for stale in (r"max:\s*(?:15|20)(?:\.0)?\b", r'max="(?:15|20)"',
                  r"val\s*<=\s*20\b", r"Math\.min\(\s*(?:15|20)\s*,"):
        assert not re.search(stale, source), (
            f"{card} still carries the retired {stale!r} peak ceiling (#717)"
        )
    assert re.search(r"(?:max:\s*80(?:\.0)?\b|max=\"80\"|Math\.min\(80,)", source), (
        f"{card} does not carry the {MAX_PEAK_LIMIT_KW:g} kW ceiling (#717)"
    )


# ---------------------------------------------------------------------------
# The install flow derives; the options flow validates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("target", [DEFAULT_TARGET_PEAK_LIMIT, 38.4])
async def test_install_derives_the_levels_from_the_entered_target(mock_hass, target):
    """The install form asks for the target and nothing else, then writes all
    three. Before #717 it wrote the seeded 4.5/6.0 next to whatever target the
    user typed — a 38 kW service configured to emergency-shed at 6 kW.

    Parametrised over the default too: at 5.0 kW the stored entry must still
    come out 4.5/6.0, which is what makes this safe to ship to every existing
    install.
    """
    from custom_components.solar_energy_management.config_flow import (
        SolarEnergyManagementConfigFlow,
    )

    flow = SolarEnergyManagementConfigFlow()
    flow.hass = mock_hass
    flow._data = {"observer_mode": False}
    flow._energy_dashboard_config = {}
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()

    with patch(
        "custom_components.solar_energy_management.config_flow."
        "discover_inverter_from_registry",
        return_value=None,
    ):
        result = await flow.async_step_hardware({
            "battery_capacity_kwh": 12,
            "target_peak_limit": target,
            "generate_dashboard_on_install": False,
        })

    assert result["type"] == FlowResultType.CREATE_ENTRY, result
    data = result["data"]
    assert data["target_peak_limit"] == target
    assert (data["warning_peak_level"], data["emergency_peak_level"]) == (
        derive_peak_levels(target)
    )
    assert data["warning_peak_level"] < target < data["emergency_peak_level"]


def _options_flow(mock_hass, config_entry):
    flow = OptionsFlowHandler(config_entry)
    flow.hass = mock_hass
    flow._data = {}
    return flow


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "levels,expected",
    [
        # The realistic mistake: raise the target, leave the rest behind.
        # Only the emergency level inverts -- 4.5 kW is still (uselessly) below
        # 38.4 -- and that is the dangerous half: emergency shedding at 6 kW.
        ({"target_peak_limit": 38.4, "warning_peak_level": 4.5,
          "emergency_peak_level": 6.0},
         {"emergency_peak_level": "peak_emergency_not_above_target"}),
        # Both ends wrong at once, so the flow must report both fields.
        ({"target_peak_limit": 5.0, "warning_peak_level": 6.0,
          "emergency_peak_level": 4.0},
         {"warning_peak_level": "peak_warning_not_below_target",
          "emergency_peak_level": "peak_emergency_not_above_target"}),
        # Equal is not "close enough": >= is what LoadManager compares with.
        ({"target_peak_limit": 5.0, "warning_peak_level": 5.0,
          "emergency_peak_level": 6.0},
         {"warning_peak_level": "peak_warning_not_below_target"}),
        ({"target_peak_limit": 5.0, "warning_peak_level": 4.5,
          "emergency_peak_level": 5.0},
         {"emergency_peak_level": "peak_emergency_not_above_target"}),
    ],
)
async def test_options_flow_refuses_an_inverted_ladder(
    mock_hass, config_entry, levels, expected,
):
    """Saving warning >= target means the warning can never fire in time;
    emergency <= target means SEM sheds hard *before* reaching the limit the
    setting exists to defend. Both used to save without a word."""
    flow = _options_flow(mock_hass, config_entry)
    with patch.object(type(flow), "config_entry", config_entry):
        result = await flow.async_step_load_management(
            {"load_management_enabled": True, **levels},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "load_management"
    assert result["errors"] == expected
    assert "target_peak_limit" not in flow._data, "a rejected ladder was stored"


@pytest.mark.asyncio
async def test_options_flow_accepts_a_north_american_ladder(mock_hass, config_entry):
    """The positive case, at a size the old 15/15/20 kW form could not express
    at all."""
    flow = _options_flow(mock_hass, config_entry)
    submitted = {
        "load_management_enabled": True,
        "target_peak_limit": 38.4,
        "warning_peak_level": 34.6,
        "emergency_peak_level": 46.1,
    }
    with patch.object(type(flow), "config_entry", config_entry):
        with patch.object(
            type(flow), "async_step_heat_pump",
            return_value={"type": "form", "step_id": "heat_pump"},
        ):
            result = await flow.async_step_load_management(submitted)

    assert result["step_id"] == "heat_pump"
    for key, value in submitted.items():
        assert flow._data[key] == value


# ---------------------------------------------------------------------------
# Strings
# ---------------------------------------------------------------------------

def test_the_two_new_errors_resolve_in_every_language():
    """Options-flow errors localise under ``options.error`` — see #674. A key
    only in ``config.error`` renders as ``peak_warning_not_below_target`` to
    the user."""
    wanted = {"peak_warning_not_below_target", "peak_emergency_not_above_target"}
    files = [_ROOT / "strings.json", *sorted((_ROOT / "translations").glob("*.json"))]
    assert len(files) >= 17
    for path in files:
        block = json.loads(path.read_text(encoding="utf-8"))["options"].get("error", {})
        missing = wanted - set(block)
        assert not missing, f"{path.name} is missing {sorted(missing)} (#717)"
        for key in wanted:
            assert block[key].strip(), f"{path.name}:{key} is empty"


def test_the_install_help_no_longer_assumes_a_european_fuse_box():
    """The old text told every user to size from "your fuse rating divided by
    4" and named 3-5 kW as typical — advice that produced exactly Azlinon's
    misconfiguration on a North-American service."""
    description = json.loads((_ROOT / "strings.json").read_text(encoding="utf-8"))
    text = description["config"]["step"]["hardware"]["data_description"][
        "target_peak_limit"
    ]
    assert "divided by 4" not in text
    assert "200 A" in text, "the help text no longer names a non-European size"


def test_the_constants_are_a_usable_range():
    """Bug class 8 for the constants themselves: every scan above compares
    against these, so a typo that made MAX smaller than MIN would make the
    surface tests vacuous rather than failing."""
    assert MIN_PEAK_LIMIT_KW < DEFAULT_TARGET_PEAK_LIMIT < MAX_PEAK_LIMIT_KW
    assert MAX_PEAK_LIMIT_KW >= 77.0, (
        "a 400 A North-American split-phase service is ~77 kW — the ceiling "
        "must cover the largest residential connection, not the common one"
    )
    assert 0 < PEAK_LIMIT_STEP_KW <= 0.1
    assert WARNING_PEAK_RATIO < 1.0 < EMERGENCY_PEAK_RATIO


def test_this_file_scans_real_sources():
    """Every regex above reads a file from disk; if one moved, the assertions
    would pass on an empty string."""
    for path in (_ROOT / "config_flow.py", _ROOT / "__init__.py",
                 _CARDS / "sem-config-card.js",
                 _CARDS / "sem-load-priority-card.js"):
        assert path.is_file() and path.stat().st_size > 1000, path
    # and derive_peak_levels is really the function the flow uses
    source = (_ROOT / "config_flow.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "derive_peak_levels" in names
