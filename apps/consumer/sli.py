"""Timestamp validation for message-path latency; no Kafka/Vault dependencies."""
from datetime import datetime, timezone


def message_age_seconds(timestamp, now=None):
    """Return elapsed seconds for an aware producer timestamp.

    Missing/naive/future timestamps cannot produce a trustworthy latency sample.
    Callers must count these separately without changing message delivery.
    """
    if not isinstance(timestamp, str):
        raise ValueError("Missing or invalid producer timestamp")
    started = datetime.fromisoformat(timestamp)
    if started.utcoffset() is None:
        raise ValueError("Producer timestamp must include a timezone")
    finished = now if now is not None else datetime.now(timezone.utc)
    seconds = (finished - started).total_seconds()
    if seconds < 0:
        raise ValueError("Producer timestamp is in the future; check clock sync")
    return seconds
