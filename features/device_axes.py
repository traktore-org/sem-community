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


#: (#1419) The modes that let SEM switch a load. Anything else — "off", an
#: unknown word, or NO mode at all — means SEM leaves the load alone.
ACTING_MODES = frozenset({"surplus", "peak_only", "manual"})


def mode_permits(device_info: Mapping[str, Any]) -> bool:
    """(#1419) PERMISSION, mode half: did the user turn SEM control on?

    A device does nothing until the user turns SEM control on for it. Every
    row SEM builds itself carries the mode the user chose, or the default
    "off" for a new device (#805). A row with NO mode is one nobody could
    ever set: the old pattern discovery saved such rows (a camera's
    "enabled" switch, a bedroom plug), they never reached the Devices card,
    and the peak shed switched them off. No mode reads as off.

    A charger row is the exception: its permission is the charge mode, which
    the charger loop owns; its load row never carried a ``control_mode``. A
    charger-typed row that DOES carry one (an Energy-Dashboard row the user
    set to Off) keeps the user's word.
    """
    mode = device_info.get("control_mode")
    if mode is None and device_info.get("device_type") == "ev_charger":
        return True
    return mode in ACTING_MODES


def may_actuate(device_info: Mapping[str, Any]) -> bool:
    """Both axes, in one question: is there a handle AND permission to use it?

    Permission is a mode the user turned on (#49, #1419) and no hands-off
    opt-out (#650). This is what the peak-shed loop actually wants to know,
    and now the only expression of it — pre-#780 the mode half was checked at
    some call sites and forgotten at others, which is how the "how much can we
    shed?" counters came to include devices shedding would never touch.
    """
    if not mode_permits(device_info):
        return False
    return has_control_handle(device_info) and not user_hands_off(device_info)


def device_mode_permits(device: Any) -> bool:
    """(#1419) The same permission, for a live device object of the surplus
    engine (``control_mode`` is a ``DeviceControlMode``): may SEM act on it
    at all? Every Off check on a device object reads this — the shedder reads
    ``mode_permits`` on its rows — so "off means off" has one home per shape.
    """
    mode = getattr(device, "control_mode", None)
    value = getattr(mode, "value", mode)
    return value in ACTING_MODES
