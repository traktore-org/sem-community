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
