"""(#1054) Static fields a charger's current service needs beside the amps."""
from __future__ import annotations

import json
from typing import Any, Dict


def service_extra_data(raw: Any) -> Dict[str, Any]:
    """The ``ev_charger_service_data`` config value as a dict.

    The crawler stores it as JSON (go-e's ``{"charger_name": "<box>"}``).
    Anything that is not a JSON object is no extra data — never a crash,
    and never a field that would overwrite the amps."""
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            return {}
    return {str(k): v for k, v in data.items()} if isinstance(data, dict) else {}
