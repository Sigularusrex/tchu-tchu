"""Subscribe to topics and handle messages with Celery integration."""

import json
from typing import Callable, Optional, Any, Dict
from functools import wraps

from tchu_tchu.registry import get_registry
from tchu_tchu.serializers.pydantic_serializer import default_serializer
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

    Returns:
        Decorated function

    Example:
        @subscribe('user.created')
        def handle_user_created(event):
            print(f"User created: {event}")
    """

    def decorator(func: Callable) -> Callable:
        # Generate handler ID if not provided
        handler_id_val = handler_id or f"{func.__module__}.{func.__name__}"

        # Register the handler in the local registry
        registry = get_registry()
        registry.register_handler(
            routing_key=routing_key,
            handler_id=handler_id_val,
            handler=func,
            metadata=metadata or {},
            name=name or func.__name__,
        )

        logger.info(
            f"Registered handler '{handler_id_val}' for topic '{routing_key}'",
            extra={"routing_key": routing_key, "handler_id": handler_id_val},
        )

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def create_topic_dispatcher(
    celery_app: Any,
    task_name: str = "tchu_tchu.dispatch_event",
    serializer: Optional[Any] = None,
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

    Args:
        celery_app: Celery app instance
        task_name: Name for the dispatcher task (default: 'tchu_tchu.dispatch_event')
        serializer: Optional custom serializer

    Returns:
        Celery task function that dispatches to local handlers

    Example:
        # In your celery.py
        from tchu_tchu.subscriber import create_topic_dispatcher

        dispatcher = create_topic_dispatcher(app)
    """
    _serializer = serializer or default_serializer
    registry = get_registry()

    @celery_app.task(name=task_name, bind=True)
    def dispatch_event(self, message_body: str, routing_key: Optional[str] = None):
        """
        Dispatcher task that routes messages to local handlers.

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
                    deserialized = _serializer.deserialize(message_body)
                except Exception:
                    # If deserialization fails, try JSON
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
                try:
                    handler_func = handler_info["function"]
                    result = handler_func(deserialized)
                    results.append(
                        {
                            "handler": handler_info["name"],
                            "status": "success",
                            "result": result,
                        }
                    )
                    log_handler_executed(
                        logger, handler_info["name"], routing_key, self.request.id
                    )
                except Exception as e:
                    log_error(
                        logger,
                        f"Handler '{handler_info['name']}' failed",
                        e,
                        routing_key,
                    )
                    results.append(
                        {
                            "handler": handler_info["name"],
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
) -> list[str]:
    """
    Get all routing keys that have handlers registered.

    This includes routing keys from both @subscribe decorators and Event().subscribe() calls.
    Useful for auto-configuring Celery queue bindings.

    Args:
        exclude_patterns: Optional list of patterns to exclude (e.g., ['rpc.*'])

    Returns:
        List of routing keys with registered handlers

    Example:
        # Get all routing keys except RPC
        keys = get_subscribed_routing_keys(exclude_patterns=['rpc.*'])
        # Returns: ['user.created', 'order.updated', 'coolset.scranton.*', ...]
    """
    import fnmatch

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
