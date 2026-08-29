"""The two axes of a device row, and the words for them (#780).

Every appliance SEM knows about is described twice: once as a row in
``LoadManager._devices`` (the peak-shed side) and once as a device in the
surplus controller's list. Both rows answer two independent questions, and
before #780 only one of them had an honest name:

**Capability — is there anything to switch?**
    A control handle was discovered for this appliance: a switch entity, a
    number entity, a service call. Pure discovery fact; the user's opinion
    doesn't enter into it. ``has_control_handle``.

**Permission — may SEM switch it, and under which policy?**
    Two parts: the ``control_mode`` the user picked (``surplus`` /
    ``peak_only`` / ``off`` / ``manual``), and the explicit "never touch this
    load" opt-out from the priority card (#650). ``user_hands_off``.

The old flag ``is_controllable`` was capability AND-ed with half of permission,
under a name that reads as pure permission. In #779 that cost real diagnosis
time on both sides: the reporter's diagnostics said ``is_controllable: true``
for a device he had set to Mode: Off while SEM was switching it off — capability
true, permission off, both correct, and indistinguishable from the bug we were
actually chasing. #650 is the earlier scar; it had to write a paragraph
explaining why ``controllable_override=True`` is not the symmetric case of
``False``, because "controllable" was being read as permission there too.

So: three functions, each answering exactly one question, and every consumer
asks the one it means. The accessors read the new key first and fall back to
the legacy mixed key, so a row written by an older install — or by a code path
that hasn't been migrated — reaches the same verdict it always did.
"""
from __future__ import annotations

from typing import Any, Mapping

# The mixed flag. Still written (derived) for one release so outward readers
# that predate #780 keep answering, still read here so no row loses its say.
LEGACY_MIXED_KEY = "is_controllable"

CAPABILITY_KEY = "has_control_handle"
HANDS_OFF_KEY = "user_hands_off"


def has_control_handle(device_info: Mapping[str, Any]) -> bool:
    """CAPABILITY: has a way to control this appliance been found?

    Falls back to the legacy mixed key, whose ``False`` also meant "no handle"
    — ambiguous by construction, which is the bug — and finally to ``True``,
    the default every pre-#780 call site used.
    """
    if CAPABILITY_KEY in device_info:
        return bool(device_info[CAPABILITY_KEY])
    return bool(device_info.get(LEGACY_MIXED_KEY, True))


def user_hands_off(device_info: Mapping[str, Any]) -> bool:
    """PERMISSION: has the user said "never touch this load"? (#650)

    No legacy fallback on purpose. A legacy ``is_controllable: False`` is
    already answered by :func:`has_control_handle`; reading it here too would
    count the same bit twice and, worse, would re-mix the axes this module
    exists to separate.
    """
    return bool(device_info.get(HANDS_OFF_KEY, False))


def may_actuate(device_info: Mapping[str, Any]) -> bool:
    """Both axes, in one question: is there a handle AND permission to use it?

    Permission is ``control_mode != "off"`` (#49) and no hands-off opt-out
    (#650). This is what the peak-shed loop actually wants to know, and now the
    only expression of it — pre-#780 the mode half was checked at some call
    sites and forgotten at others, which is how the "how much can we shed?"
    counters came to include devices shedding would never touch.
    """
    if device_info.get("control_mode") == "off":
        return False
    return has_control_handle(device_info) and not user_hands_off(device_info)
