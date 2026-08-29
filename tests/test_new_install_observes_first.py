"""A new install starts OBSERVING — it looks before it touches (Guido, 29.08).

The old default was off, reasoning that "a real install actually controls
hardware". Live on PROD 29.08 showed the cost of that reasoning: a fresh
install on a rig wired to a real KEBA silently became a SECOND controller,
fought the production instance's stop for 40 minutes, and put ~5 kWh into a
car whose charge mode was Off. Nobody chose that; an install default did.

Observing first is the honest order of operations. SEM's whole first-run
story is "here is what I found, here is what I would do" — and observer mode
is precisely that sentence in executable form. The user turns actuation on
when the WOULD-decisions look right, which is one switch on the dashboard,
and a decision they made rather than one made for them.

This is a default, not a lock: nothing about the switch, the options flow, or
the actuation path changes.
"""
from __future__ import annotations

from custom_components.solar_energy_management.consts.core import (
    DEFAULT_OBSERVER_MODE,
)
from custom_components.solar_energy_management.persisted_flags import (
    PERSISTED_FLAG_DEFAULTS,
)


def test_the_constant_says_observe():
    assert DEFAULT_OBSERVER_MODE is True, (
        "a fresh install observes until its owner says otherwise"
    )


def test_the_persisted_flag_table_agrees():
    """The table and the constant are two doors to one answer; #777 exists
    because they once disagreed and a restore-store ghost walked through."""
    assert PERSISTED_FLAG_DEFAULTS["observer_mode"] is DEFAULT_OBSERVER_MODE


def test_the_flow_schema_offers_the_same_default():
    """What the install form shows must match what the code assumes — a
    checkbox that says off while the constant says on is the #819 shape."""
    import inspect
    from custom_components.solar_energy_management import config_flow as cf
    src = inspect.getsource(cf)
    marker = 'vol.Optional(\n                    "observer_mode",'
    assert marker in src, "the install step's observer toggle moved — re-pin it"
    tail = src[src.index(marker):src.index(marker) + 260]
    assert "default=DEFAULT_OBSERVER_MODE" in tail, (
        "the form must read the constant, not carry its own literal — that "
        "is how the two drifted in the first place"
    )


def test_actuation_is_still_reachable_in_one_switch():
    """Observing first must not mean 'hard to start': the switch entity is
    the one deliberate action, unchanged."""
    from custom_components.solar_energy_management.persisted_flags import (
        switch_entity_id,
    )
    assert switch_entity_id("observer_mode") == "switch.sem_observer_mode"
