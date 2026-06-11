"""#485 H1: canonical fleet-primary charger id.

The strategy-display gate compared the per-charger loop's cid
(registration fallback ``ev_charger_<idx>``) against an inline primary
id with a DIFFERENT fallback (``"ev_charger"``) — on an id-less first
charger the equality never held and ``sem_charging_strategy`` froze.
``primary_charger_id()`` is the single accessor and mirrors
registration's fallback.
"""
import pytest
from unittest.mock import patch

from custom_components.solar_energy_management.coordinator import SEMCoordinator


def _coord(config):
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.config = config
    return coord


@pytest.mark.unit
class TestPrimaryChargerId:
    def test_explicit_id(self):
        coord = _coord({"ev_chargers": [{"id": "garage"}, {"id": "drive"}]})
        assert coord.primary_charger_id() == "garage"

    def test_idless_first_charger_matches_registration_fallback(self):
        # Registration assigns ev_charger_0 to an id-less index-0 entry;
        # the primary id must agree or the fleet-strategy gate never fires.
        coord = _coord({"ev_chargers": [{"name": "no id"}]})
        assert coord.primary_charger_id() == "ev_charger_0"

    def test_empty_string_id_uses_positional_fallback(self):
        coord = _coord({"ev_chargers": [{"id": ""}]})
        assert coord.primary_charger_id() == "ev_charger_0"

    def test_flat_key_shape_keeps_legacy_id(self):
        # No ev_chargers list (legacy single-charger flat keys) — the
        # auto-discovery reseed plants id "ev_charger".
        coord = _coord({})
        assert coord.primary_charger_id() == "ev_charger"

    def test_primary_cfg_returns_first_dict(self):
        coord = _coord({"ev_chargers": [{"id": "a", "x": 1}, {"id": "b"}]})
        assert coord._primary_charger_cfg() == {"id": "a", "x": 1}

    def test_primary_cfg_empty_when_no_chargers(self):
        coord = _coord({})
        assert coord._primary_charger_cfg() == {}
