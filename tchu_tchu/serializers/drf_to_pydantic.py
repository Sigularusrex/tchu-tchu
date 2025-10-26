"""Utilities for converting Django REST Framework serializers to Pydantic models."""

from typing import Any, Dict, Type, Optional, get_type_hints
from pydantic import BaseModel, Field, create_model

from tchu_tchu.utils.error_handling import SerializationError
from tchu_tchu.logging.handlers import get_logger

logger = get_logger(__name__)

try:
    from rest_framework import serializers as drf_serializers

    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    logger.warning(
        "Django REST Framework not available. DRF conversion features disabled."
    )


def convert_drf_to_pydantic(
    serializer_class: Type, model_name: Optional[str] = None
) -> Type[BaseModel]:
    """
    Convert a Django REST Framework serializer to a Pydantic model.

    Args:
        serializer_class: DRF serializer class to convert
        model_name: Optional name for the generated Pydantic model

    Returns:
        Generated Pydantic model class

    Raises:
        SerializationError: If conversion fails or DRF is not available
    """
    if not DRF_AVAILABLE:
        raise SerializationError("Django REST Framework is required for DRF conversion")

    if model_name is None:
        model_name = f"{serializer_class.__name__}Model"

    try:
        # Create an instance to inspect fields with safe context
        # Provide empty context to avoid issues with fields that expect request
        serializer_instance = serializer_class(context={})

        # Build field definitions for Pydantic
        field_definitions: Dict[str, Any] = {}

        for field_name, field_instance in serializer_instance.fields.items():
            pydantic_field = _convert_drf_field_to_pydantic(field_instance)
            field_definitions[field_name] = pydantic_field

        # Create the Pydantic model
        pydantic_model = create_model(model_name, **field_definitions)

        logger.info(
            f"Successfully converted DRF serializer {serializer_class.__name__} to Pydantic model {model_name}"
        )
        return pydantic_model

    except Exception as e:
        logger.error(
            f"Failed to convert DRF serializer {serializer_class.__name__}: {e}",
            exc_info=True,
        )
        raise SerializationError(f"Failed to convert DRF serializer: {e}")


def _convert_drf_field_to_pydantic(field_instance: Any) -> tuple:
    """
    Convert a single DRF field to Pydantic field definition.

    Args:
        field_instance: DRF field instance

    Returns:
        Tuple of (type, Field()) for Pydantic model creation
    """
    if not DRF_AVAILABLE:
        return (Any, Field())

    # Default values
    field_type = Any
    field_kwargs = {}

    # Handle required/optional
    if not field_instance.required:
        if field_instance.default != drf_serializers.empty:
            # Check if default is callable - if so, we can't evaluate it safely
            # in this context (might require request context)
            if callable(field_instance.default):
                # Use None as default for callable defaults to avoid context issues
                field_kwargs["default"] = None
            else:
                field_kwargs["default"] = field_instance.default
        else:
            field_kwargs["default"] = None

    # Add description if available
    if hasattr(field_instance, "help_text") and field_instance.help_text:
        field_kwargs["description"] = field_instance.help_text

    # Map DRF field types to Python types
    if isinstance(field_instance, drf_serializers.CharField):
        field_type = str
        if hasattr(field_instance, "max_length") and field_instance.max_length:
            field_kwargs["max_length"] = field_instance.max_length

    elif isinstance(field_instance, drf_serializers.IntegerField):
        field_type = int

    elif isinstance(field_instance, drf_serializers.FloatField):
        field_type = float

    elif isinstance(field_instance, drf_serializers.BooleanField):
        field_type = bool

    elif isinstance(field_instance, drf_serializers.DateTimeField):
        from datetime import datetime

        field_type = datetime

    elif isinstance(field_instance, drf_serializers.DateField):
        from datetime import date

        field_type = date

    elif isinstance(field_instance, drf_serializers.TimeField):
        from datetime import time

        field_type = time

    elif isinstance(field_instance, drf_serializers.UUIDField):
        from uuid import UUID

        field_type = UUID

    elif isinstance(field_instance, drf_serializers.EmailField):
        from pydantic import EmailStr

        field_type = EmailStr

    elif isinstance(field_instance, drf_serializers.URLField):
        from pydantic import HttpUrl

        field_type = HttpUrl

    elif isinstance(field_instance, drf_serializers.JSONField):
        # Use Dict and Any from module-level imports
        field_type = Dict[str, Any]

    elif isinstance(field_instance, drf_serializers.ListField):
        from typing import List

        # Try to determine child type
        if hasattr(field_instance, "child") and field_instance.child:
            child_type, _ = _convert_drf_field_to_pydantic(field_instance.child)
            field_type = List[child_type]
        else:
            # Use Any from module-level imports
            field_type = List[Any]

    elif isinstance(field_instance, drf_serializers.DictField):
        from typing import Dict

        # Use Any from module-level imports
        field_type = Dict[str, Any]

    elif isinstance(field_instance, drf_serializers.DecimalField):
        from decimal import Decimal

        field_type = Decimal

    # Handle nested serializers
    elif isinstance(field_instance, drf_serializers.Serializer):
        # Recursively convert nested serializer
        nested_model = convert_drf_to_pydantic(
            field_instance.__class__, f"{field_instance.__class__.__name__}Nested"
        )
        field_type = nested_model

    # Make optional if not required
    if not field_instance.required:
        from typing import Optional

        field_type = Optional[field_type]

    return (field_type, Field(**field_kwargs))


def create_pydantic_from_drf_data(
    serializer_class: Type, data: Dict[str, Any], model_name: Optional[str] = None
) -> BaseModel:
    """
    Create a Pydantic model instance from DRF serializer class and data.

    Args:
        serializer_class: DRF serializer class
        data: Data to validate and convert
        model_name: Optional name for the generated model

    Returns:
        Pydantic model instance

    Raises:
        SerializationError: If conversion or validation fails
    """
    pydantic_model = convert_drf_to_pydantic(serializer_class, model_name)

    try:
        return pydantic_model(**data)
    except Exception as e:
        raise SerializationError(f"Failed to create Pydantic model from data: {e}")
