"""Constants for SEM Solar Energy Management integration.

Split into domain-specific sub-modules for navigability:
- core: DOMAIN, thresholds, all DEFAULT_* configuration values
- sensors: SEM_SENSORS, SEM_BINARY_SENSORS, sensor definitions
- states: ChargingState, LoadManagementState, STATUS_MESSAGES
- devices: Device discovery patterns, EV charger manufacturers
- labels: Dashboard label definitions, sensor-to-label mapping

All constants are re-exported here for backward compatibility:
    from .consts import DOMAIN, ChargingState, SEM_SENSORS, ...
"""
from .core import *       # noqa: F401,F403
from .sensors import *    # noqa: F401,F403
from .states import *     # noqa: F401,F403
from .devices import *    # noqa: F401,F403
from .labels import *     # noqa: F401,F403
