"""The field list the frontend gets for a flow page, on every HA this suite runs.

HA 2026.10 serializes a step's ``data_schema`` with ``probatio.to_field_list``
(it replaced voluptuous); older cores use ``voluptuous_serialize.convert``.
Both take ``cv.custom_serializer``. Calling the old one on 2026.10 returns
its "unsupported" marker instead of a list (#1298).
"""
from __future__ import annotations

from homeassistant.helpers import config_validation as cv

try:
    import probatio as _serializer

    def _to_field_list(schema):
        return _serializer.to_field_list(
            schema, custom_serializer=cv.custom_serializer)
except ImportError:  # HA before 2026.10
    import voluptuous_serialize as _serializer

    def _to_field_list(schema):
        return _serializer.convert(
            schema, custom_serializer=cv.custom_serializer)


def field_list(schema) -> list[dict]:
    """``schema`` → the frontend's field dicts (name, required, default …)."""
    return _to_field_list(schema)
