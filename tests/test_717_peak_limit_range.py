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

The fix makes the levels a RATIO of the target, derived at read time by
``_effective_levels()`` in ``features/load_management.py`` (see
``test_716_peak_limit_unlimited.py`` for that derivation pinned at the
5.0 kW default). #717 went further and removed the install-step field
entirely — the Control-tab slider is now the one live place to set it; see
the tests below for what that leaves in ``config_flow.py`` and the cards.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
import yaml
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solar_energy_management.config_flow import (
    OptionsFlowHandler,
)
from custom_components.solar_energy_management.const import (
    DEFAULT_EMERGENCY_PEAK_LEVEL,
    DEFAULT_PEAK_LIMIT_UNLIMITED,
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

    Every peak-limit number input in ``config_flow.py`` must be bounded by
    the shared constants. A literal here is how the install form ended up
    5 kW wider than the options form that edits the same key.

    #717 removed the install-step ``target_peak_limit`` field entirely (it
    duplicated the Control-tab slider and this options-flow field), so each
    of the three keys now has exactly one NumberSelector left — all in the
    options flow.
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
    assert seen == 3, f"expected exactly 3 peak selectors (one per key), found {seen}"


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


def test_the_service_yaml_selector_matches_the_shared_range():
    """``services.yaml`` cannot import ``MIN_PEAK_LIMIT_KW``/``MAX_PEAK_LIMIT_KW``
    — YAML has no notion of a Python constant — so its ``update_target_peak``
    selector is a hand-typed mirror of the same range every other surface in
    this file derives from a shared import. That is exactly the shape that
    already drifted once (#717): five different hard-coded ceilings across ten
    controls, nobody noticing because nothing compared them. This pins the one
    surface that structurally cannot use the import, so a future bump of the
    constants can't leave the Developer Tools → Actions picker still offering
    the old ceiling (found in review).
    """
    spec = yaml.safe_load((_ROOT / "services.yaml").read_text(encoding="utf-8"))
    selector = (
        spec["update_target_peak"]["fields"]["target_peak_limit"]["selector"]["number"]
    )
    assert selector["min"] == MIN_PEAK_LIMIT_KW
    assert selector["max"] == MAX_PEAK_LIMIT_KW


@pytest.mark.parametrize(
    "card,anchor,positive",
    [
        # The three config-card fields. Number inputs, not sliders: 791 stops
        # at 0.1 kW is not a control, it is a hazard.
        ("sem-config-card.js",
         r"'(?:target_peak_limit|warning_peak_level|emergency_peak_level)'",
         r"max:\s*80(?:\.0)?\b"),
        # The load-priority card's Control-tab slider (#717 redesign — the
        # old inline "Set" number box is gone, this is the one live editable
        # peak-limit control).
        ("sem-load-priority-card.js",
         r"range-handle-peak",
         r"MAX_KW\s*=\s*80\b"),
    ],
)
def test_no_card_hard_codes_the_old_ceiling(card, anchor, positive):
    """The cards are a separate copy of the same bound, and they are what most
    users actually touch — the load-priority card used to silently *discard*
    a value over 20 kW, so the user typed their real service size, pressed
    Set and nothing at all happened. #717 replaced that box with a slider
    that reaches 80 kW ("Unlimited") at the top."""
    source = (_CARDS / card).read_text(encoding="utf-8")
    assert re.search(anchor, source), f"{card}: anchor gone — retarget this scan"
    for stale in (r"max:\s*(?:15|20)(?:\.0)?\b", r'max="(?:15|20)"',
                  r"val\s*<=\s*20\b", r"Math\.min\(\s*(?:15|20)\s*,",
                  r"MAX_KW\s*=\s*(?:15|20)\b",
                  r'id="targetInput"', r'id="setTargetBtn"'):
        assert not re.search(stale, source), (
            f"{card} still carries the retired {stale!r} peak ceiling (#717)"
        )
    assert re.search(positive, source), (
        f"{card} does not carry the {MAX_PEAK_LIMIT_KW:g} kW ceiling (#717)"
    )


# ---------------------------------------------------------------------------
# The install flow no longer asks; the options flow validates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_install_no_longer_asks_for_the_peak_limit(mock_hass):
    """#717 dropped the install-step ``target_peak_limit`` field — it
    duplicated the live Control-tab slider and the options-flow field, three
    places to set one number. The install flow now always seeds the shared
    defaults for all four load-management keys, regardless of what the
    hardware step is submitted with — it has no way left to ask.
    """
    from custom_components.solar_energy_management.config_flow import (
        SolarEnergyManagementConfigFlow,
    )

    source = (_ROOT / "config_flow.py").read_text(encoding="utf-8")
    start = source.index("async def async_step_hardware(")
    end = source.index("async def async_step_reconfigure(", start)
    schema_block = source[start:end]
    assert '"target_peak_limit"' not in schema_block, (
        "the install-step schema still asks for target_peak_limit (#717)"
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
            "generate_dashboard_on_install": False,
        })

    assert result["type"] == FlowResultType.CREATE_ENTRY, result
    data = result["data"]
    assert data["target_peak_limit"] == DEFAULT_TARGET_PEAK_LIMIT
    assert data["peak_limit_unlimited"] == DEFAULT_PEAK_LIMIT_UNLIMITED
    assert data["warning_peak_level"] == DEFAULT_WARNING_PEAK_LEVEL
    assert data["emergency_peak_level"] == DEFAULT_EMERGENCY_PEAK_LEVEL
    assert data["warning_peak_level"] < data["target_peak_limit"] < data["emergency_peak_level"]


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


def test_the_install_help_no_longer_promises_a_removed_field():
    """#717 dropped the install-step ``target_peak_limit`` field. Its
    ``data``/``data_description`` entries must go with it — a stale entry is
    silently ignored by Home Assistant, but the install-step description
    text is prose a real user reads, so it must stop telling them to "Set
    your Peak Power Limit" on a step that no longer has that field.
    """
    files = [_ROOT / "strings.json", *sorted((_ROOT / "translations").glob("*.json"))]
    assert len(files) >= 17
    for path in files:
        hardware = json.loads(path.read_text(encoding="utf-8"))["config"]["step"]["hardware"]
        assert "target_peak_limit" not in hardware.get("data", {}), (
            f"{path.name}: orphaned data.target_peak_limit (#717)"
        )
        assert "target_peak_limit" not in hardware.get("data_description", {}), (
            f"{path.name}: orphaned data_description.target_peak_limit (#717)"
        )


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
    # and async_step_hardware is really still the method the scans above slice
    source = (_ROOT / "config_flow.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    assert "async_step_hardware" in names
    assert "async_step_reconfigure" in names
