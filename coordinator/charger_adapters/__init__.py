"""ChargerAdapter — encapsulates per-brand hardware quirks.

The multi-charger architecture migration moves brand-specific
behaviour (KEBA rejects ``set_current < 6 A``, KEBA self-resumes on
plug-in, KEBA's ``charging_state`` sensor lags real draw by ~5 s,
etc.) out of the actuator and into a dedicated adapter layer.

Pre-architecture, ``coordinator/ev_control.py`` was riddled with
KEBA-specific branches:

- The "set_current(0) doesn't actually stop KEBA" workaround that
  produced #315 (off-mode), #346 (solar_only night), and #353
  (solar_only sub-min surplus) — three independent guards for the
  same firmware quirk.
- The ``charging_state`` vs ``power_w > 500`` ambiguity that
  drives the #289 ``sem_ev_power`` lag.
- The 6 A IEC 61851 minimum hardcoded in the actuator's amp
  clamping.

Each of these is a property of the KEBA firmware, not of the SEM
control loop. The adapter pattern encapsulates them.

After the migration, the actuator says ``adapter.command_idle()``
without knowing whether the underlying brand needs
``set_current(0)`` (Wallbox / go-eCharger) or
``service: keba.disable`` (KEBA) or both. New brands ship as new
adapter subclasses with no touch to the actuator.

This Step 2 of the architecture migration adds the protocol and the
KEBA implementation. Steps 4 / 6 (actuator + data model inversion)
wire it in.
"""
from typing import TYPE_CHECKING

from .base import ChargerAdapter
from .generic import GenericAdapter
from .keba import KebaAdapter

if TYPE_CHECKING:  # pragma: no cover
    from ...devices.base import CurrentControlDevice


def adapter_for(device: "CurrentControlDevice") -> ChargerAdapter:
    """Pick the right adapter for a charger.

    Inspection: the device's ``charger_service`` reveals which
    integration. Anything starting with ``keba.`` gets the KEBA
    adapter (6 A min, self-resume guard, etc.). Everything else gets
    ``GenericAdapter``. To add brand-specific quirks in the future:
    add a dedicated adapter subclass + branch here.
    """
    service = (getattr(device, "charger_service", "") or "").lower()
    if service.startswith("keba."):
        return KebaAdapter(device)
    return GenericAdapter(device)


__all__ = ["ChargerAdapter", "GenericAdapter", "KebaAdapter", "adapter_for"]
