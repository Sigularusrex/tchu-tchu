"""Base TchuEvent class for tchu-tchu integration."""

from typing import Optional, Type, Callable, Dict, Any, Union
from abc import ABC, abstractmethod

from tchu_tchu.client import TchuClient
from tchu_tchu.registry import get_registry
from tchu_tchu.serializers.pydantic_serializer import PydanticSerializer
from tchu_tchu.serializers.drf_to_pydantic import convert_drf_to_pydantic
from tchu_tchu.utils.error_handling import SerializationError
from tchu_tchu.logging.handlers import get_logger

logger = get_logger(__name__)

try:
    from rest_framework import serializers as drf_serializers

    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False


class TchuEvent:
    """
    Base class for defining microservice events in tchu-tchu.

    Each event should specify:
    - topic: the routing key/topic string
    - request_serializer_class: DRF serializer for the event request payload
    - response_serializer_class: (optional) DRF serializer for the event response payload (RPC)
    - handler: (optional) function to handle the event when received
    
    For custom context reconstruction (e.g., Django auth, Flask user, etc.):
        TchuEvent.set_context_helper(my_custom_helper)
    
    Or per-instance:
        event = MyEvent(context_helper=my_custom_helper)
    """

    topic: str
    request_serializer_class: Optional[Type] = None
    response_serializer_class: Optional[Type] = None
    handler: Optional[Callable] = None
    validated_data: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None
    
    # Class-level context helper (can be set globally)
    _context_helper: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None
    
    @classmethod
    def set_context_helper(cls, helper: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        """
        Set a global context helper for reconstructing request context from event data.
        
        This allows framework-specific logic (Django auth, Flask user, etc.) to be
        injected without making tchu-tchu dependent on any specific framework.
        
        Args:
            helper: Function that takes event data dict and returns context dict
            
        Example:
            def django_context_helper(event_data):
                user = event_data.get('user')
                company = event_data.get('company')
                # ... reconstruct Django request mock ...
                return {'request': mock_request}
            
            TchuEvent.set_context_helper(django_context_helper)
        """
        cls._context_helper = helper
        logger.info(f"Set global context helper: {helper.__name__}")
    
    @classmethod
    def get_context_helper(cls) -> Optional[Callable[[Dict[str, Any]], Dict[str, Any]]]:
        """Get the current global context helper."""
        return cls._context_helper

    def __init__(
        self,
        topic: Optional[str] = None,
        request_serializer_class: Optional[Type] = None,
        response_serializer_class: Optional[Type] = None,
        handler: Optional[Callable] = None,
        context_helper: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> None:
        """
        Initialize the TchuEvent.

        Args:
            topic: Topic name (uses Meta.topic if not provided)
            request_serializer_class: DRF serializer class for requests
            response_serializer_class: DRF serializer class for responses
            handler: Handler function for this event
            context_helper: Optional context helper function (overrides class-level helper)
        """
        # Get values from Meta class if not provided as arguments
        meta = getattr(self, "Meta", None)
        if meta:
            topic = topic or getattr(meta, "topic", None)
            request_serializer_class = request_serializer_class or getattr(
                meta, "request_serializer_class", None
            )
            response_serializer_class = response_serializer_class or getattr(
                meta, "response_serializer_class", None
            )
            handler = handler or getattr(meta, "handler", None)

        if not topic:
            raise ValueError(
                "Topic must be provided either as argument or in Meta class"
            )

        self.topic = topic
        self.request_serializer_class = request_serializer_class
        self.response_serializer_class = response_serializer_class
        self.handler = handler
        self.validated_data = None
        self.context = None
        
        # Instance-level context helper (overrides class-level)
        self._instance_context_helper = context_helper

        # Create serializers
        self._request_serializer = None
        self._response_serializer = None
        self._client = None

        if self.request_serializer_class and DRF_AVAILABLE:
            try:
                # Convert DRF serializer to Pydantic model
                pydantic_model = convert_drf_to_pydantic(
                    self.request_serializer_class,
                    f"{self.__class__.__name__}RequestModel",
                )
                self._request_serializer = PydanticSerializer(pydantic_model)
            except Exception as e:
                logger.warning(f"Failed to convert request serializer to Pydantic: {e}")
                self._request_serializer = PydanticSerializer()
        else:
            self._request_serializer = PydanticSerializer()

        if self.response_serializer_class and DRF_AVAILABLE:
            try:
                # Convert DRF serializer to Pydantic model
                pydantic_model = convert_drf_to_pydantic(
                    self.response_serializer_class,
                    f"{self.__class__.__name__}ResponseModel",
                )
                self._response_serializer = PydanticSerializer(pydantic_model)
            except Exception as e:
                logger.warning(
                    f"Failed to convert response serializer to Pydantic: {e}"
                )
                self._response_serializer = PydanticSerializer()
        else:
            self._response_serializer = PydanticSerializer()

    @property
    def client(self) -> TchuClient:
        """Get or create TchuClient instance."""
        if self._client is None:
            self._client = TchuClient()
        return self._client

    def subscribe(self) -> str:
        """
        Register the event handler with the message broker.

        Returns:
            Handler ID for unsubscribing

        Raises:
            ValueError: If no handler is defined
        """
        if not self.handler:
            raise ValueError(f"No handler defined for event topic '{self.topic}'")

        # Create wrapper function that handles the event instance
        def event_handler_wrapper(data: Dict[str, Any]) -> Any:
            """Wrapper that creates event instance and calls handler."""
            # Create new event instance
            event_instance = self.__class__()

            # Check if authorization was skipped
            auth_fields = [
                data.get("user"),
                data.get("company"),
                data.get("user_company"),
            ]
            authorization_was_skipped = all(field is None for field in auth_fields)

            try:
                if authorization_was_skipped:
                    # Skip authorization validation
                    event_instance.serialize_request(
                        data,
                        skip_authorization=True,
                        skip_reason="Authorization was skipped in original event",
                    )
                else:
                    # Standard processing with context
                    # Note: You'll need to implement create_request_context_from_event
                    # or adapt this to your context creation logic
                    event_instance.serialize_request(data)

                # Call the original handler
                return self.handler(event_instance)

            except Exception as e:
                logger.error(
                    f"Event handler failed for {self.__class__.__name__}: {e}",
                    exc_info=True,
                )
                raise

        # Register the wrapper function directly with the registry
        handler_name = (
            f"{self.__class__.__name__}_{getattr(self.handler, '__name__', 'handler')}"
        )
        handler_id = f"{self.__class__.__module__}.{self.__class__.__name__}.{getattr(self.handler, '__name__', 'handler')}"

        registry = get_registry()
        return registry.register_handler(
            routing_key=self.topic,
            handler=event_handler_wrapper,
            name=handler_name,
            handler_id=handler_id,
        )

    def serialize_request(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        skip_authorization: bool = False,
        skip_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate and serialize request data.

        Args:
            data: Event data to serialize
            context: Request context for authorization
            skip_authorization: If True, skip authorization validation
            skip_reason: Reason for skipping authorization

        Returns:
            Validated data dictionary
        """
        try:
            # If we have a DRF serializer and context, use the DRF serializer
            # to properly handle HiddenFields with defaults that need context
            if self.request_serializer_class and DRF_AVAILABLE and context:
                # Use the original DRF serializer with context
                serializer_kwargs = {
                    "data": data,
                    "context": context,
                }

                # Pass skip parameters if the serializer supports them
                if skip_authorization:
                    serializer_kwargs["skip_authorization"] = skip_authorization
                    serializer_kwargs["skip_reason"] = skip_reason

                drf_serializer = self.request_serializer_class(**serializer_kwargs)

                if not drf_serializer.is_valid():
                    raise SerializationError(
                        f"DRF serializer validation failed: {drf_serializer.errors}"
                    )

                # Get validated data from DRF serializer
                # This includes the hidden auth fields populated by defaults
                self.validated_data = dict(drf_serializer.validated_data)

            elif self._request_serializer:
                # Use Pydantic serializer (for events without DRF or context)
                if isinstance(data, str):
                    validated_data = self._request_serializer.deserialize(data)
                else:
                    # Serialize then deserialize to validate
                    serialized = self._request_serializer.serialize(data)
                    validated_data = self._request_serializer.deserialize(serialized)

                if hasattr(validated_data, "dict"):
                    # Pydantic model
                    self.validated_data = validated_data.dict()
                else:
                    # Dictionary
                    self.validated_data = validated_data
            else:
                # No serializer, use data as-is
                self.validated_data = data

            self.context = context

            # Log authorization status
            self._log_authorization_status(skip_authorization, skip_reason)

            return self.validated_data

        except Exception as e:
            logger.error(f"Request serialization failed: {e}", exc_info=True)
            raise SerializationError(f"Failed to serialize request: {e}")

    def serialize_response(
        self, data: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Validate and serialize response data.

        Args:
            data: Response data to serialize
            context: Optional context

        Returns:
            Validated response data
        """
        if not self._response_serializer:
            raise NotImplementedError("No response serializer defined for this event")

        try:
            if isinstance(data, str):
                validated_data = self._response_serializer.deserialize(data)
            else:
                # Serialize then deserialize to validate
                serialized = self._response_serializer.serialize(data)
                validated_data = self._response_serializer.deserialize(serialized)

            if hasattr(validated_data, "dict"):
                return validated_data.dict()
            else:
                return validated_data

        except Exception as e:
            logger.error(f"Response serialization failed: {e}", exc_info=True)
            raise SerializationError(f"Failed to serialize response: {e}")

    def publish(self) -> None:
        """
        Validate and publish the event (fire-and-forget).
        """
        if self.validated_data is None:
            raise ValueError(
                "No validated data available. Call serialize_request() first."
            )

        self.client.publish(self.topic, self.validated_data)

    def call(self, timeout: int = 30) -> Any:
        """
        Validate and send the event as an RPC call.

        Args:
            timeout: Timeout in seconds

        Returns:
            Response data
        """
        if self.validated_data is None:
            raise ValueError(
                "No validated data available. Call serialize_request() first."
            )

        response = self.client.call(self.topic, self.validated_data, timeout=timeout)

        if self._response_serializer:
            return self.serialize_response(response)

        return response

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from validated data."""
        if self.validated_data is None:
            raise ValueError(
                "No validated data available. Call serialize_request() first."
            )
        return self.validated_data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Dictionary-style access to validated data."""
        if self.validated_data is None:
            raise ValueError(
                "No validated data available. Call serialize_request() first."
            )
        return self.validated_data[key]

    def __contains__(self, key: str) -> bool:
        """Check if key exists in validated data."""
        if self.validated_data is None:
            return False
        return key in self.validated_data

    @property
    def request_context(self) -> Optional[Dict[str, Any]]:
        """
        Get the request context.
        
        If context was provided during serialization, returns it directly.
        Otherwise, attempts to reconstruct context from validated_data using
        the configured context helper (if available).
        
        Returns:
            Context dictionary or None if no context available
        """
        # If we have explicit context, return it
        if self.context is not None:
            return self.context
        
        # Try to reconstruct from validated_data using helper
        if self.validated_data:
            # Use instance-level helper if provided, otherwise use class-level
            helper = self._instance_context_helper or self._context_helper
            if helper:
                try:
                    return helper(self.validated_data)
                except Exception as e:
                    logger.warning(
                        f"Context helper failed to reconstruct context: {e}. "
                        f"Returning None. Set a valid context helper with "
                        f"TchuEvent.set_context_helper() or pass context_helper to __init__."
                    )
        
        return None

    def is_authorized(self) -> bool:
        """
        Check if the event has valid authorization context.

        Returns:
            True if authorized, False otherwise
        """
        if self.validated_data is None:
            raise ValueError(
                "No validated data available. Call serialize_request() first."
            )

        # Check for authorization fields
        user = self.validated_data.get("user")
        company = self.validated_data.get("company")
        user_company = self.validated_data.get("user_company")

        return all([user is not None, company is not None, user_company is not None])

    def _log_authorization_status(
        self, skip_authorization: bool = False, skip_reason: Optional[str] = None
    ) -> None:
        """Log authorization status for security monitoring."""
        if skip_authorization:
            logger.info(
                f"Event {self.__class__.__name__} topic '{self.topic}' "
                f"processed with intentionally skipped authorization. Reason: {skip_reason}"
            )
        elif self.is_authorized():
            logger.debug(
                f"Event {self.__class__.__name__} topic '{self.topic}' "
                f"processed with valid authorization context."
            )
        else:
            logger.warning(
                f"Event {self.__class__.__name__} topic '{self.topic}' "
                f"processed without authorization data and no skip_authorization flag."
            )

