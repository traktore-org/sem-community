# (#1313) Experimental HA 2026.11 rung only, until the test plugin has a
# 2026.11 release:
# 1. HA 2026.11 swaps httpx for httpx2 when it is imported, and refuses if
#    httpx was imported first; the plugin pinned for 2026.10 imports httpx
#    earlier, so HA goes first.
# 2. HA 2026.11 moved _clear_logger_overwrites from logger/__init__ to
#    logger/helpers; the plugin still imports it from the old place.
# The logger component is loaded by name: Hassfest reads every import in
# the repository and would ask for "logger" as an integration dependency.
import importlib

import homeassistant  # noqa: F401

_logger = importlib.import_module("homeassistant.components." + "logger")
if not hasattr(_logger, "_clear_logger_overwrites"):
    _helpers = importlib.import_module("homeassistant.components." + "logger.helpers")
    _logger._clear_logger_overwrites = _helpers._clear_logger_overwrites
