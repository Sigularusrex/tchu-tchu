"""Pydantic-based serialization for tchu-tchu."""

import json
from typing import Any, Dict, Type, Union, Optional
from pydantic import BaseModel, ValidationError

from tchu_tchu.utils.error_handling import SerializationError
from tchu_tchu.logging.handlers import get_logger

logger = get_logger(__name__)


class PydanticSerializer:
    """
    Pydantic-based serializer for message serialization and deserialization.

    Provides high-performance serialization with type validation and automatic
    conversion between Python objects and JSON.
    """

    def __init__(self, model_class: Optional[Type[BaseModel]] = None) -> None:
        """
        Initialize the serializer.

        Args:
            model_class: Optional Pydantic model class for validation
        """
        self.model_class = model_class

    def serialize(self, data: Union[Dict[str, Any], BaseModel, Any]) -> str:
        """
        Serialize data to JSON string.

        Args:
            data: Data to serialize (dict, Pydantic model, or any JSON-serializable object)

        Returns:
            JSON string representation

        Raises:
            SerializationError: If serialization fails
        """
        try:
            if isinstance(data, BaseModel):
                # Use Pydantic's built-in JSON serialization
                return data.model_dump_json()

            elif self.model_class and isinstance(data, dict):
                # Validate and serialize using the model class
                model_instance = self.model_class(**data)
                return model_instance.model_dump_json()

            else:
                # Fallback to standard JSON serialization
                return json.dumps(data, default=self._json_serializer)

        except (ValidationError, TypeError, ValueError) as e:
            logger.error(f"Serialization failed: {e}", exc_info=True)
            raise SerializationError(f"Failed to serialize data: {e}")

    def deserialize(self, data: Union[str, bytes]) -> Union[Dict[str, Any], BaseModel]:
        """
        Deserialize JSON string to Python object.

        Args:
            data: JSON string or bytes to deserialize

        Returns:
            Deserialized Python object (dict or Pydantic model)

        Raises:
            SerializationError: If deserialization fails
        """
        try:
            if isinstance(data, bytes):
                data = data.decode("utf-8")

            # Parse JSON first
            parsed_data = json.loads(data)

            # If we have a model class, validate and return model instance
            if self.model_class:
                return self.model_class(**parsed_data)

            # Otherwise return the parsed dict
            return parsed_data

        except (json.JSONDecodeError, ValidationError, UnicodeDecodeError) as e:
            logger.error(f"Deserialization failed: {e}", exc_info=True)
            raise SerializationError(f"Failed to deserialize data: {e}")

    def _json_serializer(self, obj: Any) -> Any:
        """
        Custom JSON serializer for non-standard types.

        Handles common Python types that aren't natively JSON serializable.
        """
        # Import here to avoid circular imports
        import uuid
        import datetime
        import decimal

        if isinstance(obj, uuid.UUID):
            return str(obj)
        elif isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
            return obj.isoformat()
        elif isinstance(obj, decimal.Decimal):
            return float(obj)
        elif isinstance(obj, set):
            return list(obj)
        elif isinstance(obj, bytes):
            try:
                return obj.decode("utf-8")
            except UnicodeDecodeError:
                import base64

                return base64.b64encode(obj).decode("ascii")
        elif hasattr(obj, "__dict__"):
            return obj.__dict__

        # Let JSON encoder handle the rest (will raise TypeError if not serializable)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# Global serializer instance for convenience
default_serializer = PydanticSerializer()
