# #620 — Generic-device goal model: priority + min/max + battery-eligibility (NO deadlines)

**Status:** Design (2026-07-20). Supersedes the earlier "guaranteed-by-deadline top-up" framing on #620 after a design review (see the #620 thread). Build target 1.8.0.

**Origin:** onkelfu's pool filter (discussion #619 → #620): "min 8 h, max ~10 h, prefer PV, don't over-run." The naïve reading — "guarantee the minimum by a deadline with grid/battery top-up" — was rejected after working the edge cases; see §2.

## 1. The model (what we build)

A generic switch/relay load is controlled by **three per-device knobs** plus its place in the **one priority list** (#576). No per-device target times / deadlines.

| Knob | Meaning | Default |
|---|---|---|
| **Minimum** | A floor the device should reach each day (runtime minutes; energy later). Protects the device from being fully starved behind higher-consumption siblings. NOT a hard guarantee. | 0 (off) |
| **Maximum** | A hard cap — the device never runs past this in a day. Prevents a device hogging the ceiling / over-running (pump wear, waste). | none (uncapped) |
| **Allow overnight battery** | Opt-in: the device may draw from the home battery (down to the reserve/buffer SoC) when there is no surplus. OFF by default — no silent battery drain to run a pool pump. | off |

Allocation is **continuous and priority-ordered**, not scheduled:

- **Sources, in order:** solar surplus (day) → peak headroom, i.e. grid draw kept under the peak limit (night/deficit) → **battery (night, only for opted-in devices, only down to the reserve SoC).**
- **Two hard ceilings bound everything:** the **peak limit** (never breached — caps the grid side) and the **reserve SoC** (never discharged past — caps the battery side). Priority + min/max shape everything between the floors and ceilings.
- **Anti-cycle:** every load has a **minimum on-time and minimum off-time** (default e.g. 5 min / 5 min) so a binary device near the surplus threshold does not duty-cycle its contactor/motor to death. This is net-new vs the EV path (the EV modulates current; a switch cannot).

The EV charger and HP/HW keep their **own dedicated guarantees** (the EV night planner with its Charge-by deadline; the HP/HW legionella cycle). Generic devices deliberately do NOT inherit deadline scheduling.

## 2. Why no deadlines (the rejected path)

The "guarantee min by a deadline, force grid/battery" model was worked through and rejected:

- **Winter peak contention.** An EV force-charging to a 07:00 deadline hogs the peak ceiling for hours; a heat pump behind it starves. Honouring both deadlines requires capping the EV to make room → a peak-constrained, priority-aware, multi-device *scheduler* with infeasibility detection.
- **That scheduler is unsolved in the field.** evcc's load management explicitly states priority is *"not yet taken into account in load management … rebalancing across active sessions is not yet supported"* — it ships greedy circuit-throttling. Solarmanager (Swiss HEMS) does the same: dynamic load management that *throttles consumers against the house connection*, priority-ordered — **no per-generic-device deadlines**. The whole field coordinates by continuous priority-throttle, not deadline scheduling.
- **Binary loads make it worse** — you can't proportionally throttle a pump; a deadline scheduler for binary devices is bin-packing, not division.

Conclusion: continuous priority + min/max floor/cap is the industry-proven shape; the min/max floors and the battery opt-in are the parts Solarmanager/evcc don't expose — our differentiator, and buildable without a scheduler.

Deferred (explicit v2): target-time optimal overnight scheduler (folds in the parked #6 forecast+tariff battery scheduler), precise surplus-profile reachability, per-device battery *priority* arbitration under contention.

## 3. Config surface

Per-device (on `SwitchDevice`, serialized + **restored** — the #559 HIGH-1 was an un-persisted cap):

- `daily_min_runtime_sec` (exists)
- `daily_max_runtime_sec` (**new**, persisted, gate `daily_max_runtime_reached` stops the device)
- `battery_eligible_overnight: bool` (**new**, default False)
- `min_on_time_sec` / `min_off_time_sec` (**new**, anti-cycle; sane defaults)

Global (exists): the one priority list, the peak limit, the battery reserve/buffer SoC (reuse the Solar Gate buffer, #537).

The control-mode dropdown stays **off / peak-only / surplus** (unchanged vocabulary); the min/max/battery knobs live in the device's target panel, shown in surplus mode.

## 4. Allocation (surplus_controller)

Extend the existing priority-ordered surplus pass:

1. **Day / surplus present:** distribute surplus by priority to devices below their max (unchanged), honouring min-on/off.
2. **Night / deficit, device below its min:** grant **peak-headroom grid** in priority order until the peak limit is reached; lower-priority devices wait for headroom. Never breach the peak limit — a device that can't get headroom simply doesn't run (graceful miss + reason).
3. **Battery-eligible devices** may additionally draw battery (above the reserve SoC), priority-ordered, when no peak headroom or as configured. Reserve SoC is hard.
4. A device at its **max** is excluded from all passes for the rest of the day.

Reason surface (like the EV strategy sensor): each device publishes *why* it is or isn't running ("waiting — peak headroom taken by higher-priority heat pump"; "capped at 10 h"; "on battery, reserve 20% protected").

## 5. UI (mockup-first — this spec's gate)

The device target panel mirrors the load-priority card's existing look, NOT the full EV card (a switch does not need 5 modes / dual-amp / taper):

- **Min / Max** as an **EV-style dual-handle range slider** (green *at least* handle + orange *up to* handle, green→orange gradient fill — identical to the charger's Charge-target slider), with today's progress line (`X.X / Y h`).
- **Allow overnight battery** toggle with a one-line hint.
- Anti-cycle min-on/off under an "advanced" disclosure (sane defaults; most users never touch).
- The device's priority is its drag position in the one list (unchanged).

Mockup approved before card code (working-agreement §1).

## 6. Testing & rollout

- Unit: min/max gates, anti-cycle timers, battery-eligible reserve floor, priority allocation under a peak cap (binary devices), max-cap persistence across restart (#559 HIGH-1 regression).
- **Live rig verification** (this force-imports / battery-draws): a mock switch load — below min at night, peak headroom available → runs on grid within the limit; peak full → waits + reason; battery-eligible + no headroom → draws battery, stops at reserve. Anti-cycle proven (no sub-min-off toggling).
- Soak on PROD before ship. v1 = daytime surplus + min/max + anti-cycle + night peak-headroom + battery opt-in. Optimal overnight scheduler = v2.

## 7. Docs

SETUP_GUIDE Load Management section + LOAD_PRIORITY.md updated to the min/max/battery model; README already corrected (beta.19). The evcc/Solarmanager comparison and the "no deadlines" rationale recorded here.
