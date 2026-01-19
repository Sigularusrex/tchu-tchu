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

    ALL handlers are created as Celery tasks at decorator time (import time).
    For broadcast messages, handlers are dispatched via .delay() for async execution.
    For RPC messages, handlers are called directly to return results.

    Args:
        routing_key: Topic routing key pattern (e.g., 'user.created', 'order.*')
        name: Optional human-readable name for the handler
        handler_id: Optional unique ID for the handler
        metadata: Optional metadata dictionary
        celery_options: Optional Celery task options for native retry support.
            Supported options (passed directly to Celery task decorator):
            - autoretry_for: tuple - Exception classes to auto-retry on
            - retry_backoff: bool/int - Enable exponential backoff
            - retry_backoff_max: int - Maximum backoff time in seconds
            - retry_jitter: bool - Add randomness to backoff
            - max_retries: int - Maximum retry attempts
            - default_retry_delay: int - Default delay between retries
            - rate_limit: str - Task rate limit (e.g., "10/m")
            - time_limit: int - Hard time limit in seconds
            - soft_time_limit: int - Soft time limit in seconds
            - acks_late: bool - Acknowledge after task completes
            - reject_on_worker_lost: bool - Reject task if worker dies

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
        def process_data(data):
            # Native Celery retry support!
            ...
    """

    def decorator(func: Callable) -> Callable:
        from celery import shared_task

        # Generate handler ID if not provided
        handler_id_val = handler_id or f"{func.__module__}.{func.__name__}"
        handler_name = name or func.__name__

        # Build Celery task options
        task_options = {
            "name": f"tchu_tchu.handler.{handler_id_val}",
        }

        # Add celery_options if provided (retries, rate limits, etc.)
        if celery_options:
            task_options.update(celery_options)

        # Create wrapper that removes _tchu_meta before calling handler
        def clean_handler(data: Dict[str, Any]) -> Any:
            """Wrapper that removes _tchu_meta before calling original handler."""
            clean_data = {k: v for k, v in data.items() if k != "_tchu_meta"}
            return func(clean_data)

        # Create the Celery task at import time
        celery_task = shared_task(**task_options)(clean_handler)

        # Build metadata
        handler_metadata = metadata.copy() if metadata else {}
        handler_metadata["celery_options"] = celery_options

        # Register the Celery task in the local registry
        registry = get_registry()
        registry.register_handler(
            routing_key=routing_key,
            handler_id=handler_id_val,
            handler=celery_task,  # Register the Celery task, not raw function
            metadata=handler_metadata,
            name=handler_name,
        )

        logger.debug(
            f"Registered handler '{handler_id_val}' for '{routing_key}'"
            + (f" with celery_options" if celery_options else ""),
            extra={"routing_key": routing_key, "handler_id": handler_id_val},
        )

        # Return the original function so it can still be called directly if needed
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # Attach the Celery task to the wrapper for direct access if needed
        wrapper.celery_task = celery_task

        return wrapper

    return decorator


def create_topic_dispatcher(
    celery_app: Any,
    task_name: str = "tchu_tchu.dispatch_event",
) -> Callable:
    """
    Create a Celery task that dispatches messages to local handlers.

    This task should be registered in your Celery app and will be called
    when messages arrive on your app's queue from the topic exchange.

    Execution behavior:
        - RPC messages (from client.call()): Handlers are called directly to return results
        - Broadcast messages (from client.publish()): Handlers are dispatched via .delay()
          as async Celery tasks with native retry support

    Deduplication:
        Handler tasks use deterministic task IDs based on message_id + handler_name.
        Celery's result backend automatically prevents duplicate task execution.

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

        Execution mode is determined by _tchu_meta.is_rpc in the message:
        - is_rpc=True: Direct call (must return result to caller)
        - is_rpc=False: Async dispatch via .delay() (fire-and-forget)

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

        message_id = self.request.id  # Original message task_id for deduplication
        log_message_received(logger, routing_key, message_id)

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

            # Extract message type from _tchu_meta
            # BACKWARD COMPATIBILITY: If _tchu_meta is missing (from 2.x publishers),
            # default to old behavior (direct call) to maintain RPC functionality
            # TODO: remove backwards compatibility when moving to Salt
            if "_tchu_meta" not in deserialized:
                # No metadata = old 2.x message, use direct call (old behavior)
                is_rpc = True
                logger.debug(
                    f"No _tchu_meta found (2.x publisher?), using direct call for '{routing_key}'"
                )
            else:
                tchu_meta = deserialized["_tchu_meta"]
                is_rpc = tchu_meta.get("is_rpc", False)

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
                handler_task = handler_info[
                    "function"
                ]  # This is now always a Celery task
                handler_name = handler_info["name"]
                handler_id = handler_info["id"]

                try:
                    if is_rpc:
                        # RPC: Must call directly to return result to caller
                        # Call the task function directly (not .delay())
                        result = handler_task(deserialized)
                        results.append(
                            {
                                "handler": handler_name,
                                "status": "success",
                                "result": result,
                            }
                        )
                        log_handler_executed(
                            logger, handler_name, routing_key, message_id
                        )
                    else:
                        # Broadcast: Dispatch as async Celery task
                        # Use deterministic task_id for deduplication: message_id:handler_id
                        handler_task_id = f"{message_id}:{handler_id}"

                        async_result = handler_task.apply_async(
                            args=[deserialized],
                            task_id=handler_task_id,  # Celery deduplicates based on this
                        )
                        results.append(
                            {
                                "handler": handler_name,
                                "status": "dispatched",
                                "task_id": async_result.id,
                            }
                        )
                        logger.debug(
                            f"Dispatched handler '{handler_name}' (task_id={async_result.id})",
                            extra={
                                "routing_key": routing_key,
                                "task_id": async_result.id,
                            },
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
                "is_rpc": is_rpc,
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
