"""#1032 — the crawler rig: real integrations' output in a real Home
Assistant, with SEM's crawler run on it.

Every capture in ``tests/integrations_rig/captures/`` is replayed into a
fresh test instance and the crawler's conclusion is compared with a golden
file in ``tests/integrations_rig/crawler/``. A pin bump that renames a key,
or a crawler change that finds something different, fails here and shows
the difference. Regenerate the golden files deliberately:

    SEM_RIG_UPDATE=1 ~/bin/semtest tests/test_integrations_rig.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from .integrations_rig.rig import (capture_names, crawl, load_capture, replay,
                                   summary)

GOLDEN = Path(__file__).resolve().parent / "integrations_rig" / "crawler"

#: The upstream keys each capture must still carry. When one disappears on a
#: pin bump, the role tests below would pass for the wrong reason.
UPSTREAM_KEYS = {
    "tesla_fleet": ("charge_state_charge_current_request",
                    "charge_state_user_charge_enable_request"),
    "teslemetry": ("charge_state_charge_current_request",
                   "charge_state_user_charge_enable_request"),
    "tessie": ("charge_state_charge_current_request",),
    "tesla_wall_connector": ("vehicle_connected", "contactor_closed",
                             "total_power_w"),
    "myenergi": ("charge_mode", "phase_setting_select", "plug_status"),
    "zaptec": ("available_current", "resume_charging", "stop_charging_final",
               "total_charge_power"),
    "zaptec_no_limit": ("resume_charging", "stop_charging_final"),
    "easee": ("power", "status"),
    # unique ids are "<the box's name>_<key>"; the rig's box is wallbox_go_e
    "goecharger": ("wallbox_go_e_p_all", "wallbox_go_e_car_status",
                   "wallbox_go_e_allow_charging",
                   "wallbox_go_e_current_session_charged_energy",
                   "wallbox_go_e_energy_total"),
}


def test_every_capture_names_where_it_came_from():
    for name in capture_names():
        src = load_capture(name)["source"]
        assert src["kind"] in ("core-snapshot", "live-load", "live-install",
                               "declared"), name
        assert src.get("repo"), name
        assert src.get("tag") or src.get("commit"), name


@pytest.mark.parametrize("name", sorted(UPSTREAM_KEYS))
def test_the_upstream_keys_are_still_there(name):
    cap = load_capture(name)
    have = set()
    for e in cap["entities"]:
        have.add(str(e.get("translation_key") or ""))
        uid = str(e.get("unique_id") or "")
        have.add(uid.rsplit("-", 1)[-1])
        have.add(uid.split("_", 1)[-1])
    missing = [k for k in UPSTREAM_KEYS[name] if k not in have]
    assert not missing, f"{name}: upstream no longer has {missing}"


@pytest.mark.parametrize("name", capture_names())
async def test_the_crawler_finds_what_it_found(hass, name):
    cap = load_capture(name)
    await replay(hass, cap)
    got = summary(crawl(hass), cap["domain"])
    path = GOLDEN / f"{name}.json"
    text = json.dumps(got, indent=1, sort_keys=True) + "\n"
    if os.environ.get("SEM_RIG_UPDATE") == "1" or not path.exists():
        # semtest runs a COPY of the tree; write the golden file into the
        # source tree too when it says where that is
        targets = [path]
        if os.environ.get("SEM_SRC"):
            targets.append(Path(os.environ["SEM_SRC"]) / "tests"
                           / "integrations_rig" / "crawler" / path.name)
        for t in targets:
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_text(text)
        if os.environ.get("SEM_RIG_UPDATE") != "1":
            pytest.fail(f"no golden file for {name}; wrote one — review it")
    want = json.loads(path.read_text())
    assert got == want, (
        f"the crawler's view of {name} changed; if intended, regenerate "
        "with SEM_RIG_UPDATE=1 and review the diff")
