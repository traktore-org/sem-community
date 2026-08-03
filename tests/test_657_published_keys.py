"""#657 — every ``coordinator.data`` key an entity reads must be published.

Eight entity attributes read keys that no production code ever wrote. The
producer computed the value and the consumer formatted it — ``peak_history_top5``
even had a pretty-printer — but the middle hop onto ``coordinator.data`` was
missing, so the attributes were permanently ``None``. Meta-class
*spec-vs-reality gap*, the sensor-attribute variant of #590.

The user-visible cost: ``sensor.sem_ev_charging_status`` exposes
``battery_too_low`` / ``battery_needs_priority`` / ``solar_sufficient`` — the
one surface designed to answer "why is my car not charging" — and all three
answered nothing.

The suite MASKED it: ``tests/conftest.py`` injects exactly these keys into the
mocked ``coordinator.data``, so tests saw attributes production never
published. Same harness-fidelity trap as the #610 lesson — which is why the
guard below reads the REAL producers, not a fixture.
"""
from __future__ import annotations

import ast
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.types import (
    LoadManagementData,
    PowerReadings,
    SEMData,
)

_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Consumers: every file that turns ``coordinator.data`` into entity state.
_CONSUMERS = ("sensor.py", "binary_sensor.py")

# Producers: ``SEMData.to_dict()`` (read at runtime, below) plus the modules
# that write further keys onto the cycle's result dict.
_PRODUCER_DIRS = ("coordinator", "features")

# The publisher locals those modules assign into. ``result`` is the cycle dict
# in ``_async_update_data``; ``out`` is ``publish_diag``'s; ``data`` is used by
# a few helpers. Restricted to these three names on purpose — accepting ANY
# subscript-assign would let an unrelated local dict (e.g.
# ``STORAGE_KEY``-style bookkeeping) vouch for a key it never publishes.
_PUBLISHER_LOCALS = {"result", "data", "out"}

# Publish payloads stashed on ``self`` and merged in later with
# ``result.update(self._x_publish)`` — e.g. ``self._vpp_publish = {...}`` on
# the VPP observer early-return. Their keys are real publications but appear
# as a plain attribute assignment, which neither rule below would see.
_PUBLISHER_ATTR_SUFFIX = "_publish"

# Keys built with an f-string prefix per charger / per device, which no static
# literal scan can see. Anything matching one of these is exempt.
_DYNAMIC_PREFIXES = ("charger_",)


def _string_keys_read_from_coordinator_data(path: pathlib.Path) -> set[str]:
    """Literal keys read off ``coordinator.data`` (directly or via an alias)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

    # ``d = self.coordinator.data`` then ``d.get("x")`` is the common shape.
    aliases = {
        t.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and isinstance(n.value, ast.Attribute)
        and n.value.attr == "data"
        for t in n.targets
        if isinstance(t, ast.Name)
    }

    def _is_data(node) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "data") or (
            isinstance(node, ast.Name) and node.id in aliases
        )

    keys: set[str] = set()
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get"
            and _is_data(n.func.value)
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and isinstance(n.args[0].value, str)
        ):
            keys.add(n.args[0].value)
        if (
            isinstance(n, ast.Subscript)
            and _is_data(n.value)
            and isinstance(n.slice, ast.Constant)
            and isinstance(n.slice.value, str)
        ):
            keys.add(n.slice.value)
    return keys


def _published_keys() -> set[str]:
    """Every key production can put on ``coordinator.data``."""
    # 1. The canonical dict.
    keys = set(SEMData().to_dict().keys())

    for directory in _PRODUCER_DIRS:
        for path in (_ROOT / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                # 2. ``result["x"] = ...`` on the cycle dict.
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if (
                            isinstance(t, ast.Subscript)
                            and isinstance(t.value, ast.Name)
                            and t.value.id in _PUBLISHER_LOCALS
                            and isinstance(t.slice, ast.Constant)
                            and isinstance(t.slice.value, str)
                        ):
                            keys.add(t.slice.value)
                        # 2b. ``self._vpp_publish = {"k": …}`` — a payload
                        #     merged into the cycle dict later.
                        elif (
                            isinstance(t, ast.Attribute)
                            and t.attr.endswith(_PUBLISHER_ATTR_SUFFIX)
                            and isinstance(n.value, ast.Dict)
                        ):
                            for k in n.value.keys:
                                if isinstance(k, ast.Constant) and isinstance(
                                    k.value, str
                                ):
                                    keys.add(k.value)
                # 3. Dict literals a helper RETURNS — these get merged in via
                #    ``result.update(...)`` (forecast-tracker + VPP blocks).
                if isinstance(n, ast.Return) and n.value is not None:
                    for d in ast.walk(n.value):
                        if isinstance(d, ast.Dict):
                            for k in d.keys:
                                if isinstance(k, ast.Constant) and isinstance(
                                    k.value, str
                                ):
                                    keys.add(k.value)
    return keys


@pytest.mark.unit
class TestPublishedKeyContract657:
    def test_every_attribute_key_has_a_producer(self):
        """The guard. Any attribute wired to a never-written key fails CI.

        This is deliberately a STATIC scan of the producers rather than a live
        cycle: a live cycle only publishes the branches its fixture happens to
        take, so a key written under `if self._load_manager:` would look
        missing on a smoke install and the guard would be noise.
        """
        read: set[str] = set()
        for name in _CONSUMERS:
            read |= _string_keys_read_from_coordinator_data(_ROOT / name)

        assert read, "key scan found nothing — the AST walk broke, not the code"

        published = _published_keys()
        missing = sorted(
            k
            for k in read - published
            if not k.startswith(_DYNAMIC_PREFIXES)
        )
        assert not missing, (
            "entity attributes read coordinator.data keys that no producer "
            f"writes (#657): {missing}. Either publish the value or drop the "
            "attribute — an attribute wired to a phantom key is worse than no "
            "attribute, because it reads as 'measured and null'."
        )


@pytest.mark.unit
class TestTheEightKeys657:
    """Pin the specific keys, so a future refactor that drops one of them
    fails with a name rather than only tripping the generic guard."""

    @pytest.mark.parametrize(
        "key",
        [
            "battery_too_low",
            "battery_needs_priority",
            "solar_sufficient",
            "excess_solar",
            "safe_discharge_power",
            "load_management_devices",
        ],
    )
    def test_key_is_in_the_canonical_dict(self, key):
        assert key in SEMData().to_dict()

    def test_home_consumption_key_is_the_published_one(self):
        """The available-power sensor read ``home_consumption_total``; the
        coordinator has always published ``home_consumption_power``."""
        d = SEMData().to_dict()
        assert "home_consumption_power" in d
        assert "home_consumption_total" not in d

    def test_peak_history_top5_is_gone(self):
        """No producer ever existed, so the attribute was deleted rather than
        invented. A real top-5 peak history means querying recorder
        statistics — a feature, not a bug fix."""
        source = (_ROOT / "sensor.py").read_text(encoding="utf-8")
        assert 'data.get("peak_history_top5"' not in source
        assert 'attrs["top_5_peaks"]' not in source

    def test_load_management_devices_round_trips(self):
        lm = LoadManagementData()
        lm.devices = {"boiler": {"friendly_name": "Boiler", "priority": 3}}
        assert SEMData(load_management=lm).to_dict()[
            "load_management_devices"
        ] == lm.devices

    def test_the_coordinator_copies_the_device_table_across(self):
        """The bug wasn't the dict — it was the copy. ``LoadManager`` returned
        ``devices`` all along and ``_build_load_management_data`` copied every
        OTHER field, so the table never reached ``coordinator.data``."""
        with patch.object(SEMCoordinator, "__init__", return_value=None):
            coord = SEMCoordinator.__new__(SEMCoordinator)
        coord.config = {}
        coord.hass = MagicMock()
        devices = {
            "boiler": {"friendly_name": "Boiler", "priority": 3,
                       "power_rating": 2000},
        }
        lm = MagicMock()
        lm.get_load_management_data = MagicMock(return_value={
            "target_peak_limit": 6.0,
            "state": "normal",
            "devices": devices,
        })
        coord._load_manager = lm

        lm_data = coord._build_load_management_data(PowerReadings())

        assert lm_data.devices == devices
        assert SEMData(load_management=lm_data).to_dict()[
            "load_management_devices"
        ] == devices

    def test_a_load_manager_without_a_device_table_publishes_an_empty_map(self):
        """Not every install has managed loads. The sensor's ``if devices:``
        guard means an empty map simply omits the attributes — it must not
        publish ``None`` and make the card iterate it."""
        with patch.object(SEMCoordinator, "__init__", return_value=None):
            coord = SEMCoordinator.__new__(SEMCoordinator)
        coord.config = {}
        coord.hass = MagicMock()
        lm = MagicMock()
        lm.get_load_management_data = MagicMock(return_value={"state": "normal"})
        coord._load_manager = lm

        assert coord._build_load_management_data(PowerReadings()).devices == {}

        # And the explicit-None shape, which is why the copy is written
        # ``.get("devices") or {}`` — the card iterates this map.
        lm.get_load_management_data = MagicMock(
            return_value={"state": "normal", "devices": None}
        )
        assert coord._build_load_management_data(PowerReadings()).devices == {}

    def test_flags_round_trip_from_the_charging_context_values(self):
        d = SEMData(
            battery_too_low=True,
            battery_needs_priority=True,
            solar_sufficient=False,
            excess_solar=-250.0,
            safe_discharge_power=1800.0,
        ).to_dict()
        assert d["battery_too_low"] is True
        assert d["battery_needs_priority"] is True
        assert d["solar_sufficient"] is False
        assert d["excess_solar"] == -250.0
        assert d["safe_discharge_power"] == 1800.0
