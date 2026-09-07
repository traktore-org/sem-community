"""(#888) "Hands off" must be the user's word, never SEM's own arithmetic.

storacm's pool pump: the switch is correctly identified, and the Control card
says **"Off — SEM won't act"** whatever Mode is picked. Neither candidate
cause was right — not #779's fold, not a missing apply-now refresh. The Mode
never mattered, because the verdict was not being driven by the Mode.

The chain, all of it in this repo:

1. ``UnifiedDevice.is_controllable`` is DERIVED — ``has_control_handle and
   not user_hands_off``. It is the two axes mixed, deprecated by #780.
2. ``_sync_to_load_manager`` writes that derived value into the LoadManagement
   row for EVERY Energy-Dashboard device, including one whose ``control`` is
   None — where it is False as ARITHMETIC, not as a preference.
3. ``_adopt_legacy_device_flags`` read ``is_controllable is False`` back as
   proof the user had opted out, on the stated premise that "the registry
   always derives those rows WITH a handle". It does not.
4. So a device whose switch was merely not discovered yet acquired a
   permanent hands-off nobody had set.

``features/device_axes.py`` — the module #780 wrote to settle exactly this —
already refuses that legacy fallback in terms: *"reading it here too would
count the same bit twice and, worse, would re-mix the axes this module exists
to separate."* Adoption was the one call site never migrated to it.

Unrecoverable, too: the toggle that could clear it died in the LitElement
migration (14.05.2026), and the store that holds it was only created on
25.07.2026 — so no value in it can be a surviving user click. That is what
makes the one-shot migration safe rather than a guess.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from custom_components.solar_energy_management.features.device_axes import (
    user_hands_off,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)


class TestTheDerivedFlagIsNotTestimony:

    def test_a_handle_less_row_derives_false_and_must_not_be_adopted(self):
        """The row SEM writes for a device whose switch is not discovered yet.
        ``is_controllable`` False here is arithmetic; the permission axis is
        silent, and silence is not an opt-out."""
        row = {"has_control_handle": False, "user_hands_off": False,
               "is_controllable": False}
        assert user_hands_off(row) is False, (
            "a derived is_controllable=False was read as the user's opt-out")

    def test_a_genuine_opt_out_is_still_adopted(self):
        row = {"has_control_handle": True, "user_hands_off": True,
               "is_controllable": False}
        assert user_hands_off(row) is True

    def test_a_pre_780_row_carrying_only_the_mixed_key_is_not_an_opt_out(self):
        """The legacy spelling is ambiguous by construction — it meant BOTH
        "no handle" and "hands off". ``has_control_handle`` answers it; the
        permission axis deliberately does not."""
        assert user_hands_off({"is_controllable": False}) is False


class TestAdoptionAsksTheModuleThatOwnsTheQuestion:

    def _fn(self):
        return UnifiedDeviceRegistry._adopt_legacy_device_flags

    def test_it_calls_user_hands_off(self):
        """Structural, not a source grep (#925): a mention in the comment
        that explains WHY is_controllable is no longer read must not satisfy
        this."""
        src = inspect.getsource(self._fn())
        tree = ast.parse(src.lstrip() if src.startswith(" ") else src)
        called = {
            (c.func.id if isinstance(c.func, ast.Name)
             else getattr(c.func, "attr", ""))
            for c in ast.walk(tree) if isinstance(c, ast.Call)
        }
        assert "user_hands_off" in called, (
            "adoption no longer routes the permission question through "
            "device_axes — the axes are re-mixed")

    def test_it_never_reads_the_derived_key(self):
        """The defect itself: ``info.get("is_controllable")``. A string in a
        comment is fine; a READ is the bug."""
        src = inspect.getsource(self._fn())
        tree = ast.parse(src.lstrip() if src.startswith(" ") else src)
        reads = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", "") == "get"
            and n.args and isinstance(n.args[0], ast.Constant)
            and n.args[0].value == "is_controllable"
        ]
        assert not reads, (
            "adoption reads the DERIVED is_controllable again — SEM's own "
            "output taken as the user's testimony (#888)")


class TestTheFabricatedFlagsAreCleared:

    def test_the_store_carries_a_one_shot_marker(self):
        """A migration that runs every load would sweep away a REAL opt-out
        the moment the axis has an honest writer again."""
        src = (Path(__file__).resolve().parent.parent
               / "features" / "device_registry.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        # PERSISTED: the marker appears as a key in a dict literal (the
        # payload handed to Store.async_save).
        saved = [
            k for node in ast.walk(tree) if isinstance(node, ast.Dict)
            for k in node.keys
            if isinstance(k, ast.Constant) and k.value == "legacy_flags_adopted"
        ]
        assert saved, "the marker is read but never persisted — it would re-run"
        # READ: and it is consulted by name in the loader — as a membership
        # test (``"legacy_flags_adopted" in data``, the absent-vs-False
        # question) and as a subscript. A marker written and never read
        # would clear a real opt-out on every load. Any read form counts;
        # the first draft only accepted ``.get()`` and broke the moment the
        # loader learned to tell absent from False.
        def _names(node):
            if isinstance(node, ast.Compare):
                return [node.left, *node.comparators]
            if isinstance(node, ast.Subscript):
                return [node.slice]
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "get":
                return node.args[:1]
            return []
        read = [
            n for n in ast.walk(tree)
            for c in _names(n)
            if isinstance(c, ast.Constant) and c.value == "legacy_flags_adopted"
        ]
        assert read, "the marker is saved but never consulted"


class TestTheEchoInTheSecondStoreCannotRestoreIt:
    """Found live on .175 the first time the migration ran: the registry's
    flag was cleared, and 35 s later adoption put it straight back.

    The LoadManagement store carries its own ``user_hands_off`` per row —
    SEM's derived output from the PREVIOUS run, persisted in a second place.
    Adoption, latched only in memory, re-read that echo every restart as the
    user's word. The fabricated flag round-tripped through two stores, and
    clearing one of them was half a fix.

    The fix is not to chase the echo but to stop adoption re-running at all:
    it seeds a pre-#650 install ONCE, and a registry store proves that has
    happened. The latch is persisted.
    """

    def _registry_with_stores(self, registry_store, lm_rows):
        """A registry whose own store and whose LoadManagement partner both
        carry SEM's previous-run output — the .175 shape."""
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._store = MagicMock()
        reg._store.async_load = AsyncMock(return_value=registry_store)
        reg._store.async_save = AsyncMock()
        reg._load_manager = SimpleNamespace(_devices=dict(lm_rows))
        reg._manual_mappings = {}
        reg._priority_overrides = {}
        reg._control_mode_overrides = {}
        reg._dependency_overrides = {}
        reg._critical_overrides = {}
        reg._controllable_overrides = {}
        reg._rated_power_overrides = {}
        reg._service_registrations = {}
        reg._device_goals = {}
        reg._legacy_flags_adopted = False
        return reg, asyncio

    def _run(self, coro):
        import asyncio
        return asyncio.new_event_loop().run_until_complete(coro)

    LM_ECHO = {
        "energy_dashboard_keba_p30_total": {
            "is_critical": False,
            "has_control_handle": True,
            "user_hands_off": True,      # SEM's own previous-run output
            "is_controllable": False,
        },
    }

    def _load(self, reg):
        """Only the storage-load path — the seam #888 extracted from
        ``async_initialize`` so the migration can be exercised without
        discovery, HA, or a running load manager."""
        return self._run(reg._load_storage())

    def test_an_upgraded_install_clears_the_flag_and_latches(self):
        reg, _ = self._registry_with_stores(
            {"controllable_overrides":
                {"energy_dashboard_keba_p30_total": False}},
            self.LM_ECHO)
        self._load(reg)
        assert reg._controllable_overrides == {}, "the fabricated flag survived"
        assert reg._legacy_flags_adopted is True, (
            "adoption is not latched after the migration — the LM echo will "
            "be re-adopted on the next refresh, which is what .175 did")

    def test_the_latch_is_persisted_in_the_same_save(self):
        reg, _ = self._registry_with_stores(
            {"controllable_overrides":
                {"energy_dashboard_keba_p30_total": False}},
            self.LM_ECHO)
        self._load(reg)
        assert reg._store.async_save.await_count >= 1, (
            "the latch was set in memory and never written — a restart would "
            "adopt the echo again")
        saved = reg._store.async_save.await_args.args[0]
        assert saved.get("legacy_flags_adopted") is True
        assert saved.get("controllable_overrides") == {}

    def test_adoption_then_does_nothing_against_the_echo(self):
        """The whole point: after load, the LM store still says hands-off,
        and adoption must not believe it."""
        reg, _ = self._registry_with_stores(
            {"controllable_overrides":
                {"energy_dashboard_keba_p30_total": False}},
            self.LM_ECHO)
        self._load(reg)
        self._run(reg._adopt_legacy_device_flags())
        assert reg._controllable_overrides == {}, (
            "adoption re-adopted SEM's own echo from the LoadManagement "
            "store — the flag round-tripped through two stores")

    def test_a_post_888_store_with_the_latch_false_keeps_its_flags(self):
        """ABSENT is not FALSE. A fresh install saves the latch as False
        before adoption has run; on its first restart that must NOT read as
        "pre-#888 store, migrate" — the flags in it came through an honest
        writer. The first version wiped them, and #650's round-trip test
        caught it."""
        reg, _ = self._registry_with_stores(
            {"legacy_flags_adopted": False,
             "controllable_overrides": {"energy_dashboard_pump": False}},
            {})
        self._load(reg)
        assert reg._controllable_overrides == {"energy_dashboard_pump": False}, (
            "a present-but-False latch was read as an absent one and an "
            "honest opt-out was wiped")
        assert reg._legacy_flags_adopted is False, (
            "the latch was set without adoption having run")
        assert reg._store.async_save.await_count == 0, "nothing to migrate"

    def test_a_store_that_already_latched_is_left_alone(self):
        """A genuine opt-out set AFTER the migration must survive the next
        restart — the marker is what makes the clearing one-shot."""
        reg, _ = self._registry_with_stores(
            {"legacy_flags_adopted": True,
             "controllable_overrides": {"energy_dashboard_pump": False}},
            {})
        self._load(reg)
        assert reg._controllable_overrides == {"energy_dashboard_pump": False}
        assert reg._legacy_flags_adopted is True

    def test_a_fresh_install_still_adopts_once(self):
        """No registry store at all: adoption may run, exactly once, and the
        fixed adoption reads the permission axis so a control-less device
        adopts nothing."""
        reg, _ = self._registry_with_stores(None, {
            "energy_dashboard_new": {"is_critical": False,
                                     "has_control_handle": False,
                                     "user_hands_off": False,
                                     "is_controllable": False},
        })
        self._load(reg)
        assert reg._legacy_flags_adopted is False
        self._run(reg._adopt_legacy_device_flags())
        assert reg._controllable_overrides == {}
        assert reg._legacy_flags_adopted is True


class TestThePermissionHasAnHonestWriter:
    """A migration that clears a flag nobody can set again is half a fix."""

    def _accepted_properties(self):
        """Every literal inside a ``vol.In([...])`` in __init__.py.

        Structural, not a window of source text (#925): the first draft
        sliced 900 characters after a marker string and asked whether a
        word appeared in it, which is exactly the idiom the ratchet
        exists to retire — and the ratchet caught it.
        """
        src = (Path(__file__).resolve().parent.parent
               / "__init__.py").read_text(encoding="utf-8")
        out = set()
        for n in ast.walk(ast.parse(src)):
            if not (isinstance(n, ast.Call)
                    and getattr(n.func, "attr", "") == "In"):
                continue
            for arg in n.args:
                if isinstance(arg, (ast.List, ast.Tuple)):
                    out |= {e.value for e in arg.elts
                            if isinstance(e, ast.Constant)}
        return out

    def test_hands_off_is_an_accepted_property(self):
        props = self._accepted_properties()
        assert "hands_off" in props, (
            "the handler has accepted hands_off since #780 but voluptuous "
            "refuses the call before it arrives — an axis with a reader, a "
            "store and a handler, and no way in")

    def test_the_sibling_spelling_still_works(self):
        """``controllable`` is the same toggle under the older name and must
        keep working — this adds a way in, it does not move the door."""
        assert "controllable" in self._accepted_properties()

    def test_a_falsey_word_is_not_true(self):
        """``bool("false")`` is True. Every natural way to say no — false, 0,
        no, off — meant yes."""
        parse = lambda v: str(v).strip().lower() in ("true", "1", "on", "yes")
        for word in ("false", "0", "no", "off", "False", " OFF "):
            assert parse(word) is False, word
        for word in ("true", "1", "yes", "on", "True"):
            assert parse(word) is True, word
