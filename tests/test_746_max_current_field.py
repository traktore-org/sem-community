"""A charger's ceiling must be settable, and setting it must reach the hardware.

#746. SEM has always had a per-charger **Min Amps** slider and no maximum. The
ceiling came from ``max_charging_current`` — a config key that no config flow
step and no entity ever wrote, minted only by the dashboard's *add charger*
skeleton as the literal ``32``. Every EVSE on every install was therefore
ceilinged at 32 A with no way to raise it; @Azlinon's 48 A box charged at two
thirds of its rating and nothing in the UI explained why.

#789 fixed the *arithmetic* half of that (thirteen open-coded defaults, six 32
and five 16, for a key nothing wrote). This is the other half: the field.

Two things have to be true, and the second is the one that historically fails.

1. The entity exists, persists to ``ev_max_current`` — the key the decision
   layer already reads — and spans a range a real EVSE can occupy.
2. Raising it actually raises the commanded current. ``build_view`` resolves the
   ceiling as ``min(hardware_max_a, cfg["ev_max_current"])`` and
   ``hardware_max_a`` is the device's ``max_current``, built at three separate
   construction sites. If those sites keep reading ``max_charging_current``, a
   user who drags the new slider to 48 gets flattened straight back to 32 by
   the ``min()`` — a live control that changes nothing, which is exactly the
   #542 silent-no-op class the knob-wiring lint exists to prevent.

So the three sites resolve through ONE function. That is deliberate: #789 is
**bug class 46** — a value with one source of truth restated as a literal at
the site that uses it — and a fix that leaves three sites free to drift would
re-open the class it was filed under.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.consts.core import (
    DEFAULT_MAX_CHARGING_CURRENT,
)

_ROOT = Path(__file__).resolve().parents[1]


# ── the entity ───────────────────────────────────────────────────────────

async def _per_charger_numbers(chargers, **top_level):
    """Run the real ``number.async_setup_entry`` and return its entities."""
    from custom_components.solar_energy_management.number import async_setup_entry

    entry = MagicMock()
    entry.entry_id = "entry_746"
    entry.data = {}
    entry.options = {"ev_chargers": chargers, **top_level}

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.config_entry = entry
    coordinator.hass.config.currency = "EUR"
    entry.runtime_data = coordinator

    added: list = []
    await async_setup_entry(MagicMock(), entry, lambda ents: added.extend(ents))
    return added


def _by_key(entities, key):
    for ent in entities:
        if getattr(ent.entity_description, "key", None) == key:
            return ent
    return None


@pytest.mark.unit
class TestTheCeilingIsSettable746:

    async def test_a_maximum_current_slider_exists_per_charger(self):
        ents = await _per_charger_numbers([{"id": "keba", "name": "KEBA P30"}])
        ent = _by_key(ents, "charger_keba_maximum_current")

        assert ent is not None, (
            "no per-charger maximum-current entity — the Min Amps slider has "
            "had no counterpart since #193 and every EVSE is stuck at the "
            "32 A default (#746)"
        )
        assert ent._config_key == "ev_max_current", (
            "the slider must persist to ``ev_max_current`` — that is the key "
            "build_view/charge_stability/ev_control already read. Writing a "
            "new key nobody reads is a dead stepper (#542)"
        )

    async def test_the_slider_spans_what_real_hardware_offers(self):
        ents = await _per_charger_numbers([{"id": "keba", "name": "KEBA P30"}])
        desc = _by_key(ents, "charger_keba_maximum_current").entity_description

        assert desc.native_min_value == 6, "6 A is the IEC 61851 handshake floor"
        assert desc.native_max_value >= 48, (
            "the reporter's EVSE is 48 A; a ceiling slider that cannot reach "
            "his hardware fixes nothing"
        )
        assert desc.native_max_value <= 80, (
            "80 A is the continuous ceiling for an EVSE on a 100 A feed — "
            "above that the slider is inviting a number no wallbox can honour"
        )

    async def test_it_seeds_from_the_legacy_ceiling(self):
        """An upgrade must not move anyone's ceiling.

        Installs predating #746 carry ``max_charging_current`` (32, or whatever
        the user hand-edited) and no ``ev_max_current``. The new entity has to
        appear already holding that number.
        """
        ents = await _per_charger_numbers(
            [{"id": "keba", "name": "KEBA P30", "max_charging_current": 20}]
        )
        ent = _by_key(ents, "charger_keba_maximum_current")
        assert ent.native_value == 20

    async def test_the_new_key_wins_over_the_legacy_one(self):
        ents = await _per_charger_numbers([{
            "id": "keba", "name": "KEBA P30",
            "max_charging_current": 32, "ev_max_current": 48,
        }])
        assert _by_key(ents, "charger_keba_maximum_current").native_value == 48

    async def test_a_fresh_charger_seeds_from_the_constant(self):
        ents = await _per_charger_numbers([{"id": "keba", "name": "KEBA P30"}])
        ent = _by_key(ents, "charger_keba_maximum_current")
        assert ent.native_value == DEFAULT_MAX_CHARGING_CURRENT

    async def test_two_chargers_get_their_own_ceiling(self):
        ents = await _per_charger_numbers([
            {"id": "keba", "name": "KEBA", "ev_max_current": 32},
            {"id": "wallbox", "name": "Wallbox", "ev_max_current": 48},
        ])
        assert _by_key(ents, "charger_keba_maximum_current").native_value == 32
        assert _by_key(ents, "charger_wallbox_maximum_current").native_value == 48


# ── the resolver ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestOneResolverForTheCeiling746:

    def test_the_new_key_is_preferred(self):
        from custom_components.solar_energy_management.devices.base import (
            resolve_max_current,
        )
        cfg = {"ev_max_current": 48, "max_charging_current": 32}
        assert resolve_max_current(cfg.get) == 48.0

    def test_the_legacy_key_still_answers(self):
        from custom_components.solar_energy_management.devices.base import (
            resolve_max_current,
        )
        assert resolve_max_current({"max_charging_current": 20}.get) == 20.0

    def test_an_unconfigured_charger_gets_the_constant(self):
        from custom_components.solar_energy_management.devices.base import (
            resolve_max_current,
        )
        assert resolve_max_current({}.get) == float(DEFAULT_MAX_CHARGING_CURRENT)

    def test_junk_does_not_ceiling_a_charger_at_zero(self):
        """A stored empty string must not become 0 A — that is a charger that
        can never start, from a config value nobody typed."""
        from custom_components.solar_energy_management.devices.base import (
            resolve_max_current,
        )
        for junk in ("", None, "abc", []):
            assert resolve_max_current({"ev_max_current": junk}.get) == float(
                DEFAULT_MAX_CHARGING_CURRENT
            )


# ── the wiring: raising it must reach the hardware ───────────────────────

@pytest.mark.unit
class TestTheRaisedCeilingReachesTheHardware746:

    def test_every_construction_site_resolves_through_the_one_function(self):
        """Bug class 46's guard, scoped to this key.

        Three places build a ``CurrentControlDevice``'s ``max_current``:
        setup, the late-discovery retry, and the refresh-in-place path. Any of
        them reading ``max_charging_current`` directly pins that device at the
        legacy value, and ``build_view``'s ``min(hardware_max_a, cfg_max)``
        then silently discards whatever the user set.
        """
        offenders = []
        for rel in ("__init__.py", "coordinator/coordinator.py"):
            src = (_ROOT / rel).read_text(encoding="utf-8")
            for lineno, line in enumerate(src.splitlines(), 1):
                if "max_charging_current" not in line:
                    continue
                if line.lstrip().startswith("#"):
                    continue  # prose about the legacy key is fine
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

        assert not offenders, (
            "these sites still read the legacy ceiling key directly instead of "
            "resolve_max_current() — a user who raises the new Max Amps "
            "slider is flattened back to the legacy value by build_view's "
            "min() and sees nothing change (#746, bug class 46):\n"
            + "\n".join(f"  {o}" for o in offenders)
        )

    def test_the_resolver_is_the_only_place_the_legacy_key_survives(self):
        """Bug class 8 — prove the scan above could actually fail."""
        src = (_ROOT / "devices" / "base.py").read_text(encoding="utf-8")
        assert '"max_charging_current"' in src, (
            "the legacy key has to be read SOMEWHERE or pre-#746 installs "
            "lose their configured ceiling on upgrade"
        )

    def _view(self, charger_cfg, hardware_max_a):
        from custom_components.solar_energy_management.coordinator.build_view import (
            build_charger_view,
        )
        from custom_components.solar_energy_management.coordinator.charger_types import (
            FleetCycleState,
        )
        power = MagicMock()
        power.solar_power = 20000.0
        power.home_consumption_power = 500.0
        power.battery_soc = 50.0
        power.ev_power_per_charger = {}
        power.ev_connected_per_charger = {}
        power.ev_charging_per_charger = {}
        return build_charger_view(
            FleetCycleState(
                power=power, config={}, is_night=False,
                tariff_level=None, forecast_remaining_kwh=0.0,
            ),
            charger_id="keba", charger_cfg=charger_cfg,
            mode="solar_only", daily_ev_kwh=0.0,
            hardware_max_a=hardware_max_a,
        )

    def test_a_raised_ceiling_survives_build_view(self):
        """The end of the chain: 48 A configured, 48 A hardware → 48 A decided."""
        view = self._view({"id": "keba", "ev_max_current": 48}, hardware_max_a=48.0)
        assert view.config["ev_max_current"] == 48, (
            "the configured ceiling was flattened on the way to the decision"
        )

    def test_the_ceiling_still_cannot_exceed_the_hardware(self):
        """Raising the slider above what the box can do stays a no-op — the
        adapter clamps anyway, and deciding above the clamp is the drift #627
        closed."""
        view = self._view({"id": "keba", "ev_max_current": 80}, hardware_max_a=32.0)
        assert view.config["ev_max_current"] == 32
