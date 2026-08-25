"""The simulated charger's behaviour model (#804).

Every rule here is taken from evidence rather than invented:

* **current 0 is a SOFT pause** — @coppe218 held his Zaptec Go 2 at 0 A for
  roughly half an hour and it resumed on its own when he raised the current
  again. That is SEM's own stop=0/start=N model, and it is why the Zaptec
  needed a control entity rather than a resume surface.
* **an explicit stop LATCHES** — EVCC sends `CmdStopChargingFinal` and needs
  `CmdResumeCharging` to undo it. Raising the current does not clear it. This
  is the state SEM must never drive into unintentionally, and the one where a
  resume surface is genuinely required.
* **phase switching lives on the INSTALLATION** as a current threshold
  (32 A → 1-phase, 0 A → 3-phase), not as a phase command — which is why
  #804's stop→switch→settle sequencer had nothing to talk to.
"""
from __future__ import annotations

import logging

from .const import (
    DEFAULT_MAX_A, DEFAULT_MIN_A, PHASE_SWITCH_1P_A, VOLTAGE,
)

_LOGGER = logging.getLogger(__name__)


class ZaptecSimState:
    """One simulated installation + charger."""

    def __init__(self) -> None:
        self.cable_connected: bool = True
        self.charger_max_current: float = DEFAULT_MAX_A
        self.charger_min_current: float = DEFAULT_MIN_A
        self.available_current: float = 25.0        # the 3x25 A grid guard
        self.phase_switch_current: float = 0.0      # 0 → 3-phase
        self.hard_stopped: bool = False
        self.session_energy: float = 0.0
        self._listeners: list = []

    # ── derived ──────────────────────────────────────────────────────────
    @property
    def phases(self) -> int:
        return 1 if self.phase_switch_current >= PHASE_SWITCH_1P_A else 3

    @property
    def effective_current(self) -> float:
        """What the box will actually draw: its own max, capped by the
        installation's available current — the guard applies to every charger
        on the site, which is exactly why SEM must not use it as a throttle."""
        return min(self.charger_max_current, self.available_current)

    @property
    def charging(self) -> bool:
        if self.hard_stopped or not self.cable_connected:
            return False
        return self.effective_current >= self.charger_min_current

    @property
    def power_w(self) -> float:
        if not self.charging:
            return 0.0
        return round(self.effective_current * VOLTAGE * self.phases, 1)

    @property
    def operation_mode(self) -> str:
        if not self.cable_connected:
            return "Disconnected"
        if self.hard_stopped:
            return "Paused"
        return "Charging" if self.charging else "Connected_Requesting"

    # ── commands ─────────────────────────────────────────────────────────
    def set_charger_max_current(self, amps: float) -> None:
        """The soft pause. Note what does NOT happen: dropping to 0 never
        sets hard_stopped, and raising it again charges without a resume."""
        self.charger_max_current = max(0.0, float(amps))
        _LOGGER.debug("sim: charger_max_current=%.1f charging=%s",
                      self.charger_max_current, self.charging)
        self.notify()

    def hard_stop(self) -> None:
        """CmdStopChargingFinal — latches until an explicit resume."""
        self.hard_stopped = True
        self.notify()

    def resume(self) -> None:
        """CmdResumeCharging — the ONLY way out of a hard stop."""
        self.hard_stopped = False
        self.notify()

    def add_listener(self, cb) -> None:
        self._listeners.append(cb)

    def notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug("listener failed: %s", e)
