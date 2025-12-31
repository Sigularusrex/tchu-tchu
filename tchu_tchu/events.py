"""Base TchuEvent class for tchu-tchu integration."""

import importlib.util
from typing import Optional, Type, Callable, Dict, Any

from tchu_tchu.client import TchuClient
from tchu_tchu.registry import get_registry
from tchu_tchu.utils.json_encoder import loads_message
from tchu_tchu.utils.error_handling import SerializationError, TchuRPCException
from tchu_tchu.logging.handlers import get_logger

logger = get_logger(__name__)

# Check if Django REST Framework is available
DRF_AVAILABLE = importlib.util.find_spec("rest_framework") is not None


class TchuEvent:
    """
    Base class for defining microservice events in tchu-tchu.

    Each event should specify:
    - topic: the routing key/topic string
    - request_serializer_class: DRF serializer for the event request payload
    - response_serializer_class: (optional) DRF serializer for the event response payload (RPC)
    - handler: (optional) function to handle the event when received
    - celery_options: (optional) Celery task options like retry settings

    For custom context reconstruction (e.g., Django auth, Flask user, etc.):
        TchuEvent.set_context_helper(my_custom_helper)

    Or per-instance:
        event = MyEvent(context_helper=my_custom_helper)

    Celery retry configuration:
        event = MyEvent(
            handler=my_handler,
            celery_options={
                "autoretry_for": (ConnectionError, TimeoutError),
                "max_retries": 3,
                "countdown": 60,  # Optional: delay between retries in seconds
            }
        )

    Note: For advanced retry options like exponential backoff (retry_backoff, retry_jitter),
    configure them at the Celery app level since they're task decorator options.
    """

    topic: str
    request_serializer_class: Optional[Type] = None
    response_serializer_class: Optional[Type] = None
    handler: Optional[Callable] = None
    validated_data: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None
    celery_options: Optional[Dict[str, Any]] = None

    # Class-level context helper (can be set globally)
    _context_helper: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None

    @classmethod
    def set_context_helper(
        cls, helper: Callable[[Dict[str, Any]], Dict[str, Any]]
    ) -> None:
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
        error_serializer_class: Optional[Type] = None,
        handler: Optional[Callable] = None,
        context_helper: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        celery_options: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize the TchuEvent.

        Args:
            topic: Topic name (uses Meta.topic if not provided)
            request_serializer_class: DRF serializer class for requests
            response_serializer_class: DRF serializer class for responses (success cases)
            error_serializer_class: DRF serializer class for error responses (TchuRPCException)
            handler: Handler function for this event
            context_helper: Optional context helper function (overrides class-level helper)
            celery_options: Optional Celery task options for retry configuration.
                Supported options:
                - autoretry_for: Tuple of exception classes to auto-retry on
                - max_retries: Maximum number of retry attempts (default: 3)
                - countdown: Delay between retries in seconds (optional)
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
            error_serializer_class = error_serializer_class or getattr(
                meta, "error_serializer_class", None
            )
            handler = handler or getattr(meta, "handler", None)
            celery_options = celery_options or getattr(meta, "celery_options", None)

        if not topic:
            raise ValueError(
                "Topic must be provided either as argument or in Meta class"
            )

        self.topic = topic
        self.request_serializer_class = request_serializer_class
        self.response_serializer_class = response_serializer_class
        self.error_serializer_class = error_serializer_class
        self.handler = handler
        self.celery_options = celery_options
        self.validated_data = None
        self.context = None

        # Instance-level context helper (overrides class-level)
        self._instance_context_helper = context_helper

        # Store reference to client
        self._client = None

    @property
    def client(self) -> TchuClient:
        """Get or create TchuClient instance."""
        if self._client is None:
            self._client = TchuClient()
        return self._client

    def subscribe(self) -> str:
        """
        Register the event handler with the message broker.

        The handler receives a TchuEvent instance with validated_data populated.

        ALL handlers are created as Celery tasks at subscribe time (import time).
        For broadcast messages, handlers are dispatched via .delay() for async execution.
        For RPC messages, handlers are called directly to return results.

        For native Celery retry support, pass celery_options:

        ```python
        MyEvent(
            handler=my_handler,
            celery_options={
                "autoretry_for": (ConnectionError, TimeoutError),
                "retry_backoff": True,
                "retry_backoff_max": 600,
                "retry_jitter": True,
                "max_retries": 5,
            }
        ).subscribe()
        ```

        tchu-tchu internally creates a Celery task with these native options.
        Your consuming app never needs to import Celery directly!

        Returns:
            Handler ID for unsubscribing

        Raises:
            ValueError: If no handler is defined
        """
        if not self.handler:
            raise ValueError(f"No handler defined for event topic '{self.topic}'")

        # Import shared_task here to create Celery task at subscribe time (import time)
        from celery import shared_task

        # Capture references for the closure
        event_class = self.__class__
        original_handler = self.handler
        context_helper = self._instance_context_helper or self._context_helper

        # Build handler identifiers
        handler_name = (
            f"{event_class.__name__}_{getattr(original_handler, '__name__', 'handler')}"
        )
        handler_id = f"{event_class.__module__}.{event_class.__name__}.{getattr(original_handler, '__name__', 'handler')}"

        # Build Celery task options
        task_options = {
            "name": f"tchu_tchu.handler.{handler_id}",
        }

        # Add celery_options if provided (retries, rate limits, etc.)
        if self.celery_options:
            task_options.update(self.celery_options)

        # Create the Celery task with TchuEvent wrapper logic included
        @shared_task(**task_options)
        def celery_task_handler(data: Dict[str, Any]) -> Any:
            """Celery task that wraps handler with TchuEvent logic."""
            # Remove _tchu_meta before processing
            clean_data = {k: v for k, v in data.items() if k != "_tchu_meta"}

            # Create new event instance
            event_instance = event_class()

            # Check if authorization was skipped
            auth_fields = [
                clean_data.get("user"),
                clean_data.get("company"),
                clean_data.get("user_company"),
            ]
            authorization_was_skipped = all(field is None for field in auth_fields)

            try:
                if authorization_was_skipped:
                    # Skip authorization validation
                    event_instance.serialize_request(
                        clean_data,
                        skip_authorization=True,
                        skip_reason="Authorization was skipped in original event",
                    )
                else:
                    # Reconstruct context from event data using context helper
                    context = None
                    if context_helper:
                        try:
                            context = context_helper(clean_data)
                        except Exception as ctx_err:
                            logger.warning(
                                f"Context helper failed: {ctx_err}. Processing without context."
                            )

                    # Serialize with reconstructed context
                    event_instance.serialize_request(clean_data, context=context)

                # Call the original handler with TchuEvent instance
                return original_handler(event_instance)

            except TchuRPCException as e:
                # Convert to response dict
                error_response = e.to_response_dict()
                logger.warning(
                    f"RPC error: {e.message} ({e.code})",
                    extra={"topic": event_class.topic, "error_code": e.code},
                )

                # Validate with error_serializer if defined
                if event_instance.error_serializer_class and DRF_AVAILABLE:
                    try:
                        error_serializer = event_instance.error_serializer_class(
                            data=error_response
                        )
                        if error_serializer.is_valid():
                            return dict(error_serializer.validated_data)
                        else:
                            logger.error(
                                f"Error response validation failed: {error_serializer.errors}"
                            )
                    except Exception as validation_err:
                        logger.error(f"Error serializer failed: {validation_err}")

                return error_response

            except Exception as e:
                logger.error(
                    f"Event handler failed for {event_class.__name__}: {e}",
                    exc_info=True,
                )
                raise

        # Build metadata
        metadata = {
            "celery_options": self.celery_options,
        }

        # Register the Celery task with the registry
        registry = get_registry()
        registered_id = registry.register_handler(
            routing_key=self.topic,
            handler=celery_task_handler,  # Register the Celery task, not raw function
            name=handler_name,
            handler_id=handler_id,
            metadata=metadata,
        )

        logger.info(
            f"Registered Celery task handler '{handler_name}' for topic '{self.topic}'"
            + (
                f" with celery_options: {list(self.celery_options.keys())}"
                if self.celery_options
                else ""
            ),
            extra={"routing_key": self.topic, "handler_id": handler_id},
        )

        return registered_id

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
            # If we have a DRF serializer, use it for validation
            if self.request_serializer_class and DRF_AVAILABLE:
                # Use the original DRF serializer with context
                serializer_kwargs = {
                    "data": data,
                }

                if context:
                    serializer_kwargs["context"] = context

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

            else:
                # No serializer, use data as-is
                # Handle both dict and JSON string input
                if isinstance(data, str):
                    self.validated_data = loads_message(data)
                else:
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
        if not self.response_serializer_class:
            # If no response serializer, just return data as-is
            return data

        try:
            # If we have a DRF serializer, use it for validation
            if self.response_serializer_class and DRF_AVAILABLE:
                serializer_kwargs = {
                    "data": data,
                }

                if context:
                    serializer_kwargs["context"] = context

                drf_serializer = self.response_serializer_class(**serializer_kwargs)

                if not drf_serializer.is_valid():
                    raise SerializationError(
                        f"DRF serializer validation failed: {drf_serializer.errors}"
                    )

                return dict(drf_serializer.validated_data)

            else:
                # No serializer, handle both dict and JSON string input
                if isinstance(data, str):
                    return loads_message(data)
                else:
                    return data

        except Exception as e:
            logger.error(f"Response serialization failed: {e}", exc_info=True)
            raise SerializationError(f"Failed to serialize response: {e}")

    def serialize_error(
        self, data: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Validate and serialize error response data.

        Args:
            data: Error response data to serialize (from TchuRPCException)
            context: Optional context

        Returns:
            Validated error response data
        """
        if not self.error_serializer_class:
            # If no error serializer, just return data as-is
            return data

        try:
            # If we have a DRF serializer, use it for validation
            if self.error_serializer_class and DRF_AVAILABLE:
                serializer_kwargs = {
                    "data": data,
                }

                if context:
                    serializer_kwargs["context"] = context

                drf_serializer = self.error_serializer_class(**serializer_kwargs)

                if not drf_serializer.is_valid():
                    raise SerializationError(
                        f"DRF error serializer validation failed: {drf_serializer.errors}"
                    )

                return dict(drf_serializer.validated_data)

            else:
                # No serializer, handle both dict and JSON string input
                if isinstance(data, str):
                    return loads_message(data)
                else:
                    return data

        except Exception as e:
            logger.error(f"Error response serialization failed: {e}", exc_info=True)
            raise SerializationError(f"Failed to serialize error response: {e}")

    def publish(self) -> None:
        """
        Validate and publish the event (fire-and-forget).
        """
        if self.validated_data is None:
            raise ValueError(
                "No validated data available. Call serialize_request() first."
            )

        self.client.publish(self.topic, self.validated_data)

    def call(self, timeout: int = 30, allow_join: bool = False) -> Any:
        """
        Validate and send the event as an RPC call.

        Args:
            timeout: Timeout in seconds
            allow_join: Allow calling result.get() from within a task (default: False)

        Returns:
            Response data
        """
        if self.validated_data is None:
            raise ValueError(
                "No validated data available. Call serialize_request() first."
            )

        response = self.client.call(
            self.topic, self.validated_data, timeout=timeout, allow_join=allow_join
        )

        # Detect error responses (from TchuRPCException)
        is_error = isinstance(response, dict) and response.get("error_code") is not None

        # Route to appropriate serializer
        if is_error and self.error_serializer_class:
            # Validate error response
            try:
                validated_response = self.serialize_error(response)
                logger.debug(f"RPC error validated for {self.topic}")
                return validated_response
            except SerializationError as e:
                logger.error(
                    f"Error response validation failed for {self.topic}: {e}. "
                    f"Handler returned: {response}",
                    exc_info=True,
                )
                raise

        elif self.response_serializer_class:
            # Validate success response
            try:
                validated_response = self.serialize_response(response)
                logger.debug(f"RPC response validated for {self.topic}")
                return validated_response
            except SerializationError as e:
                logger.error(
                    f"Response validation failed for {self.topic}: {e}. "
                    f"Handler returned: {response}",
                    exc_info=True,
                )
                raise

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
