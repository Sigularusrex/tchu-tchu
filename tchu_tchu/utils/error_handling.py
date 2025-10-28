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


class TchuRPCException(TchuError):
    """
    Base exception for RPC handler errors that return responses instead of raising.

    When raised in an RPC handler, this exception is caught and converted
    to a response dict that's sent back to the caller (not an exception).

    Standard Usage:
        raise TchuRPCException(
            message="User not found",
            code="USER_NOT_FOUND",
            details={"user_id": 123}
        )
        # Returns: {"success": False, "error_message": "...", "error_code": "...", "error_details": {...}}

    Custom Usage - Override to_response_dict():
        class PaymentException(TchuRPCException):
            def __init__(self, payment_id: str, error_type: str, message: str):
                self.payment_id = payment_id
                self.error_type = error_type
                super().__init__(message=message, code=error_type)

            def to_response_dict(self) -> dict:
                return {
                    "payment_id": self.payment_id,
                    "error_type": self.error_type,
                    "message": self.message
                }
    """

    def __init__(
        self, message: str, code: str = "RPC_ERROR", details: Optional[dict] = None
    ):
        """
        Initialize the RPC exception.

        Args:
            message: Human-readable error message
            code: Error code for programmatic handling
            details: Optional additional error details
        """
        super().__init__(message, details)
        self.code = code

    def to_response_dict(self) -> dict:
        """
        Convert exception to a response dictionary.
        Override this method to customize the response format.

        Returns:
            dict: Error response (sent to RPC caller)
        """
        return {
            "success": False,
            "error_message": self.message,
            "error_code": self.code,
            "error_details": self.details,
        }
