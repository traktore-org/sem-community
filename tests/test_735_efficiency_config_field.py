"""#735 (enhancement half) — ``ev_charger_efficiency`` gets a dialog field.

The fix half (v1.7.6-beta.6) validated the key. It stayed reachable only by
hand-editing ``.storage/core.config_entries``, which is why it needed
validating in the first place. This half puts it on the EV charger options
step so a user with a 1-phase 3.7 kW charger — or a car that preconditions
while it charges — can calibrate the SOC estimate instead of living with a
92 % assumption that is wrong for their install.

**The whole risk of this change is a unit.** The detector's band is 0.5–1.0;
a form that reads "92" to a human has to write 0.92 to storage. Get that
wrong in either direction and the failure is silent:

  * form writes 85 → detector rejects it as out-of-band → falls back to 0.92
    and the user's setting does nothing, forever, with no error anywhere;
  * form displays 0.85 as "0.85 %" → user "corrects" it to 85 → same thing.

That is #708's shape exactly: two halves of one calculation, each defensible
alone, disagreeing about what the number means. So the load-bearing tests
here are not "does the field exist" — they are the ones that carry a value
across the boundary and assert on the *far* side (``TestTheFormAndTheDetector
AgreeOnUnits``). A test that only inspects the flow's own dict would pass
under either convention.

Storage keeps the fraction. The alternative — store percent, teach the
detector to accept both — reopens the ambiguity permanently (is 0.92 a
fraction or 0.92 %?) and would have to unpin the shipped guard that rejects
``92`` as the classic percentage mistake. One canonical unit, converted at
the UI edge, is the whole point of the issue.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.config_flow import (
    OPTIONS_FLOW_OWNED_KEYS,
    OptionsFlowHandler,
)
from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    CHARGE_EFFICIENCY,
    CHARGE_EFFICIENCY_MAX,
    CHARGE_EFFICIENCY_MIN,
    EVTaperDetector,
)

KEY = "ev_charger_efficiency"
DEFAULT_PCT = 92
CALIBRATED_PCT = 85          # a plausible 1-phase / cold-pack install
CALIBRATED_FRACTION = 0.85

_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _flow(mock_hass, config_entry, options: dict | None = None):
    flow = OptionsFlowHandler(config_entry)
    flow.hass = mock_hass
    flow._data = {}
    config_entry.options = dict(options or {})
    return flow


async def _form(mock_hass, config_entry, options: dict | None = None):
    """Render the EV charger step and hand back its schema."""
    flow = _flow(mock_hass, config_entry, options)
    with patch.object(type(flow), "config_entry", config_entry):
        result = await flow.async_step_ev_charger(user_input=None)
    assert result["step_id"] == "ev_charger"
    return result["data_schema"].schema


def _marker(schema, key: str):
    for marker in schema:
        if str(marker) == key:
            return marker
    raise AssertionError(
        f"{key!r} is not in the ev_charger options schema. Present: "
        f"{sorted(str(m) for m in schema)}"
    )


def _default(schema, key: str):
    marker = _marker(schema, key)
    default = marker.default
    return default() if callable(default) else default


def _selector_config(schema, key: str) -> dict:
    return dict(schema[_marker(schema, key)].config)


async def _submit(mock_hass, config_entry, percent, options: dict | None = None):
    """Submit the step with the field set, return the flow's accumulated data."""
    flow = _flow(mock_hass, config_entry, options)
    with patch.object(type(flow), "config_entry", config_entry):
        await flow.async_step_ev_charger(user_input={KEY: percent})
    return flow._data


# ---------------------------------------------------------------------------


class TestTheFieldExistsAndIsAPercentage:
    @pytest.mark.asyncio
    async def test_the_ev_charger_step_offers_the_field(self, mock_hass, config_entry):
        schema = await _form(mock_hass, config_entry)
        _marker(schema, KEY)     # raises with the full key list if absent

    @pytest.mark.asyncio
    async def test_the_band_is_the_detectors_band_in_percent(self, mock_hass, config_entry):
        """50–100 %, mirroring the 0.5–1.0 the detector will accept.

        Offering a value the detector then rejects is worse than not
        offering it: the dialog saves, shows no error, and silently keeps
        using 92 %.
        """
        config = _selector_config(await _form(mock_hass, config_entry), KEY)
        assert config["min"] == round(CHARGE_EFFICIENCY_MIN * 100)
        assert config["max"] == round(CHARGE_EFFICIENCY_MAX * 100)
        assert config["unit_of_measurement"] == "%"
        # Derived, not copied: move the band in the detector and the box moves
        # with it, instead of quietly offering values the booking discards.
        assert (config["min"], config["max"]) == (50, 100)

    @pytest.mark.asyncio
    async def test_an_unset_key_shows_the_shipped_default(self, mock_hass, config_entry):
        schema = await _form(mock_hass, config_entry)
        assert _default(schema, KEY) == DEFAULT_PCT


class TestTheFormAndTheDetectorAgreeOnUnits:
    """The load-bearing half. Assertions land on the detector, not the dict."""

    @pytest.mark.asyncio
    async def test_what_the_form_writes_is_what_the_detector_reads(
        self, mock_hass, config_entry
    ):
        """85 % in the dialog must mean 0.85 to the thing doing the booking.

        Discriminating by construction: if the flow stored the raw 85, the
        detector's band check rejects it and this reads back 0.92.
        """
        data = await _submit(mock_hass, config_entry, CALIBRATED_PCT)
        detector = EVTaperDetector({"ev_battery_capacity_kwh": 40, **data})
        assert detector._charge_efficiency() == pytest.approx(CALIBRATED_FRACTION)

    @pytest.mark.asyncio
    async def test_the_stored_value_is_the_fraction(self, mock_hass, config_entry):
        data = await _submit(mock_hass, config_entry, CALIBRATED_PCT)
        assert data[KEY] == pytest.approx(CALIBRATED_FRACTION)

    @pytest.mark.asyncio
    async def test_the_primary_charger_entry_gets_the_same_fraction(
        self, mock_hass, config_entry
    ):
        """The step mirrors every field into ``ev_chargers[0]`` (#112).

        Two copies of one value is how a unit mismatch survives a review —
        pin that they are written from the same converted number.
        """
        data = await _submit(mock_hass, config_entry, CALIBRATED_PCT)
        assert data["ev_chargers"][0][KEY] == pytest.approx(CALIBRATED_FRACTION)

    @pytest.mark.asyncio
    async def test_a_stored_fraction_comes_back_as_a_percentage(
        self, mock_hass, config_entry
    ):
        schema = await _form(mock_hass, config_entry, {KEY: CALIBRATED_FRACTION})
        assert _default(schema, KEY) == CALIBRATED_PCT

    @pytest.mark.asyncio
    async def test_the_round_trip_is_stable(self, mock_hass, config_entry):
        """Open → save → open must not walk the value.

        A conversion pair that is off by a rounding step turns "the user
        opened the dialog and pressed Submit" into a slow drift.
        """
        for pct in (50, 78, 85, 92, 100):
            data = await _submit(mock_hass, config_entry, pct)
            schema = await _form(mock_hass, config_entry, {KEY: data[KEY]})
            assert _default(schema, KEY) == pct


class TestACorruptStoredValueCannotReachTheForm:
    """The key predates the field — a hand-edited value may already be there.

    Rendering it raw would show "300 %" in a 50–100 box (which HA refuses to
    submit, wedging the whole dialog) or "92 %" for a stored ``92`` that the
    detector is actually ignoring. Show what is in force, not what is stored.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stored", [
        3.0,        # the fraction/percent confusion, stored the other way up
        92,         # the classic percentage mistake — rejected by the detector
        0.001,      # looks set, goes nowhere
        True,       # hand-edited JSON `true` → float(True) == a valid-looking 1.0
        "abc", None, -0.5,
    ])
    async def test_a_rejected_value_displays_as_the_default(
        self, mock_hass, config_entry, stored
    ):
        schema = await _form(mock_hass, config_entry, {KEY: stored})
        assert _default(schema, KEY) == DEFAULT_PCT

    @pytest.mark.asyncio
    async def test_a_hand_edited_valid_fraction_is_kept(self, mock_hass, config_entry):
        """The flip side — don't "sanitise" a value that was always fine."""
        schema = await _form(mock_hass, config_entry, {KEY: 0.78})
        assert _default(schema, KEY) == 78


class TestTheKeyIsRegisteredWhereItHasToBe:
    def test_the_options_flow_owns_the_key(self):
        """#690: a form field absent from the owned set is carried forward
        instead of replaced, so clearing it in the dialog does nothing."""
        assert KEY in OPTIONS_FLOW_OWNED_KEYS

    @pytest.mark.parametrize("path", sorted(
        [_ROOT / "strings.json"] + list((_ROOT / "translations").glob("*.json"))
    ), ids=lambda p: p.name)
    def test_the_field_is_labelled(self, path):
        """#674: ``strings.json`` and all 16 languages are a hand-maintained
        mirror. A missing label never raises — the field just renders as the
        raw key ``ev_charger_efficiency`` next to a percent box, in every
        language at once.
        """
        step = json.loads(path.read_text())["options"]["step"]["ev_charger"]
        assert KEY in step["data"], f"{path.name}: no label"
        assert KEY in step["data_description"], f"{path.name}: no description"

    def test_the_label_guard_would_catch_a_bare_key(self):
        """Bug class 8 — prove the rule can fire.

        Every key on this step is labelled today, so the parametrised test
        above is a real constraint rather than a vacuous one.

        NOTE: this step only. An audit while writing this found six other
        options steps shipping unlabelled fields (``ev_charger_add``,
        ``ev_charger_edit``, ``settings``, ``settings_phase_guard``,
        ``settings_tariff``, ``battery_scheduler``, ``deye``) — out of scope
        for #735, worth its own issue rather than an allow-list here.
        """
        src = (_ROOT / "config_flow.py").read_text()
        opt = src[src.index("class OptionsFlowHandler"):]
        body = opt[
            opt.index("async def async_step_ev_charger("):
            opt.index("async def async_step_ev_charger_menu(")
        ]
        keys = set(re.findall(
            r'vol\.(?:Optional|Required)\(\s*\n?\s*"([a-z0-9_]+)"', body))
        assert len(keys) > 10, f"the schema scan broke — found {sorted(keys)}"
        assert KEY in keys

        step = json.loads((_ROOT / "strings.json").read_text(
        ))["options"]["step"]["ev_charger"]
        assert not keys - set(step["data"])
        assert not keys - set(step["data_description"])


class TestTheResolverIsShared:
    """Both sides of the boundary validate with the same function.

    The flow needs the band to decide what to display; the detector needs it
    to decide what to honour. Two copies of "0.5 ≤ x ≤ 1.0, reject bools"
    would drift — which is the sentence #735 was filed to stop writing.
    """

    def test_the_flow_imports_the_detectors_resolver(self):
        from custom_components.solar_energy_management import config_flow
        from custom_components.solar_energy_management.coordinator import (
            ev_taper_detector,
        )

        assert (
            config_flow.resolve_charge_efficiency
            is ev_taper_detector.resolve_charge_efficiency
        )

    def test_the_detectors_accessor_delegates_to_it(self):
        """No second band check inside the method."""
        src = (_ROOT / "coordinator" / "ev_taper_detector.py").read_text()
        body = src[src.index("    def _charge_efficiency("):]
        body = body[:body.index("\n    def ", 10)]
        assert "resolve_charge_efficiency" in body
        assert "0.5" not in body, (
            "the band moved back into the accessor — it belongs in the "
            "resolver the config flow also calls"
        )

    def test_the_resolver_agrees_with_the_accessor(self):
        from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
            resolve_charge_efficiency,
        )

        for raw in (0.5, 0.78, 1.0, "0.88", 3.0, 92, True, None, "abc"):
            detector = EVTaperDetector({"ev_battery_capacity_kwh": 40, KEY: raw})
            assert detector._charge_efficiency() == resolve_charge_efficiency(raw)
        assert resolve_charge_efficiency(None) == CHARGE_EFFICIENCY
