"""(#925) Run SEM's REAL cycle, with REAL chargers, across MANY cycles.

Why this exists
---------------
Thirteen test files mention ``_async_update_data``. Until #873, every one
of them did so through ``inspect.getsource`` — a string search over the
assembly rather than a run of it. #873 proved the barrier was never real:
the cycle touches no entity registry, no ``async_write_ha_state``, no
config entries. Fifteen lines of stand-in and it runs.

What #873 stopped short of is chargers. Its scenarios configure none, so
``if self._ev_devices:`` never fires and the entire per-charger loop —
``build_charger_view`` → ``decide`` → the stability filter → the phase
tick → ``note_redirect_outcome`` → ``actuate`` — has never been executed
by any test, ever. That loop is where nine of the eleven bugs found on
real hardware in September live.

The YAML scenario harness cannot go there and should not be made to. It
builds its coordinator with ``SEMCoordinator.__new__`` and hand-populates
the dozen fields the budget path needs, so ``_pcc_store``,
``_charge_stability``, the adapters and the reconcilers simply do not
exist on it; and it constructs ``PowerReadings`` directly, bypassing
``SensorReader`` by design. Reaching the loop from there means chasing an
open-ended tail of stubs — the brittle-mock drift its own docstring
already records twice.

Two properties this rig has that nothing else does:

**Real devices, not MagicMocks.** ``adapter_for()`` reads
``device.charger_service`` and calls ``.lower().startswith("keba.")`` on
it. On a ``MagicMock`` that attribute auto-vivifies and every comparison
returns a truthy Mock — so a mock charger silently resolves to the KEBA
adapter whatever you meant, and a test written against "a Wallbox" is
quietly testing KEBA. That is a vacuous pass with extra steps.

**One coordinator across cycles.** #873 builds a fresh coordinator per
call, which is right for a single-shot energy-balance assertion and wrong
for everything stateful. The blink hold counts cycles; the redirect veto
counts three strikes; the phase tick counts a gap in seconds. State that
resets every cycle can never accumulate, so a rig that rebuilds cannot
observe any of them — it would report "no strike" forever and look green.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)


class _States:
    """A real state registry — ``get`` returns a state or None, never a mock.

    (#873's finding, kept.) A MagicMock states object makes every read a
    MagicMock, the first comparison raises, and the cycle's blanket
    handler turns that into ``UpdateFailed`` — which reads as "the cycle
    cannot be tested" when it means "the stand-in was wrong"."""

    def __init__(self, mapping=None):
        self._m = dict(mapping or {})

    def set(self, entity_id, value):
        self._m[entity_id] = value

    def get(self, entity_id):
        if entity_id not in self._m:
            return None
        v = self._m[entity_id]
        if isinstance(v, tuple):        # (state, attributes)
            state, attrs = v
        else:
            state, attrs = v, {}
        return SimpleNamespace(entity_id=entity_id, state=str(state),
                               attributes=dict(attrs), last_updated=None,
                               last_reported=None)

    def async_all(self, *args, **kwargs):
        return []


def make_hass(states=None):
    hass = MagicMock()
    hass.states = _States(states)
    hass.config = SimpleNamespace(
        time_zone="Europe/Zurich", language="en", currency="CHF", country="CH",
        units=SimpleNamespace(temperature_unit="°C"),
    )
    # Must be awaitable: the per-charger loop AWAITS every service call, and
    # a bare MagicMock raises the moment a real charger command is issued.
    hass.services.async_call = AsyncMock()
    return hass


class CycleRig:
    """A real coordinator, real charger devices, and a cycle you can turn.

    ``rig.tick(...)`` runs one whole ``_async_update_data`` against the
    sensor values you give it, on the SAME coordinator each time, and
    records every service call the loop made.
    """

    def __init__(self, config=None, chargers=(), states=None, nights=None):
        cfg = dict(config or {})
        if chargers:
            cfg["ev_chargers"] = [dict(c) for c in chargers]
        self.hass = make_hass(states)
        self.coord = SEMCoordinator(self.hass, cfg)
        self.coord.config_entry = None      # skip the storage restore
        if nights is not None:
            self.coord._battery_night = SimpleNamespace(sealed=lambda: nights)
        for c in chargers:
            self._add_charger(c)
        self.results = []

    def _add_charger(self, c):
        """A REAL ``CurrentControlDevice``, so adapter dispatch is real.

        ``__init__.py`` builds these from discovered hardware, which is the
        one genuinely HA-entangled step in the chain — so the rig does that
        part itself rather than pretending the registry is there."""
        dev = CurrentControlDevice(
            self.hass,
            device_id=c["id"],
            name=c.get("name", c["id"]),
            priority=int(c.get("priority", 3)),
            min_current=float(c.get("ev_min_current", 6)),
            max_current=float(c.get("ev_max_current", 16)),
            phases=int(c.get("ev_phases", 3)),
            voltage=float(c.get("ev_voltage", 230)),
            entity_id=c.get("entity_id"),
            power_entity_id=c.get("ev_power_sensor"),
            current_entity_id=c.get("ev_current_control_entity"),
            charger_service=c.get("charger_service"),
            charger_service_entity_id=c.get("charger_service_entity_id"),
        )
        self.coord._ev_devices[c["id"]] = dev

    @property
    def calls(self):
        """Every ``hass.services.async_call`` the cycles made, oldest first,
        as ``(domain, service, data)``."""
        out = []
        for call in self.hass.services.async_call.await_args_list:
            a, kw = call.args, call.kwargs
            domain = a[0] if len(a) > 0 else kw.get("domain")
            service = a[1] if len(a) > 1 else kw.get("service")
            data = a[2] if len(a) > 2 else kw.get("service_data") or {}
            out.append((domain, service, dict(data or {})))
        return out

    def calls_to(self, service):
        return [c for c in self.calls if c[1] == service]

    def charger_state(self, cid):
        """This charger's DURABLE per-charger state — the object the redirect
        veto strikes against and the phase tick times from. It is created by
        the real ``__init__``; the YAML harness has no such attribute."""
        return (self.coord._pcc_store or {}).get(cid)

    async def tick(self, **sensor_values):
        """One real cycle. Keyword args set entity states first, e.g.
        ``await rig.tick(**{"sensor.grid": -8000})``."""
        for eid, val in sensor_values.items():
            self.hass.states.set(eid.replace("__", "."), val)
        res = await self.coord._async_update_data()
        self.results.append(res)
        return res
