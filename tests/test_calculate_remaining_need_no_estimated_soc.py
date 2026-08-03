"""AST lint — ``_calculate_remaining_need`` never reads ``estimated_soc`` (#446).

Pre-#446 the function had a rescue path that pulled the taper detector's
``estimated_soc`` (a.k.a. ``virtual_soc``) into the kWh budget when the
saved ``ev_target_type`` was ``"soc"`` but no real vehicle SOC sensor was
configured. That leak idled the EV on PROD 2026-06-06 against a
fictitious SOC. The fix removed the rescue path; this test pins the
invariant so a future refactor doesn't accidentally reintroduce it.

#708 amendment: the function MAY reach the per-charger taper detector for
exactly ONE method — ``energy_accounted_soc()`` — the measurement-only
session estimate (last real sensor value + measured delivered energy)
that CAPS the stale sensor in the stop decision. That is not the #446
substitution: the virtual SOC's speculative terms (daily driving decay,
temperature correction, self-heal) remain banned, ``get_virtual_soc``
remains banned, and the sensor stays primary (a fresh reading re-anchors
and wins). This lint therefore still bans ``estimated_soc`` /
``get_virtual_soc`` outright, and additionally asserts the ONLY method
ever invoked on a detector-derived name is ``energy_accounted_soc``.
"""
import ast
import pathlib


_BANNED_ATTRS = {"_estimated_soc", "estimated_soc"}
_BANNED_NAMES = {"_estimated_soc", "estimated_soc"}
_BANNED_CALLS = {"get_virtual_soc"}
_DETECTOR_ATTRS = {"_ev_taper_detector", "_ev_taper_detectors"}
_ALLOWED_DETECTOR_METHODS = {"energy_accounted_soc", "get"}


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Could not find function {name!r} in source")


def _load_fn() -> ast.FunctionDef:
    source = (
        pathlib.Path(__file__).parent.parent
        / "coordinator"
        / "coordinator.py"
    )
    assert source.exists(), f"coordinator.py not at expected path: {source}"
    tree = ast.parse(source.read_text())
    return _find_function(tree, "_calculate_remaining_need")


def test_calculate_remaining_need_never_reads_estimated_soc():
    """AST-walk ``_calculate_remaining_need`` and assert no banned name appears."""
    fn = _load_fn()

    for node in ast.walk(fn):
        # ``x.estimated_soc`` or ``x._estimated_soc``
        if isinstance(node, ast.Attribute) and node.attr in _BANNED_ATTRS:
            raise AssertionError(
                f"_calculate_remaining_need reads attribute {node.attr!r} at "
                f"line {node.lineno}. The EV target budget must never read "
                "estimated SOC — it leaks a fictitious SOC into kWh-mode "
                "decisions (#446)."
            )
        # ``estimated_soc`` as a bare name
        if isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            raise AssertionError(
                f"_calculate_remaining_need references name {node.id!r} at "
                f"line {node.lineno}. See #446."
            )
        # ``x.get_virtual_soc(...)``
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _BANNED_CALLS:
                raise AssertionError(
                    f"_calculate_remaining_need calls {func.attr!r} at "
                    f"line {node.lineno}. The taper detector's virtual SOC "
                    "must not enter the budget calculation (#446)."
                )


def test_detector_access_is_energy_accounted_only():
    """#708 — detector access exists solely to call ``energy_accounted_soc``.

    Collects every name bound from ``self._ev_taper_detector[s]`` and
    asserts that any method invoked on such a name (or directly on the
    detector attribute) is in the allowlist. A future edit that pulls
    anything else off the detector — the virtual SOC, taper state,
    session internals — fails here with the #446 history attached.
    """
    fn = _load_fn()

    detector_names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                for sub in ast.walk(node.value):
                    if (isinstance(sub, ast.Attribute)
                            and sub.attr in _DETECTOR_ATTRS):
                        detector_names.add(target.id)

    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        base = func.value
        is_detector_method = (
            (isinstance(base, ast.Name) and base.id in detector_names)
            or (isinstance(base, ast.Attribute) and base.attr in _DETECTOR_ATTRS)
        )
        if is_detector_method and func.attr not in _ALLOWED_DETECTOR_METHODS:
            raise AssertionError(
                f"_calculate_remaining_need calls detector method "
                f"{func.attr!r} at line {node.lineno}. Only "
                f"{sorted(_ALLOWED_DETECTOR_METHODS)} are sanctioned (#708); "
                "everything else on the detector is the speculative surface "
                "#446 banned from budgets."
            )
