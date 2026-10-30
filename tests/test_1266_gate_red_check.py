"""#1266 throwaway: fails on Python 3.14 only, to prove the CI gate for
HA 2026.8 goes red while HA 2026.2 stays green. Never merged."""
import sys


def test_fails_only_on_the_2026_8_rung():
    assert sys.version_info < (3, 14), "deliberate failure (#1266 gate check)"
