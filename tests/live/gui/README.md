# Browser-driven live tests (HA-TEST)

The fourth layer of SEM's test pyramid: a real Home Assistant, the real
dashboard, a real browser, and a real click.

## Why this layer exists

Every layer below it was green while, on a fresh install, SEM **read 0 W from
a 4.2 kW inverter** — the #915 config-flow step wrote key names the sensor
reader never consumed. The halves were tested; the seam was not. The same
build shipped a card that said *"unconfirmed"* with no way to confirm, and a
near-miss list telling users to report their Zigbee coordinator. None of that
is visible to a unit test, because none of it is a wrong return value: it is
work a person cannot finish.

| Layer | Catches | Where |
|---|---|---|
| Unit | wrong values | `tests/test_*.py` |
| Scenario | decision-vs-enforcement drift | `tests/scenarios/*.yaml` |
| Live (curl) | time, reactivity, persistence | `tests/live/test_*.sh` |
| **Live (browser)** ← here | *the user cannot finish the job* | `tests/live/gui/*.js` |

## Running

```bash
source ~/.config/sem/tokens.env
cd /tmp && npm install --no-save playwright@1.59.0     # once; browser must be present
cd /home/sem/sem-community

HA_TOKEN=$HA_TEST_TOKEN node tests/live/gui/test_915_detected_hardware.js
HA_TOKEN=$HA_TEST_TOKEN node tests/live/gui/test_915_install_without_energy_dashboard.js
```

`SHOT_DIR=/some/dir` writes evidence screenshots. `HA_URL` overrides the host;
`lib.js` refuses PROD outright, because these tests click buttons.

## What each file covers

**`test_915_detected_hardware.js`** — the Configuration → Detected hardware
section as a person meets it. Renders without console errors · names what it
found with the evidence · a near miss is hardware and not the MQTT bus · an
installed integration's declared controls are proposed · every proposal offers
an *action* rather than the word "unconfirmed" · **clicking Use this writes the
option SEM reads** · and the accepted row stops being proposed, so the loop
closes.

**`test_915_install_without_energy_dashboard.js`** — the install that used to
be refused. Removes the grid source from the Energy Dashboard (through HA's
own `energy/save_prefs`, restored in `finally`), then drives the real
Add-integration dialog: the flow opens the sources step instead of aborting ·
every field is pre-filled and says which declared key matched · the install
completes · **and SEM then reads each source's live value**, which is the
assertion the unit suite could not make.

## Two traps worth knowing before you add a test here

1. **Shadow DOM.** `textContent` stops at a shadow boundary, and collecting
   only childless elements drops every paragraph containing an inline
   `<code>` — the exact shape of a config-flow step description. `deepText()`
   walks text nodes across roots; use it.
2. **HA's delayed stores.** `energy/save_prefs` returns before the file is
   written, and SEM reads the file. Without a settle the first run of the
   onboarding suite deleted the grid source, immediately started the flow, got
   the ordinary path, and passed while testing nothing.

Both cost a green-looking run that proved nothing, which is the failure mode
this layer exists to prevent.

## `test_915_near_miss_offer.js` — the offer, via a fixture

"Add this charger" is unreachable on a healthy rig: every brand present is
detected, and a near miss for a detected brand is filtered as noise. So
`tools/zaptec_sim` grows an **`unmapped_charger`** option that publishes the
installation device alone — a power reading and the site's grid-guard current,
no cable state, no charging state, no throttle. SEM can describe it and cannot
map it, which is exactly the near miss the offer answers. The suite turns the
fixture on, asserts the offer appears and is wired to the entity the *real*
Zaptec integration declares, **clicks it**, checks the charger that was
created, and turns everything back off.

## Running order, and the traps between suites

Run them in this order, and one at a time:

```
test_915_detected_hardware.js        # reads + one click, non-destructive
test_915_near_miss_offer.js          # flips a sim option, adds/removes a charger
test_915_install_without_energy_dashboard.js   # DELETES SEM and reinstalls it
```

Traps that cost real time here, all of them about the rig rather than SEM:

1. **A destructive suite must put the rig back even when it fails.** One
   interrupted run left `.46` with no SEM entry, and every other suite failed
   for reasons that had nothing to do with them. The install suite now
   guarantees an entry exists before it exits.
2. **Never "restore" a state you did not verify.** The same suite backs up the
   Energy Dashboard and restores it; run against an already-broken dashboard it
   faithfully restored the breakage, and the next run inherited it. It refuses
   to start now if the grid source is missing.
3. **Never restore `.storage` by file copy under a running Home Assistant.**
   HA holds those prefs in memory and rewrites the file on its next save, so
   the copy silently loses. Go through the API (`energy/save_prefs`).
4. **Removing a charger is a service, not a shorter list.** `set_option` merges
   `ev_chargers` by id and preserves siblings (#464, so a partial submit can
   never drop one), so filtering the list does nothing. Use
   `solar_energy_management.remove_charger`.
5. **Do not compare two entities sampled at different instants.** The rig's
   grid value moves every cycle; a strict equality between SEM's reading and
   its source tests how fast the sun went behind a cloud. Sample the source
   either side and assert SEM lies in that envelope.
6. **The Add-integration dialog races Home Assistant's own discovery.** Since
   #915 SEM offers itself when a supported inverter appears, and a discovery
   flow in progress makes the manual route a dead end — while the card is not
   always there yet. The install suite asserts the step through the flow API
   (the same strings HA renders) and keeps the browser for evidence.
