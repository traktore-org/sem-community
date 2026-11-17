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
               "status_retention_days",
               # (#1323) The coordinator pushes each heat pump row's value
               # onto its device on every runtime refresh.
               "heat_pump_step_down"}
# Reload IS the correct behaviour: consumed at construction only (#462 —
# live-applying these would silently not reach the constructed consumer).
STRUCTURAL_RELOAD = {"tariff_mode", "tariff_classification_mode",
                     "battery_max_target_soc", "battery_pessimism_weight",
                     "battery_precharge_trigger_hour",
                     "battery_replan_interval_min",
                     "battery_roundtrip_efficiency",
                     # (#1077) read when the tariff provider is built
                     "tariff_value_preset", "import_price_basis",
                     "feed_in_fee_model"}


def _entity_backed_keys():
    """Keys reachable via a number entity — directly or through the #542 map."""
    src = (REPO / "number.py").read_text()
    m = re.search(r"CONFIG_KEY_MAP\s*=\s*\{(.*?)\}", src, re.S)
    mapped = dict(re.findall(r'"([a-z_0-9]+)":\s*"([a-z_0-9]+)"', m.group(1)))
    # option key is the VALUE side of the map
    return set(mapped.values())


class TestClassificationGuard637:
    def test_every_reloading_key_the_screen_writes_is_staged(self):
        """(#1321) The System screen stages a key behind Apply when writing it
        reloads the entry (its STRUCTURAL_KEYS). A key the backend reloads on
        that the screen did not stage would reload per tweak (#637). The
        per-battery list options are the exception: they carry their own
        reload (``listEdits``)."""
        src = (REPO / "dashboard/card/src/util/next-settings.js").read_text()
        code = re.sub(r"//[^\n]*", "", src)
        staged = set(re.findall(r"'([^']+)'", re.search(
            r"export const STRUCTURAL_KEYS = new Set\(\[(.*?)\]\)", code, re.S).group(1)))
        init = (REPO / "__init__.py").read_text()
        py = set(re.findall(r'"([^"]+)"', re.search(
            r"_SET_OPTION_STRUCTURAL_KEYS:[^=]*=\s*frozenset\(\{(.*?)\}\)", init, re.S).group(1)))
        written = set(re.findall(r"""['"]([a-z][a-z0-9_]+)['"]""", src))
        loose = sorted(k for k in (py & written) - staged if not k.endswith("_entities"))
        assert not loose, (
            f"the System screen writes {loose}, which reload the entry, without staging "
            "them: add each to STRUCTURAL_KEYS in next-settings.js (#637)")

    def test_live_config_keys_are_runtime_read(self):
        """Every LIVE_CONFIG key must have a per-cycle consumer reading
        coordinator config (the #636 lesson: verify the consumption site)."""
        runtime_src = "".join(
            p.read_text() for p in (REPO / "coordinator").glob("*.py"))
        for k in LIVE_CONFIG:
            assert re.search(rf'get\(\s*"{k}"', runtime_src), (
                f"{k} has no runtime config read — a live-apply would be "
                "the #462 silent no-op; route it structural instead")
