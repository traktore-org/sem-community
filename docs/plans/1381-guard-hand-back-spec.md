# Challenge — fix/1381-guard-hand-back

Branch: `fix/1381-guard-hand-back` (worktree `~/sem-1381`). Code: `coordinator/guard_hand_back.py`,
the send seam in `devices/base.py` (`send`), wiring in `coordinator/coordinator.py` (both charger
paths, fleet state, store/restore). Tests: `tests/test_1381_guard_hand_back.py`.

VERDICT: PENDING — the independent reviewer has not run yet.

## Claims for the reviewer (REFUTE them)

CLAIM 1: SEM only ever undoes its OWN guard stop. The hand-back sends exactly the inverse of the
commands the stop let through (switch on, number/select back to the prior value), never a command
it did not record, never a current to a yielded charger, never keba.authorize; a stop with no safe
inverse is never guessed at (the charger stays off and a Repair says so).

CLAIM 2: A hand-back never pushes a phase over its limit by SEM's own arithmetic: it waits for the
guard to be `enforcing_armed` and every monitored phase to have the charger's draw before the
stop (or its minimum, whichever is larger) plus the guard's recovery margin (2 A) free; with two
or more stopped chargers only one is handed back per cycle, highest priority first, and the next
waits at least 120 s so the meter shows the first one's draw.

CLAIM 3: No loop. A charger the guard stops again within 15 min of a hand-back waits 10, 20,
40 min; after three such failures SEM stops trying for good and raises one Repair naming the
charger. Nothing in a restart, a store round-trip or observer mode resets that count.

CLAIM 4: SEM never acts against the other party or the user: the record is dropped without
any command when an entity SEM touched no longer shows the state SEM left (switched on by the
other party or by hand), when the car is known to be gone (`car_absent`, never "unknown"), when
SEM steers the charger again (no longer yielded), or when the charger is removed.

CLAIM 5: The record survives an HA restart (stored with the EV session state) and the charger
state and the fleet state read "Stopped by the phase guard" while SEM holds it off and no car
draws — never "night charging active" at 0 W; a charger SEM controls normally is unaffected.

## Author's attack notes

- Restore order is the order the stop sent the commands. For "current 0, then switch off" that
  sets the current back before switching on; for "switch off, then current 0" it switches on at
  0 A for one call. Both are harmless; a strict reverse order would just swap which case has it.
- The draw is the charger's power at the moment of the stop. A car still ramping up (e.g. 2 kW at
  16:43:07) underestimates it; the hand-back can then come too early, the guard trips again and
  the back-off takes over. A re-stop keeps the larger draw of the two records.
- A one-phase charger needs its draw free on EVERY monitored phase (SEM does not know which
  phase it is on). Conservative: it can wait longer than needed.
- A guard that is switched off (not enforcing) claims no protection: a held charger is handed
  back without a margin check. The user turned the guard off; SEM undoes its stop.
- Observer mode: a record from before observer was switched on is shown as a withheld
  `switch.turn_on` at most every 10 min and kept until observer is off.
- `fleet_state` overrides any global text, not only "charging" ones, while a charger is held and
  none draws. Intended: the held charger is the news.
