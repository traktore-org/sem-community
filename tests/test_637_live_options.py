"""#637 — config-card options: live routing completeness + classification guard."""
import re
import pathlib


REPO = pathlib.Path(__file__).resolve().parents[1]

# The deliberate classification (#637). A NEW card option must be added to
# exactly one of these sets — the guard test fails otherwise, so nobody can
# silently join the reload-per-tweak set again.
LM_LIVE = {"target_peak_limit", "warning_peak_level", "emergency_peak_level"}
LIVE_CONFIG = {"hot_water_minimum_temperature", "hot_water_legionella_target",
               "heat_pump_max_setpoint", "vpp_reserve_soc",
               "mobile_notification_service",
               # (#819) Construction-time by nature — the ForecastReader
               # takes it in __init__ — but the coordinator re-applies it
               # every cycle via set_preferred_source(), which is what
               # earns it a place here instead of in STRUCTURAL_RELOAD.
               # tests/test_819_forecast_source.py pins both halves.
               "solar_forecast_source",
               # (#829) Status-history retention. The coordinator reads it
               # fresh from config on every daily-rollover check, so a change
               # takes effect the next day without a reload. Backed by a
               # per-cycle read in coordinator.py, which the consumer test
               # below verifies.
               "status_retention_days"}
# Reload IS the correct behaviour: consumed at construction only (#462 —
# live-applying these would silently not reach the constructed consumer).
STRUCTURAL_RELOAD = {"tariff_mode", "tariff_classification_mode",
                     "battery_max_target_soc", "battery_pessimism_weight",
                     "battery_precharge_trigger_hour",
                     "battery_replan_interval_min",
                     "battery_roundtrip_efficiency"}


def _card_option_keys():
    src = (REPO / "dashboard/card/src/cards/sem-config-card.js").read_text()
    return set(re.findall(r"_renderOption(?:Slider|Switch|Select)\('([a-z_0-9]+)'", src))


def _entity_backed_keys():
    """Keys reachable via a number entity — directly or through the #542 map."""
    src = (REPO / "number.py").read_text()
    m = re.search(r"CONFIG_KEY_MAP\s*=\s*\{(.*?)\}", src, re.S)
    mapped = dict(re.findall(r'"([a-z_0-9]+)":\s*"([a-z_0-9]+)"', m.group(1)))
    # option key is the VALUE side of the map
    return set(mapped.values())


class TestClassificationGuard637:
    def test_every_card_key_is_classified(self):
        keys = _card_option_keys()
        assert keys, "card key extraction broke — fix the regex, not the guard"
        entity_backed = _entity_backed_keys()
        unclassified = []
        for k in keys:
            if (k in LM_LIVE or k in LIVE_CONFIG or k in STRUCTURAL_RELOAD
                    or k in entity_backed):
                continue
            # direct-named entity keys can't be verified without hass;
            # accept keys that ship a number/select/switch entity by key name
            # in the entity platforms' sources.
            plat = "".join((REPO / f).read_text() for f in
                           ("number.py", "select.py", "switch.py") if (REPO / f).exists())
            if f'"{k}"' in plat or f"'{k}'" in plat:
                continue
            unclassified.append(k)
        assert not unclassified, (
            f"card option(s) {unclassified} are not classified: add each to "
            "LM_LIVE / LIVE_CONFIG (+ set_option routing) / STRUCTURAL_RELOAD "
            "(deliberate), or back it with an entity — do not let it silently "
            "reload the coordinator per tweak (#637)")

    def test_live_config_keys_are_runtime_read(self):
        """Every LIVE_CONFIG key must have a per-cycle consumer reading
        coordinator config (the #636 lesson: verify the consumption site)."""
        runtime_src = "".join(
            p.read_text() for p in (REPO / "coordinator").glob("*.py"))
        for k in LIVE_CONFIG:
            assert re.search(rf'get\(\s*"{k}"', runtime_src), (
                f"{k} has no runtime config read — a live-apply would be "
                "the #462 silent no-op; route it structural instead")
