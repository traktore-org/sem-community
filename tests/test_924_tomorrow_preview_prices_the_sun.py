"""(#924) Tomorrow's provisional plan is packed against a PRICED sun.

``_compose_tomorrow_preview`` does not merely draw windows: it builds a
real ledger and runs the real ``pack_night``. It was doing that over day
slots built with no ``export_rate``, so every surplus hour priced at 0
and the packer preferred the sun BY FIAT — the exact behaviour #755
removed from the stamped plan, alive on the preview beside it.

The user-visible shape of that: the Tomorrow card shows a plan the night
does not execute. Same forecast, same tariff, same battery, two answers,
because one of the two was told the sun costs nothing.

The discriminating case is a feed-in tariff worth MORE than the day's
grid price. Then self-consuming a sunny kWh is the expensive choice and
a correct packer moves the load off it. Unpriced, it cannot: 0 beats
every tariff, so the packing at a rich feed-in was byte-identical to the
packing at no feed-in at all. That equality is the bug, and this is the
test that fails on it.
"""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _DayCapableTime,
    _fake_load,
    _fake_self,
    _power,
    freeze_targets,
)

# The fake tariff prices the day at 0.28 and 02:00-04:00 at 0.10.
DAY_PRICE = 0.28


def _preview_at(export_rate):
    fake = _fake_self(devices=[_fake_load()])
    fake.time_manager = _DayCapableTime()
    fake._forecast_reader = SimpleNamespace(
        forecast_data=SimpleNamespace(forecast_tomorrow_kwh=41.0))
    fake.config["electricity_export_rate"] = export_rate
    p = SEMCoordinator._compose_tomorrow_preview(fake, power=_power())
    assert p is not None, "no preview to judge"
    prov = p.get("provisional")
    assert prov is not None, (
        "the provisional plan is what packs — without it this test proves "
        "nothing about pricing")
    return prov


def _windows(prov):
    return sorted((b["start"][11:16], b["end"][11:16]) for b in prov["blocks"])


class TestTomorrowsPreviewPricesTheSun:

    def test_a_feed_in_richer_than_the_grid_moves_the_load_off_the_sun(
            self, freeze_targets):
        """At 0.50/kWh export against a 0.28/kWh day, consuming a sunny kWh
        costs more than buying one. The packer must say so."""
        free = _windows(_preview_at(0.0))
        rich = _windows(_preview_at(DAY_PRICE + 0.22))
        assert rich != free, (
            "tomorrow's provisional plan packs identically whether the sun "
            "is worth nothing or worth more than grid power — the surplus "
            "slots are being priced at 0, which is #755's defect on the "
            f"preview path (#924). blocks={free}")

    def test_the_ordinary_feed_in_still_prefers_the_sun(self, freeze_targets):
        """The fix is a price, not a thumb on the other side of the scale.
        Below the day tariff the sun is still the cheapest hour and the
        plan is unchanged — which is why this was invisible for a month."""
        assert _windows(_preview_at(0.075)) == _windows(_preview_at(0.0))

    def test_the_preview_reads_the_one_feed_in_accessor(self, freeze_targets):
        """(#924) A preview that fetched its own rate could drift from the
        plan's again. It asks the coordinator's single reader."""
        import inspect
        src = inspect.getsource(SEMCoordinator._compose_tomorrow_preview)
        assert src.count("export_rate=self._configured_export_rate()") == 2, (
            "both the window build and the provisional packing inside "
            "_compose_tomorrow_preview must price from the one accessor")
