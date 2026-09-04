"""#915 — the oracle: does the miner re-find what SEM learned by hand?

Everything in `consts/integration_roster.py` is derived from public sources
with no human in the loop, which is exactly why it needs an independent check
before anything is allowed to act on it. The check is this: SEM knows a
handful of brand facts that cost real effort to learn — a reporter's live
install, a debugging session, a shipped bug. If the miner cannot re-derive
those from each integration's own repository, it has no business proposing
anything for a brand nobody has run.

Four facts, from four different origins:

* `storage_maximum_discharging_power` — hardcoded in
  `config_flow._SPEC_REGISTRY_KEYS`, harvested from a German Huawei install.
* the three Huawei working-mode labels in `_suggest_select_with_options` —
  #845, learned from a live install because the entity id was localised.
* Zaptec's charging-current register — #804's phase-switching work, where
  `three_to_one_phase_switch_current` had to be told apart from the real
  current control.
* Sessy's `api / eco / nom / idle` strategy values — #523, learned when the
  battery sat idle at 20 % SOC because SEM left it in the wrong mode.

And one absence, which is information of the same kind: Easee exposes no
current-control number at all (it is service-driven), so the miner must
report nothing rather than invent one.

These assertions run offline against the COMMITTED roster. When one fails
after a refresh, upstream renamed something — which is a finding, not a test
bug: see the drift allowlist at the bottom.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


roster = _load("integration_roster", "consts/integration_roster.py")


def _keys(domain: str, role: str) -> tuple:
    return tuple(roster.ROLE_VOCAB.get(domain, {}).get(role, {}).get("keys", ()))


def _options(domain: str, role: str) -> set:
    return set(roster.ROLE_VOCAB.get(domain, {}).get(role, {}).get("options", ()))


@pytest.mark.unit
class TestItRediscoversWhatWeLearnedByHand:
    def test_huawei_discharge_limit_key(self):
        """`_SPEC_REGISTRY_KEYS` carries this because someone's real inverter
        had it. The miner reads it off the integration's own strings.json."""
        assert "storage_maximum_discharging_power" in _keys(
            "huawei_solar", "battery_discharge_limit")

    def test_huawei_working_mode_options_match_the_845_vocabulary(self):
        """#845 hardcodes these three labels to identify the working-mode
        select whatever the entity is called. All three must be mined."""
        want = {"maximise_self_consumption", "fully_fed_to_grid",
                "time_of_use_luna2000"}
        assert want <= _options("huawei_solar", "battery_strategy")

    def test_zaptec_current_control_without_the_phase_register(self):
        """#804: the phase-switch register is also a current, and writing a
        charging setpoint into it would switch phases instead. The miner must
        pick the control and leave the trap alone."""
        keys = _keys("zaptec", "ev_current_control")
        assert "charger_max_current" in keys or "available_current" in keys
        assert "three_to_one_phase_switch_current" not in keys
        assert "charger_min_current" not in keys

    def test_sessy_strategy_options_cover_the_generic_adapter_defaults(self):
        """#523: the generic battery adapter's `api` / `eco` / `nom` / `idle`
        values were learned from a live Sessy."""
        assert {"api", "eco", "nom", "idle"} <= _options("sessy",
                                                         "battery_strategy")

    def test_easee_exposes_no_current_control_and_none_is_invented(self):
        """Easee is service-driven. Absence is information: a miner that
        produced a plausible-looking number here would be the failure mode
        this whole arc is designed to avoid."""
        assert "easee" in roster.ROSTER
        assert "ev_current_control" not in roster.ROLE_VOCAB.get("easee", {})


@pytest.mark.unit
class TestItFindsBrandsNobodyHasRun:
    """The point of the exercise: hardware SEM has never seen, with concrete
    role candidates, before any user asks."""

    @pytest.mark.parametrize("domain,role", [
        ("eg4_web_monitor", "battery_target_soc"),   # #810, reporter waiting on PTO
        ("sigen", "battery_discharge_limit"),        # 2.2k installs, never reported
        ("anker_solix", "battery_charge_limit"),     # #869, modbus install had no row
    ])
    def test_a_brand_with_no_matrix_row_still_has_candidates(self, domain, role):
        assert role in roster.ROLE_VOCAB.get(domain, {}), domain

    def test_the_roster_reaches_beyond_what_sem_supports(self):
        """A roster that only knew what the matrix knows would be a mirror,
        not a discovery."""
        matrix = _load("hardware_matrix", "consts/hardware_matrix.py")
        brands = " ".join(str(r.get("brand", "")) for r in matrix.ALL_ROWS).lower()
        unknown = [d for d in roster.ROLE_VOCAB
                   if d.split("_")[0] not in brands]
        assert len(unknown) >= 5, unknown


#: Upstream renamed a key SEM hardcodes. Each entry is a REVIEWED finding, not
#: a silencer: the note says what moved. Shrink-only — when SEM's own key list
#: catches up, the entry goes.
_KEY_DRIFT_ALLOWLIST: dict = {
    # `_SPEC_REGISTRY_KEYS` lists "usable_capacity" / "rated_capacity" /
    # "battery_capacity" / "max_discharge_power" / "max_discharging_power" /
    # "nominal_power" as generic fallbacks harvested from installs rather than
    # from any one integration's published vocabulary. They are kept because a
    # live install had them; the miner cannot confirm them from upstream.
    "usable_capacity": "generic fallback, not published by a mined integration",
    "rated_capacity": "generic fallback",
    "battery_capacity": "generic fallback",
    "max_discharging_power": "generic fallback",
    "nominal_power": "generic fallback",
}


@pytest.mark.unit
class TestTheHardcodedKeysAreStillReal:
    def test_every_spec_key_is_mined_or_a_reviewed_fallback(self):
        """SEM hardcodes entity keys in `config_flow._SPEC_REGISTRY_KEYS`.
        Each one should be findable in some integration's published
        vocabulary — and when it is not, that is either a generic fallback or
        an upstream rename SEM has not noticed. Huawei renaming
        `storage_rated_capacity` to `rated_ess_capacity` is exactly the second
        case, which is why mined keys are ADDITIVE aliases and never
        replacements."""
        src = (ROOT / "config_flow.py").read_text()
        block = re.search(r"_SPEC_REGISTRY_KEYS[^=]*=\s*\{(.*?)\n\}", src, re.S)
        assert block, "the spec key table moved"
        hardcoded = set(re.findall(r'"([a-z0-9_]{4,})"', block.group(1)))
        hardcoded -= {"battery_capacity_kwh", "system_size_kwp",
                      "battery_max_discharge_power"}   # the spec names
        mined = {k for roles in roster.ROLE_VOCAB.values()
                 for body in roles.values() for k in body["keys"]}
        missing = sorted(hardcoded - mined - set(_KEY_DRIFT_ALLOWLIST))
        assert not missing, (
            f"{missing} is hardcoded in _SPEC_REGISTRY_KEYS but no mined "
            "integration publishes it — either upstream renamed it (add it to "
            "_KEY_DRIFT_ALLOWLIST with the note) or SEM invented it"
        )

    def test_the_allowlist_only_shrinks(self):
        mined = {k for roles in roster.ROLE_VOCAB.values()
                 for body in roles.values() for k in body["keys"]}
        stale = sorted(set(_KEY_DRIFT_ALLOWLIST) & mined)
        assert not stale, (
            f"{stale} is now published upstream — remove it from "
            "_KEY_DRIFT_ALLOWLIST; the allowlist may only shrink"
        )

    def test_the_upstream_rename_is_visible(self):
        """The finding this test class exists to surface: Huawei publishes a
        capacity key SEM does not know about."""
        assert "rated_ess_capacity" in _keys("huawei_solar",
                                             "battery_capacity_spec")
