"""Subscribe to topics and handle messages with Celery integration."""

import json
from typing import Callable, Optional, Any, Dict
from functools import wraps

from tchu_tchu.registry import get_registry
from tchu_tchu.utils.json_encoder import loads_message
from tchu_tchu.logging.handlers import (
    get_logger,
    log_message_received,
    log_handler_executed,
    log_error,
)

logger = get_logger(__name__)

# Cache for dynamically created Celery tasks
_dynamic_tasks: Dict[str, Any] = {}


def subscribe(
    routing_key: str,
    *,
    name: Optional[str] = None,
    handler_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    celery_options: Optional[Dict[str, Any]] = None,
) -> Callable:
    """
    Decorator to subscribe a function to a topic routing key.

    With the new broadcast architecture, handlers are registered locally
    and executed when messages arrive at the app's queue.

    Args:
        routing_key: Topic routing key pattern (e.g., 'user.created', 'order.*')
        name: Optional human-readable name for the handler
        handler_id: Optional unique ID for the handler
        metadata: Optional metadata dictionary
        celery_options: Optional Celery task options for native retry support.
            Supported options (passed directly to Celery task decorator):
            - bind: bool - Bind task to self (default: True for retry support)
            - autoretry_for: tuple - Exception classes to auto-retry on
            - retry_backoff: bool/int - Enable exponential backoff
            - retry_backoff_max: int - Maximum backoff time in seconds
            - retry_jitter: bool - Add randomness to backoff
            - max_retries: int - Maximum retry attempts
            - default_retry_delay: int - Default delay between retries

    Returns:
        Decorated function

    Example (with native Celery retry):
        @subscribe(
            'data.process',
            celery_options={
                "autoretry_for": (ConnectionError, TimeoutError),
                "retry_backoff": True,
                "retry_backoff_max": 600,
                "retry_jitter": True,
                "max_retries": 5,
            }
        )
        def process_data(event):
            # Native Celery retry support!
            ...
    """

    def decorator(func: Callable) -> Callable:
        # Generate handler ID if not provided
        handler_id_val = handler_id or f"{func.__module__}.{func.__name__}"

        # Build metadata
        handler_metadata = metadata.copy() if metadata else {}
        if celery_options:
            handler_metadata["celery_options"] = celery_options

        # Register the handler in the local registry
        registry = get_registry()
        registry.register_handler(
            routing_key=routing_key,
            handler_id=handler_id_val,
            handler=func,
            metadata=handler_metadata,
            name=name or func.__name__,
        )

        logger.info(
            f"Registered handler '{handler_id_val}' for topic '{routing_key}'"
            + (" (with celery_options)" if celery_options else ""),
            extra={"routing_key": routing_key, "handler_id": handler_id_val},
        )

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def _get_or_create_celery_task(
    celery_app: Any,
    handler_id: str,
    handler_func: Callable,
    celery_options: Dict[str, Any],
) -> Any:
    """
    Get or create a Celery task for a handler with celery_options.

    This dynamically creates a Celery task with the specified options,
    giving full native Celery retry support (autoretry_for, retry_backoff, etc.).

    Args:
        celery_app: Celery app instance
        handler_id: Unique identifier for the handler
        handler_func: The handler function to wrap
        celery_options: Celery task options (autoretry_for, retry_backoff, etc.)

    Returns:
        Celery task with native options applied
    """
    # Check cache first
    if handler_id in _dynamic_tasks:
        return _dynamic_tasks[handler_id]

    # Build task decorator options
    task_options = {
        "name": f"tchu_tchu.handler.{handler_id}",
        "bind": celery_options.get("bind", False),
    }

    # Pass through all Celery-native retry options
    native_options = [
        "autoretry_for",
        "retry_backoff",
        "retry_backoff_max",
        "retry_jitter",
        "max_retries",
        "default_retry_delay",
        "retry_kwargs",
        "acks_late",
        "reject_on_worker_lost",
        "throws",
    ]
    for opt in native_options:
        if opt in celery_options:
            task_options[opt] = celery_options[opt]

    # Create the Celery task dynamically
    celery_task = celery_app.task(**task_options)(handler_func)

    # Cache it
    _dynamic_tasks[handler_id] = celery_task

    logger.info(
        f"Created dynamic Celery task for handler '{handler_id}' with options: "
        f"{[k for k in celery_options.keys()]}"
    )

    return celery_task


def create_topic_dispatcher(
    celery_app: Any,
    task_name: str = "tchu_tchu.dispatch_event",
) -> Callable:
    """
    Create a Celery task that dispatches messages to local handlers.

    This task should be registered in your Celery app and will be called
    when messages arrive on your app's queue from the topic exchange.

    Your Celery config should bind this task's queue to the tchu_events exchange:

    ```python
    from kombu import Exchange, Queue

    app.conf.task_queues = (
        Queue(
            'myapp_queue',  # Your app's unique queue
            Exchange('tchu_events', type='topic'),
            routing_key='user.*',  # Topics you want to subscribe to
            durable=True,
            auto_delete=False,
        ),
    )

    app.conf.task_routes = {
        'tchu_tchu.dispatch_event': {'queue': 'myapp_queue'},
    }
    ```

    Native Celery Retry Support:
        Pass celery_options through TchuEvent or @subscribe to get full native
        Celery retry support (autoretry_for, retry_backoff, etc.):

        ```python
        # Via TchuEvent
        DataExchangeRunInitiatedEvent(
            handler=my_handler,
            celery_options={
                "autoretry_for": (ConnectionError, TimeoutError),
                "retry_backoff": True,
                "retry_backoff_max": 600,
                "retry_jitter": True,
                "max_retries": 5,
            }
        ).subscribe()

        # Via @subscribe decorator
        @subscribe(
            'data.process',
            celery_options={
                "autoretry_for": (ConnectionError,),
                "retry_backoff": True,
                "max_retries": 3,
            }
        )
        def process_data(event):
            ...
        ```

        tchu-tchu internally creates a Celery task with these native options.
        Your consuming app never needs to import Celery directly!

    Args:
        celery_app: Celery app instance
        task_name: Name for the dispatcher task (default: 'tchu_tchu.dispatch_event')

    Returns:
        Celery task function that dispatches to local handlers

    Example:
        # In your celery.py
        from tchu_tchu.subscriber import create_topic_dispatcher

        dispatcher = create_topic_dispatcher(app)
    """
    registry = get_registry()

    @celery_app.task(name=task_name, bind=True)
    def dispatch_event(self, message_body: str, routing_key: Optional[str] = None):
        """
        Dispatcher task that routes messages to local handlers.

        Note: Task configuration (acks_late, track_started, etc.) should be set
        at the Celery app level in celery.py, not here, for compatibility with
        different result backends (rpc://, redis://, etc.)

        Args:
            message_body: Serialized message body
            routing_key: Topic routing key from AMQP delivery info
        """
        # Extract routing key from task request if not provided
        if routing_key is None:
            # Try to get from Celery task metadata
            routing_key = self.request.get("routing_key", "unknown")

        log_message_received(logger, routing_key, self.request.id)

        try:
            # Deserialize message
            if isinstance(message_body, str):
                try:
                    deserialized = loads_message(message_body)
                except Exception:
                    # If deserialization fails, try standard JSON
                    deserialized = json.loads(message_body)
            else:
                deserialized = message_body

            # Get all matching handlers for this routing key
            handlers = registry.get_handlers(routing_key)

            if not handlers:
                logger.warning(
                    f"No local handlers found for routing key '{routing_key}'",
                    extra={"routing_key": routing_key},
                )
                return {"status": "no_handlers", "routing_key": routing_key}

            # Execute all matching handlers
            results = []
            for handler_info in handlers:
                handler_func = handler_info["function"]
                handler_name = handler_info["name"]
                handler_id = handler_info["id"]
                metadata = handler_info.get("metadata", {})
                celery_options = metadata.get("celery_options", {})

                try:
                    if celery_options:
                        # Handler has celery_options - create/get dynamic Celery task
                        # This gives full native Celery retry support
                        celery_task = _get_or_create_celery_task(
                            celery_app, handler_id, handler_func, celery_options
                        )
                        # Dispatch via .delay() for async execution with native retries
                        async_result = celery_task.delay(deserialized)
                        results.append(
                            {
                                "handler": handler_name,
                                "status": "dispatched",
                                "task_id": async_result.id,
                            }
                        )
                        logger.info(
                            f"Dispatched handler '{handler_name}' as Celery task "
                            f"with id {async_result.id} (native retry enabled)",
                            extra={
                                "routing_key": routing_key,
                                "task_id": async_result.id,
                            },
                        )
                    else:
                        # No celery_options - call handler directly (synchronous)
                        result = handler_func(deserialized)
                        results.append(
                            {
                                "handler": handler_name,
                                "status": "success",
                                "result": result,
                            }
                        )
                        log_handler_executed(
                            logger, handler_name, routing_key, self.request.id
                        )

                except Exception as e:
                    log_error(
                        logger,
                        f"Handler '{handler_name}' failed",
                        e,
                        routing_key,
                    )
                    results.append(
                        {
                            "handler": handler_name,
                            "status": "error",
                            "error": str(e),
                        }
                    )

            return {
                "status": "completed",
                "routing_key": routing_key,
                "handlers_executed": len(results),
                "results": results,
            }

        except Exception as e:
            log_error(
                logger, f"Failed to dispatch event for '{routing_key}'", e, routing_key
            )
            raise

    return dispatch_event


def get_subscribed_routing_keys(
    exclude_patterns: Optional[list[str]] = None,
    celery_app=None,
    force_import: bool = True,
) -> list[str]:
    """
    Get all routing keys that have handlers registered.

    This includes routing keys from both @subscribe decorators and Event().subscribe() calls.
    Useful for auto-configuring Celery queue bindings.

    **IMPORTANT**: If using with Celery autodiscover_tasks(), handlers may not be registered yet
    when this function is called. Either:
    1. Pass `celery_app` to force immediate task discovery
    2. Manually import subscriber modules before calling this function
    3. Call this function in a Celery worker_ready signal

    Args:
        exclude_patterns: Optional list of patterns to exclude (e.g., ['rpc.*'])
        celery_app: Optional Celery app instance to force task discovery
        force_import: If True and celery_app provided, forces immediate task import

    Returns:
        List of routing keys with registered handlers

    Example:
        # Option 1: Pass Celery app (recommended)
        keys = get_subscribed_routing_keys(celery_app=app)

        # Option 2: Manual imports
        import myapp.subscribers.user_subscriber  # noqa
        keys = get_subscribed_routing_keys()

        # Option 3: Exclude RPC patterns
        keys = get_subscribed_routing_keys(celery_app=app, exclude_patterns=['rpc.*'])
    """
    import fnmatch

    # Force task discovery if Celery app provided
    if celery_app and force_import:
        # This forces immediate import of autodiscovered tasks
        # which triggers @subscribe decorator registration
        try:
            celery_app.loader.import_default_modules()
        except Exception as e:
            logger = get_logger(__name__)
            logger.warning(
                f"Failed to force import tasks from Celery app: {e}. "
                f"Handlers may not be registered yet. Consider manually importing "
                f"subscriber modules before calling get_subscribed_routing_keys()."
            )

    registry = get_registry()
    all_keys = registry.get_all_routing_keys_and_patterns()

    if not exclude_patterns:
        return all_keys

    # Filter out excluded patterns
    filtered_keys = []
    for key in all_keys:
        should_exclude = False
        for pattern in exclude_patterns:
            # Convert RabbitMQ pattern to fnmatch pattern
            fnmatch_pattern = (
                pattern.replace(".", r"\.").replace("*", ".*").replace("#", ".*")
            )
            if fnmatch.fnmatch(key, fnmatch_pattern):
                should_exclude = True
                break

        if not should_exclude:
            filtered_keys.append(key)

    return filtered_keys
