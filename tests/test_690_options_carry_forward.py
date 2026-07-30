"""#690 — a config-dialog save must not erase options it doesn't own.

The options flow finishes with ``async_create_entry(data=...)``, which
REPLACES ``entry.options`` wholesale. Every option written outside the
dialog — services (``grid_sign_user_flip``), dashboard entities
(``battery_mode``, ``battery_reserve_soc``, ``vacation_mode``, price
thresholds, …) — was silently wiped on any save ("Grid Sign Always
Changes Back").

Fix: the final save carries forward every stored option NOT in
``OPTIONS_FLOW_OWNED_KEYS``. Owned keys keep the replace semantics
(omitted from the submitted forms = cleared).

The guard test recomputes the owned set from the flow source, so adding
a form field without registering it in the set fails CI.
"""
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.config_flow import (
    OPTIONS_FLOW_OWNED_KEYS,
    OptionsFlowHandler,
)

COMPONENT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Guard: OPTIONS_FLOW_OWNED_KEYS must exactly match the flow source
# ---------------------------------------------------------------------------

def _owned_keys_from_source() -> set:
    """Recompute the owned set the same way it was derived: every static
    schema key and every direct ``self._data[...]`` write inside
    ``OptionsFlowHandler``."""
    src = (COMPONENT_ROOT / "config_flow.py").read_text()
    opt = src[src.index("class OptionsFlowHandler"):]
    keys = set(re.findall(
        r'vol\.(?:Optional|Required)\(\s*\n?\s*"([a-z0-9_]+)"', opt))
    keys |= set(re.findall(r'self\._data\[\s*"([a-z0-9_]+)"\s*\]', opt))
    keys |= set(re.findall(r'self\._data\.setdefault\(\s*"([a-z0-9_]+)"', opt))
    return keys


def test_owned_keys_match_the_flow_source():
    """A new options-flow form field MUST be added to
    OPTIONS_FLOW_OWNED_KEYS — otherwise its save semantics silently
    change (it would be carried forward even when the user clears it)."""
    from_source = _owned_keys_from_source()
    assert from_source == set(OPTIONS_FLOW_OWNED_KEYS), (
        "OPTIONS_FLOW_OWNED_KEYS is out of sync with the options-flow "
        f"schemas. Missing from set: {sorted(from_source - set(OPTIONS_FLOW_OWNED_KEYS))}; "
        f"stale in set: {sorted(set(OPTIONS_FLOW_OWNED_KEYS) - from_source)}"
    )


def test_service_and_entity_keys_are_not_owned():
    """The keys the bug erased must stay OUTSIDE the owned set — that is
    what makes them survive a save."""
    for key in (
        "grid_sign_user_flip",       # Fix-grid-sign button (#461/#690)
        "battery_sign_user_flip",    # #588 battery flip
        "battery_mode",              # select.sem_battery_mode
        "battery_modes",             # per-battery selects (#523)
        "battery_reserve_soc",
        "battery_reserve_socs",
        "vacation_mode",             # switch
        "cheap_price_threshold",
        "expensive_price_threshold",
        "night_earliest_start",
        "night_latest_end",
        "ev_enable_delay_seconds",
        "ev_disable_delay_seconds",
    ):
        assert key not in OPTIONS_FLOW_OWNED_KEYS, key


# ---------------------------------------------------------------------------
# Behaviour: the final save carries non-owned keys forward
# ---------------------------------------------------------------------------

def _flow(mock_hass, config_entry, options: dict, accumulated: dict):
    flow = OptionsFlowHandler(config_entry)
    flow.hass = mock_hass
    flow._data = dict(accumulated)
    config_entry.options = dict(options)
    return flow


@pytest.mark.asyncio
async def test_save_carries_forward_non_owned_options(mock_hass, config_entry):
    """The #690 repro: grid_sign_user_flip set by the button, then the
    user saves the config dialog — the flip must survive."""
    flow = _flow(
        mock_hass, config_entry,
        options={
            "grid_sign_user_flip": True,
            "battery_mode": "off",
            "vacation_mode": True,
            "update_interval": 30,          # owned — will be superseded
        },
        accumulated={"update_interval": 20},
    )
    with patch.object(type(flow), "config_entry", config_entry):
        result = await flow.async_step_notifications(
            {"enable_charger_notifications": True},
        )
    assert result["type"] == "create_entry"
    data = result["data"]
    # Non-owned keys carried forward untouched.
    assert data["grid_sign_user_flip"] is True
    assert data["battery_mode"] == "off"
    assert data["vacation_mode"] is True
    # Flow-accumulated values win over the old stored value.
    assert data["update_interval"] == 20
    assert data["enable_charger_notifications"] is True


@pytest.mark.asyncio
async def test_owned_keys_keep_replace_semantics(mock_hass, config_entry):
    """A flow-owned key absent from this run's accumulated data is
    DROPPED (a cleared optional field must stay cleared) — the carry-
    forward only applies to keys the dialog doesn't own."""
    flow = _flow(
        mock_hass, config_entry,
        options={"diagram_style": "kflow", "grid_sign_user_flip": True},
        accumulated={},
    )
    with patch.object(type(flow), "config_entry", config_entry):
        result = await flow.async_step_notifications(
            {"enable_charger_notifications": True},
        )
    data = result["data"]
    assert "diagram_style" not in data      # owned + omitted → cleared
    assert data["grid_sign_user_flip"] is True  # non-owned → carried


@pytest.mark.asyncio
async def test_empty_previous_options_still_saves(mock_hass, config_entry):
    """Fresh install (no stored options) — the save is just the
    accumulated data, no crash on the empty carry."""
    flow = _flow(mock_hass, config_entry, options={}, accumulated={"ev_min_current": 8})
    with patch.object(type(flow), "config_entry", config_entry):
        result = await flow.async_step_notifications(
            {"enable_charger_notifications": False},
        )
    assert result["data"]["ev_min_current"] == 8
