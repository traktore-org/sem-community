# (#1313) Experimental HA 2026.11 rung only, until the test plugin has a
# 2026.11 release:
# 1. HA 2026.11 swaps httpx for httpx2 when it is imported, and refuses if
#    httpx was imported first; the plugin pinned for 2026.10 imports httpx
#    earlier, so HA goes first.
# 2. HA 2026.11 moved _clear_logger_overwrites from logger/__init__ to
#    logger/helpers; the plugin still imports it from the old place.
import homeassistant  # noqa: F401
import homeassistant.components.logger as _logger
if not hasattr(_logger, "_clear_logger_overwrites"):
    from homeassistant.components.logger.helpers import _clear_logger_overwrites
    _logger._clear_logger_overwrites = _clear_logger_overwrites
