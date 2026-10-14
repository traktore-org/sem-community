# #1054 — a charger is a device reference, the crawler fills in the roles

**Goal:** a configured charger can never be lost, duplicated or resurrected.
SEM stores WHICH device a charger is; the crawler says, at every start, what
that device can do.

**Why (round 3, weindler, beta.15 — proven on HA-TEST 11.10.2026):** his
working go-e was lost and an old half-filled card stayed. The chain:

1. An earlier detection left a half card (`goecharger_28eb748ac3`: a name and
   one energy counter) in `entry.data` and `entry.options`, FIRST in both.
2. First = primary. The Configure dialog's "Remove a charger" never offers the
   primary (`config_flow.py` `async_step_ev_charger_remove`,
   `removable = ev_chargers[1:]`), so its only choice was the working go-e.
   Replayed on the old code: the dialog offered only `goecharger_<device>`
   (`tests/test_1054_weindler_replay.py`).
3. The half card named one go-e entity (`energy_total_corrected`, on the go-e
   device), so the detection report counted the whole box as configured
   (`hardware_detection.py`, configured-charger rows) and hid the offer that
   could rebuild it: "1 charger detected, configured", every field empty.
4. The removed charger's daily kWh and SOC rows stayed published (health check:
   9.45 kWh against a fleet of 0).

Every one of these exists because a charger is stored as a copy of its entity
ids, twice (`data` + `options`), healed by union, folded by guesswork. Round 3
patched each (branch `fix/1054-charger-lost`, PR #1091). This plan removes the
copy instead.

---

## 1. Store shape

`entry.options["ev_charger_refs"]` — the ONE store. A list of:

```python
{
  "id": "goecharger_118c…",        # stable, per-charger state is keyed by it
  "device_id": "118c…",            # HA device registry id; None = device-less
  "name": "go-eCharger",
  "overrides": {                   # only roles the USER set, or a device-less
      "ev_charging_power_sensor": "sensor.x"   # charger's whole mapping
  },
  # settings stay as today (mode, priority, targets, min/max current,
  # vehicle_soc_entity, phases, pause record, …) — they are choices, not roles
}
```

Rules:
- one ref per `device_id` (enforced on every write and in the migration);
- a device-less charger (`device_id: None` — PROD's KEBA, service-driven
  boxes) keeps its full entity mapping in `overrides`: exactly today's card;
- `entry.data` holds no charger list after the migration.

## 2. The resolver — one function, every reader goes through it

`hardware_detection.resolve_charger(hass, ref) -> dict` returns today's card
shape (all `CHARGER_ENTITY_KEYS`, service, service data, param name), built as:
`crawler live view of ref.device_id` ← then `ref.overrides` on top ← then the
settings. Plus `_role_source: {role: "crawler" | "you"}` for the card and
diagnostics.

At setup the resolved list becomes `coordinator.config["ev_chargers"]`, so the
26 runtime readers (`coordinator.py` 49 refs, `sensor_reader.py` 24,
`sensor.py` 13, `select/number/time/button/binary_sensor`, `ev_control`,
`load_management`, `per_charger_context`, `energy_calculator`, `build_view`,
`ev_night_targets`, `charging_control`, `refill_estimate`, `night_backfill`,
`demand_labels`, `charger_types`, `install_modules`, `device_registry`,
`dashboard_generator`) keep reading the shape they read today. Only WRITERS
change. MULTI_CHARGER.md's per-charger invariant is untouched.

## 3. Writers (the only code that changes shape)

| Writer | Today | After |
|---|---|---|
| **all writers** (built 11.10) | write `options.ev_chargers` | unchanged for one release: they still write the legacy list; the next setup sees it changed (fingerprint `ev_charger_refs_sig`) and folds the change into the refs (`charger_refs.apply_legacy_edit`) — one place, so no writer can bypass the refs |
| `set_option` (`__init__.py`) | merge cards by id, fold | (later) upsert ref by `id`; a ref for a `device_id` that has one = update it |
| `persist_per_charger_option` | copy-patch options list, data fallback | patch the ref's settings |
| `remove_charger` service | drop from options + data | drop the ref |
| options flow add / edit / remove | card dicts in `_data` | add = pick a crawler-found device (or "manual" → device-less ref); edit = settings + per-role "set by you"; remove = any ref, the last one too |
| card "Add this charger" | sends the crawler offer | sends `{device_id, name}` |
| card per-role picker | writes the entity | writes `overrides[role]`; "use detected" clears it |
| startup heal `_heal_ev_chargers_options` | unions data into options | **deleted** |
| fold `_same_box_as`, displacement | guess a copy | **deleted** (one ref per device makes copies impossible) |

## 4. One migration (at setup — NO entry-version bump)

Built 11.10: Home Assistant refuses to set up an entry whose version is newer
than the code, so a bump would break the downgrade promise (§5). The
conversion runs in setup instead, guarded by the presence of
`options.ev_charger_refs`, in the place the old heal ran.

For the union of `data.ev_chargers` and `options.ev_chargers` (options wins per
id, as the heal did):
1. `device_id` = the device the card's entities sit on (entity registry; the
   majority if they disagree; none → device-less).
2. `overrides` = every role whose stored entity differs from the crawler's live
   answer for that device. Device-less → all roles.
3. Two cards on one device → ONE ref: the complete card's id and settings win;
   the other id's per-charger state is swept (logged once). A half card alone
   on its device stays (it becomes a ref the crawler completes).
4. Write `options.ev_charger_refs`; remove `data.ev_chargers`.
5. A migration that cannot ask the registry (entity unknown, HA starting)
   keeps the card device-less with every role as an override — never drops it.

## 5. Rollback (a downgrade must not lose the charger)

For one release the new code ALSO writes the resolved list to
`options["ev_chargers"]` after every ref write — a read-only legacy copy. New
code never reads it. A downgrade to beta.15 reads it as today's cards and
works. `data.ev_chargers` is gone, so the old heal has nothing to resurrect.
Removed in the release after.

## 6. The crawler checks itself at every start

For every ref with a `device_id`:
- the device is gone from the registry → Repair "Charger *name*: its device
  was removed" (one click: remove the charger);
- a REQUIRED role (`EV_REQUIRED_SENSORS`, plus a control) has no live answer
  and no override → Repair naming the role and the device;
- an override's entity no longer exists → Repair naming it.
Texts in all 16 languages, as translation keys (no inline strings).

## 7. Per-charger state

Ids survive the migration, so state carries over. Merged duplicates and
removed refs: the sweep from round 3 (`_sweep_unconfigured_charger_state`)
stays and runs on the resolved ids.

## 8. Diagnostics

`ev_chargers` section: the refs, the resolved view with `_role_source`, and
the crawler's live answer per device — so a report shows what is stored and
what was found.

## 9. Tests (acceptance)

- the #1092 lifecycle suite (feature/1092-integration-lifecycle) over every rig
  capture: crawl → create → restart → upgrade → delete → recreate; its
  goecharger xfail (#1054) must flip to pass;
- `tests/test_1054_weindler_replay.py` (already on this branch): his entities,
  beta.13 and beta.15 stores, his UI path;
- migration goldens: PROD's real stored cards (read-only copy of PROD's entry,
  redacted) resolve to exactly today's config — **PROD's KEBA is device-less
  and must come out byte-identical**; HA-TEST's, RienduPre's two Wallboxes
  (conftest fixture), weindler's beta.13 and beta.15 stores;
- downgrade: after the migration, beta.15 code reading `options.ev_chargers`
  sets up the same chargers;
- one ref per device: every writer, property test;
- Repairs: device removed, role missing, override vanished.

## 10. Live proof

HA-TEST (bug pipeline, observer ON): the `goecharger` stand-in with weindler's
entity ids (built 11.10, kept in the scratchpad), his beta.13 then beta.15
stores, the migration at start, his UI path in headless Playwright;
screenshots `~/claude-jobs/mockups/1054-sim-*.png`. Then .175, then a PROD soak
(structural: no merge to develop before it).

## 11. What happens to round 3 (`fix/1054-charger-lost`, PR #1091)

Kept: the replay tests, the per-charger state sweep, the dialog may remove a
half primary, a half card does not claim its box in the report. Removed by
this build: the merge displacement and `device_of`, the data-side prune in
`set_option` (no data list exists). PR #1091 is closed unmerged when this
lands.

## Decided (Guido, 11.10.2026: "Perfect go ahead") — all five at the defaults below

## Open decisions (defaults in brackets)

1. **New key or reuse `ev_chargers`?** [new `ev_charger_refs`; `ev_chargers`
   becomes the one-release legacy copy — this is what makes the downgrade safe]
2. **The crawler's answer changes** (an integration update renames an entity):
   follow it silently? [follow it, and say so once in the log; a Repair only
   when a required role is gone]
3. **One device, two sockets** (a twin wallbox as one device): [allow a second
   ref on the same device only with an explicit `connector` setting; default
   one ref per device]
4. **Card UI for "detected" vs "set by you"** per role, with "use detected":
   [mockup first, EV card style, before any card code]
5. **Flat `ev_*` keys in `entry.data`** (the old primary mirror): [frozen for
   one release, dropped with the legacy copy]
