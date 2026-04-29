"""Automatic error and anomaly reporter for SEM.

Captures hard exceptions from the coordinator update loop and runs
periodic self-checks for "soft" anomalies (energy balance drift,
stale sensors, stuck states, repeated update failures, etc.).

Reports are filed as GitHub issues against a configured repository.
Reports are deduplicated by signature and rate-limited to avoid spam.

Off by default. Opt-in via config flow with a fine-grained PAT scoped
to ``issues:write`` on the target repo.
"""
from .reporter import ErrorReporter
from .anomaly_detector import AnomalyDetector, AnomalyCheck, AnomalyResult
from .sanitizer import sanitize_payload, hash_entity_id

__all__ = [
    "ErrorReporter",
    "AnomalyDetector",
    "AnomalyCheck",
    "AnomalyResult",
    "sanitize_payload",
    "hash_entity_id",
]
