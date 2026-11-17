"""A charging current exposed as a select (HA forum, ChargePoint Cloud).

SEM writes whole amps (7, 9, 11 A …). A select may offer only some steps
(8, 10, 12 … A) or carry a unit ("16 A"). SEM picks the largest offered
option at or below what it asked for — never more current than asked.
"""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.solar_energy_management.devices.base import CurrentControlDevice


def _dev(options):
    states = {"select.cp_amps": SimpleNamespace(attributes={"options": options})}
    return SimpleNamespace(hass=SimpleNamespace(states=SimpleNamespace(get=states.get)))


def _pick(options, amps):
    return CurrentControlDevice._select_amp_option(_dev(options), "select.cp_amps", amps)


def test_an_offered_step_is_written_as_is():
    assert _pick(["8", "10", "12", "16", "32"], 16) == "16"


def test_between_steps_the_lower_one_never_more_current():
    assert _pick(["8", "10", "12", "16", "32"], 9) == "8"
    assert _pick(["8", "10", "12", "16", "32"], 15) == "12"


def test_options_with_a_unit_keep_their_own_text():
    assert _pick(["6 A", "10 A", "16 A"], 11) == "10 A"


def test_below_every_option_or_unreadable_falls_back_to_the_plain_amps():
    assert _pick(["8", "10"], 6) == "6"
    assert _pick([], 9) == "9"
    assert _pick(None, 9) == "9"


def test_options_that_are_not_numbers_are_skipped():
    assert _pick(["Off", "8", "max"], 9) == "8"
