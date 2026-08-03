"""#640 — legionella timestamp seeds at REGISTRATION (the restore was a no-op)."""
from unittest.mock import MagicMock

from custom_components.solar_energy_management import _seed_legionella_time


def _hw():
    d = MagicMock()
    return d


class TestLegionellaSeed640:
    def test_stored_time_restored(self):
        coord = MagicMock()
        coord._storage.get_legionella_time.return_value = "2026-07-20T12:00:00+00:00"
        hw = _hw()
        _seed_legionella_time(coord, hw)
        ts = hw.record_legionella_cycle.call_args.args[0]
        assert ts.isoformat().startswith("2026-07-20T12:00")   # NOT now

    def test_fresh_install_seeds_now(self):
        coord = MagicMock()
        coord._storage.get_legionella_time.return_value = None
        hw = _hw()
        _seed_legionella_time(coord, hw)
        ts = hw.record_legionella_cycle.call_args.args[0]
        assert ts is not None                                   # seeded, not left None

    def test_unparsable_falls_back_to_now(self):
        coord = MagicMock()
        coord._storage.get_legionella_time.return_value = "garbage"
        hw = _hw()
        _seed_legionella_time(coord, hw)
        hw.record_legionella_cycle.assert_called()

    def test_no_storage_still_seeds(self):
        coord = MagicMock()
        coord._storage = None
        hw = _hw()
        _seed_legionella_time(coord, hw)
        hw.record_legionella_cycle.assert_called()

    def test_dead_firstrefresh_block_removed(self):
        """The parallel-mechanism guard: the old no-op restore must not
        come back beside the registration seed."""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "coordinator" / "coordinator.py").read_text()
        assert 'record_legionella_cycle' not in src, (
            "the first-refresh legionella restore is back — it runs before "
            "the device exists (no-op) and duplicates the registration seed (#640)")
