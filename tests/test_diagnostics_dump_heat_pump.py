"""Tests for the #432 ``heat_pump`` block in the diagnostics dump.

When the user clicks Settings → SEM → ⋮ → Download Diagnostics, the
resulting JSON must include a ``heat_pump`` block with config + live
state. That's the one-click payload @RienduPre can paste on the
discussion so the maintainer can read it without owning the hardware.

Running the full ``async_get_config_entry_diagnostics`` end-to-end
requires a real HomeAssistant instance + entry registry — overkill for
a structural assertion. We AST-walk the module and confirm:

  1. The diagnostics dump dict literal contains a ``"heat_pump"`` key.
  2. Inside ``heat_pump`` the load-bearing keys are present:
     ``registered``, ``registration_status``, ``mode``,
     ``sg_ready_state``, plus nested ``config.relay1_entity``,
     ``config.relay2_entity``, ``config.climate_entity``, and
     ``live.relay1_state``, ``live.relay2_state``, ``live.climate_state``.

If any of these is missing the diagnostic loop with RienduPre breaks
silently — we'd ask him for the dump, he'd paste it, and we'd be
missing the data we need.
"""
import ast
import pathlib


_DIAGNOSTICS_PATH = (
    pathlib.Path(__file__).parent.parent / "diagnostics.py"
)
_REQUIRED_HP_KEYS = {
    "registered",
    "registration_status",
    "mode",
    "sg_ready_state",
    "solar_boost",
    "config",
    "live",
}
_REQUIRED_HP_CONFIG_KEYS = {
    "relay1_entity",
    "relay2_entity",
    "climate_entity",
}
_REQUIRED_HP_LIVE_KEYS = {
    "relay1_state",
    "relay2_state",
    "climate_state",
}


def _find_heat_pump_dict(tree: ast.AST) -> ast.Dict | None:
    """AST-walk and find the dict literal assigned to the ``heat_pump``
    key inside the diagnostics return value."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == "heat_pump"
                    and isinstance(v, ast.Dict)
                ):
                    return v
    return None


def _string_keys(d: ast.Dict) -> set[str]:
    """Return the set of string keys in a dict-literal AST node."""
    return {
        k.value for k in d.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }


def _nested_dict(d: ast.Dict, key: str) -> ast.Dict | None:
    """Return the dict-literal value at ``d[key]`` (or None if not a dict)."""
    for k, v in zip(d.keys, d.values):
        if isinstance(k, ast.Constant) and k.value == key and isinstance(v, ast.Dict):
            return v
    return None


def test_diagnostics_dump_includes_heat_pump_block():
    """The top-level dump must include a ``heat_pump`` key."""
    assert _DIAGNOSTICS_PATH.exists(), f"diagnostics.py not at {_DIAGNOSTICS_PATH}"
    tree = ast.parse(_DIAGNOSTICS_PATH.read_text())
    hp = _find_heat_pump_dict(tree)
    assert hp is not None, (
        "diagnostics.py does not emit a 'heat_pump' key in any dict "
        "literal. RienduPre's 'Copy diagnostics' workflow needs this "
        "block to debug heat-pump registration remotely (#432)."
    )


def test_heat_pump_block_has_required_top_level_keys():
    """The ``heat_pump`` block must expose registered/status/mode/state."""
    tree = ast.parse(_DIAGNOSTICS_PATH.read_text())
    hp = _find_heat_pump_dict(tree)
    keys = _string_keys(hp)
    missing = _REQUIRED_HP_KEYS - keys
    assert not missing, (
        f"#432: heat_pump diagnostics block is missing required keys: "
        f"{sorted(missing)}. Required: {sorted(_REQUIRED_HP_KEYS)}. "
        f"Found: {sorted(keys)}."
    )


def test_heat_pump_config_subblock_has_entity_keys():
    """The nested ``config`` subblock must expose the three configured
    entity ids so the maintainer can compare them to what the user
    actually set."""
    tree = ast.parse(_DIAGNOSTICS_PATH.read_text())
    hp = _find_heat_pump_dict(tree)
    config = _nested_dict(hp, "config")
    assert config is not None, "heat_pump.config must be a dict literal"
    keys = _string_keys(config)
    missing = _REQUIRED_HP_CONFIG_KEYS - keys
    assert not missing, (
        f"#432: heat_pump.config block is missing entity keys: "
        f"{sorted(missing)}."
    )


def test_heat_pump_live_subblock_has_state_keys():
    """The nested ``live`` subblock must expose the live HA state of
    each configured entity — that's the diagnostic signal pre-#432
    nothing exposed."""
    tree = ast.parse(_DIAGNOSTICS_PATH.read_text())
    hp = _find_heat_pump_dict(tree)
    live = _nested_dict(hp, "live")
    assert live is not None, "heat_pump.live must be a dict literal"
    keys = _string_keys(live)
    missing = _REQUIRED_HP_LIVE_KEYS - keys
    assert not missing, (
        f"#432: heat_pump.live block is missing state keys: "
        f"{sorted(missing)}."
    )


def test_coordinator_data_dict_includes_diagnostic_fields():
    """The dump reads from ``coordinator.data.get(...)`` — verify the
    coordinator emits the fields the dump expects. Walk types.py and
    confirm each ``heat_pump_*_state`` / ``heat_pump_*_entity`` /
    ``heat_pump_registration_status`` is published in the data dict."""
    types_path = pathlib.Path(__file__).parent.parent / "coordinator" / "types.py"
    source = types_path.read_text()
    for field in (
        "heat_pump_registration_status",
        "heat_pump_relay1_entity",
        "heat_pump_relay2_entity",
        "heat_pump_climate_entity",
        "heat_pump_relay1_state",
        "heat_pump_relay2_state",
        "heat_pump_climate_state",
    ):
        assert f'"{field}"' in source, (
            f"#432: coordinator/types.py must emit {field!r} into the "
            "coordinator.data dict so diagnostics.py can read it via "
            "data.get(...)."
        )
