# KEBA charger failsafe

The KEBA charger has its own failsafe. If the charger gets no new current
setting for a set time, it falls back to a fixed current. The failsafe is a
setting on the charger. SEM manages it.

If the charger's failsafe is on while SEM sets the current, the charger can
fall back between SEM's commands. The current then flips, and some cars
(for example Renault Zoe) stop charging.

## Default: SEM manages the failsafe

The option `keba_arm_failsafe` is on by default. It has no row on the
screens.

When a charge starts, SEM sets the charger's failsafe to:

- Timeout: 600 s, so the charger does not fall back during charging.
- Fallback: 6 A, or the charger's minimum current if higher.

When SEM stops a charge, it sets a dead-man's switch:

- Timeout: 10 s. Fallback: 0 A. Saved on the charger.
- Sent 0.5 s after the stop. Checked 30 s later. If the fallback is still
  above 0 A, SEM sends it again, up to three times.

Some integrations raise a 0 A fallback to 6 A. Then the charger can start
again on its own after a stop.

## Option off: disable the failsafe at the charger

If `keba_arm_failsafe` is off, SEM does not change the failsafe. If the
charger's failsafe is on, SEM shows the Repair **KEBA failsafe is enabled —
disable it for steady charging**.

Disable it at the charger: send `failsafe 0 0 1` over UDP, or set the
failsafe timeout to 0 with the KEBA KeContact tools. The Repair clears when
the failsafe is off.

Use this option only if your charger can disable its failsafe.

## SEM never calls keba.authorize

SEM does not use the charger's RFID authorization. After a stop, the car
can ask again and the charger can start again. SEM stops the session again
with the dead-man's switch above.
