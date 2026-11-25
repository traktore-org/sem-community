"""(#1428) Removing a charger leaves none of its entities behind.

The sweep works on registry rows only: a row is a removed charger's entity
when its key reads ``charger_<id>_<suffix>``, the suffix is one a configured
charger also has, and no reading of the key names a configured charger.
"""
from types import SimpleNamespace

from custom_components.solar_energy_management.charger_entity_sweep import (
    orphan_charger_rows,
)

E = "01ENTRY"


def row(domain, key, prefix=E + "_", platform="solar_energy_management"):
    return SimpleNamespace(entity_id=f"{domain}.sem_{key}", unique_id=prefix + key,
                           platform=platform, domain=domain)


SUFFIXES = ["target_time", "power", "flow_grid_to_ev_power", "daily_ev_target", "charge_mode"]


def rows_for(cid, sem_prefix=False):
    out = []
    for i, s in enumerate(SUFFIXES):
        dom = ["time", "sensor", "sensor", "number", "select"][i]
        out.append(row(dom, f"charger_{cid}_{s}", prefix="sem_" if sem_prefix and dom == "sensor" else E + "_"))
    return out


def ids(rows):
    return sorted(r.entity_id for r in rows)


def live_of(*cids):
    return {r.entity_id for c in cids for r in rows_for(c)} | {r.entity_id for c in cids for r in rows_for(c, sem_prefix=True)}


def test_removed_charger_loses_every_entity_the_kept_one_keeps_all():
    rows = rows_for("ev_charger") + rows_for("ev_charger_1", sem_prefix=True)
    gone = orphan_charger_rows(rows, E, {"ev_charger"}, live_of("ev_charger"))
    assert ids(gone) == ids(rows_for("ev_charger_1", sem_prefix=True))


def test_prefix_ids_do_not_collide():
    rows = rows_for("ev_charger") + rows_for("ev_charger_1") + rows_for("ev_charger_12")
    assert ids(orphan_charger_rows(rows, E, {"ev_charger", "ev_charger_12"},
                                   live_of("ev_charger", "ev_charger_12"))) == ids(rows_for("ev_charger_1"))
    assert orphan_charger_rows(rows, E, {"ev_charger", "ev_charger_1", "ev_charger_12"},
                               live_of("ev_charger", "ev_charger_1", "ev_charger_12")) == []


def test_a_leftover_row_never_teaches_a_suffix():
    # Without the live filter, ev_charger_1's rows would read as ev_charger + "1_power".
    rows = rows_for("ev_charger") + rows_for("ev_charger_1")
    assert ids(orphan_charger_rows(rows, E, {"ev_charger"}, live_of("ev_charger"))) == ids(rows_for("ev_charger_1"))


def test_no_live_rows_removes_nothing():
    rows = rows_for("ev_charger") + rows_for("ev_charger_1")
    assert orphan_charger_rows(rows, E, {"ev_charger"}, set()) == []


def test_a_longer_suffix_never_hides_a_configured_charger():
    rows = rows_for("ev_charger")
    assert orphan_charger_rows(rows, E, {"ev_charger"}) == []


def test_empty_or_unknown_charger_list_removes_nothing():
    rows = rows_for("ev_charger") + rows_for("ev_charger_1")
    assert orphan_charger_rows(rows, E, set()) == []
    assert orphan_charger_rows(rows, E, None) == []


def test_other_integrations_and_other_entries_are_untouched():
    rows = rows_for("ev_charger") + [row("time", "charger_old_target_time", platform="other"),
                                     row("time", "charger_old_target_time", prefix="02OTHER_")]
    assert orphan_charger_rows(rows, E, {"ev_charger"}) == []


def test_global_and_unparsable_keys_stay():
    rows = rows_for("ev_charger") + [row("sensor", "charger_count"), row("sensor", "charging_state"),
                                     row("sensor", "charger_ev_charger_1_brand_new_suffix")]
    assert orphan_charger_rows(rows, E, {"ev_charger"}) == []


def test_setup_runs_the_sweep_after_the_platforms():
    import ast
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("__init__.py").read_text()
    i_setup = src.index("async_forward_entry_setups(entry, PLATFORMS)")
    i_sweep = src.index("sweep_removed_charger_entities(")
    assert i_sweep > i_setup
    ast.parse(src)
