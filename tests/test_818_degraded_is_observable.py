"""#818's resilience must be VISIBLE, not merely effective.

Guido, 30.08, on a PROD feed that logged 28 unavailable episodes in half an
hour: *"it is a known hassle … I want SEM to be able to get along with
conditions like this."* It does — caught live mid-dropout, the reason string
read `inputs degraded (sensor unavailable) — holding 12A` and the car
charged straight through on the held command.

But `inputs_degraded` is computed in the reader, threaded into FleetContext
and consumed by ChargeStability and actuate_battery — and **never
published**. The only way to learn SEM coped was to catch a strategy string
during a 60-second window. An owner of a flaky feed cannot see the thing
that is protecting them, and cannot tell a held cycle from a steered one.

So the flag and its cause are published: whether this cycle was steerable,
and which inputs went dark.
"""
from __future__ import annotations

import inspect


class TestTheFlagIsPublished:
    def test_publish_diag_carries_the_degraded_flag(self):
        from custom_components.solar_energy_management.coordinator import (
            publish_diag,
        )
        src = inspect.getsource(publish_diag)
        assert '"diag_inputs_degraded"' in src, (
            "inputs_degraded gates every write this cycle and is invisible — "
            "publish it beside diag_sensors_unavailable"
        )
        assert '"diag_inputs_dark"' in src, (
            "which inputs went dark is the actionable half: 'solar' names the "
            "modbus, an empty list means the feed was clean"
        )

    def test_the_sensor_exists_for_it(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "sensor.py").read_text()
        assert 'key="diag_inputs_degraded"' in src, (
            "a published key nobody can add to a dashboard is half a fix"
        )


class TestTheReaderStillAnswersBothQuestions:
    def test_the_two_questions_stay_separate(self):
        """#818's design: `inputs_degraded` gates WRITING (any dark read),
        `*_unavailable` gates PUBLISHING (every read dark). Publishing the
        first must not blur it into the second."""
        from custom_components.solar_energy_management.coordinator import (
            sensor_reader,
        )
        src = inspect.getsource(sensor_reader)
        assert "readings.inputs_degraded = any(self._input_dark.values())" in src
        assert 'self._all_dark("solar")' in src
