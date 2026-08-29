"""#853 — what the P30's energy register actually does (measured 28.08.2026).

Kept for the numbers, which cost a live PROD evening to obtain. The
CONCLUSION I first drew from them was wrong and is superseded by #854;
this file now records only the facts.

Written directly to the real box via ``keba.set_energy``, register read
back:

| written | reads |
|---|---|
| 0.3 | **1.0** |
| 0.5 | **1.0** |
| 2.5 | 2.5 |
| 0 | 0.0 (= no limit) |

Any non-zero target below 1 kWh is rounded UP by the firmware. So a quota
can never be used to say "charge nothing" — the smallest enforceable one
is 1 kWh.

What I wrongly concluded: that this made "Min = 0 costs 1 kWh" a hardware
truth. It did not. SEM was not obliged to write a quota at all — the old
stop wrote one *and enabled the box to charge into it*. The 1 kWh was
SEM's command, not the firmware's demand (#854).
"""
from __future__ import annotations


def test_the_quota_floor_is_the_firmware_not_a_sem_choice():
    """Documents the measurement: below 1 kWh the box rounds up, so any
    code that computes a sub-1 kWh quota is computing a fiction."""
    measured = {0.3: 1.0, 0.5: 1.0, 2.5: 2.5, 0.0: 0.0}
    for written, reads in measured.items():
        expected = 0.0 if written == 0 else max(1.0, written)
        assert reads == expected, (
            "the P30 rounds any non-zero energy target up to 1.0 kWh"
        )
