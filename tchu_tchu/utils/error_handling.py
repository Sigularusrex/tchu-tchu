"""Error handling utilities for tchu-tchu."""

from typing import Optional


class TchuError(Exception):
    """Base exception class for all tchu-tchu errors."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConnectionError(TchuError):
    """Raised when there's an issue with Celery broker connection."""

    pass


class SerializationError(TchuError):
    """Raised when there's an issue with message serialization/deserialization."""

    pass


class SubscriptionError(TchuError):
    """Raised when there's an issue with topic subscription."""

    pass


class PublishError(TchuError):
    """Raised when there's an issue publishing a message."""

    pass


class TimeoutError(TchuError):
    """Raised when an RPC call times out."""

    pass
