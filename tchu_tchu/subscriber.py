"""Topic subscription utilities for tchu-tchu."""

from typing import Callable, Optional, Dict, Any
import celery
from celery import shared_task

from tchu_tchu.registry import get_registry
from tchu_tchu.serializers.pydantic_serializer import default_serializer
from tchu_tchu.utils.error_handling import SubscriptionError
from tchu_tchu.logging.handlers import get_logger, log_message_received, log_error

logger = get_logger(__name__)


def subscribe(
    topic: str,
    handler: Optional[Callable] = None,
    handler_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    task_name: Optional[str] = None,
) -> str:
    """
    Subscribe a handler function to a topic.

    This function registers the handler with the topic registry and creates
    a Celery task that will be called when messages are published to the topic.

    Args:
        topic: Topic pattern to subscribe to (supports wildcards like "user.*")
        handler: Handler function to call when messages are received (None for remote task proxy)
        handler_name: Optional custom name for the handler
        metadata: Optional metadata to store with the handler
        task_name: Optional explicit task name (for registering remote tasks as proxies)

    Returns:
        Unique handler ID

    Raises:
        SubscriptionError: If subscription fails

    Example:
        # Local handler
        def handle_user_created(data):
            print(f"User created: {data}")
        handler_id = subscribe("user.created", handle_user_created)

        # Remote task proxy (register that a remote task should be triggered)
        subscribe("user.created", task_name="tchu_tchu.topics.user_created.remote_handler")
    """
    try:
        registry = get_registry()

        # Handle remote task proxy (no local handler, just a task name)
        if handler is None and task_name:
            # This is a proxy registration for a remote task
            handler_id = registry.register_handler(
                topic=topic,
                handler=None,  # No local handler
                handler_name=handler_name or task_name.split(".")[-1],
                metadata={
                    **(metadata or {}),
                    "task_name": task_name,
                    "is_remote_proxy": True,
                },
            )
            logger.info(
                f"Successfully registered remote task proxy '{task_name}' for topic '{topic}'"
            )
            return handler_id

        if handler is None:
            raise ValueError("Either handler or task_name must be provided")

        # Generate handler name if not provided
        if handler_name is None:
            handler_name = f"{getattr(handler, '__name__', 'handler')}"

        # Create a unique task name for this handler
        if task_name is None:
            task_name = f"tchu_tchu.topics.{topic.replace('.', '_').replace('*', 'wildcard')}.{handler_name}"

        # Create Celery task wrapper
        @shared_task(name=task_name, bind=True)
        def task_wrapper(self, message_data: Dict[str, Any]) -> Any:
            """Celery task wrapper for the handler function."""
            task_id = self.request.id

            try:
                log_message_received(logger, topic, task_id)

                # Deserialize the message data
                if isinstance(message_data, (str, bytes)):
                    deserialized_data = default_serializer.deserialize(message_data)
                else:
                    deserialized_data = message_data

                # Call the original handler
                result = handler(deserialized_data)

                logger.info(
                    f"Handler '{handler_name}' completed successfully",
                    extra={"topic": topic, "task_id": task_id},
                )

                return result

            except Exception as e:
                log_error(logger, f"Handler '{handler_name}' failed", e, topic, task_id)
                # Re-raise to let Celery handle retries
                raise

        # Register the handler in the registry
        handler_id = registry.register_handler(
            topic=topic,
            handler=task_wrapper,
            handler_name=handler_name,
            metadata={
                **(metadata or {}),
                "task_name": task_name,
                "original_handler": handler,
            },
        )

        logger.info(
            f"Successfully subscribed handler '{handler_name}' to topic '{topic}' with task '{task_name}'"
        )
        return handler_id

    except Exception as e:
        logger.error(
            f"Failed to subscribe handler to topic '{topic}': {e}", exc_info=True
        )
        raise SubscriptionError(f"Failed to subscribe to topic '{topic}': {e}")


def unsubscribe(handler_id: str) -> bool:
    """
    Unsubscribe a handler by ID.

    Args:
        handler_id: Handler ID returned by subscribe()

    Returns:
        True if handler was found and removed, False otherwise
    """
    try:
        registry = get_registry()
        success = registry.unregister_handler(handler_id)

        if success:
            logger.info(f"Successfully unsubscribed handler '{handler_id}'")
        else:
            logger.warning(f"Handler '{handler_id}' not found for unsubscription")

        return success

    except Exception as e:
        logger.error(
            f"Failed to unsubscribe handler '{handler_id}': {e}", exc_info=True
        )
        return False


def get_topic_handlers(topic: str) -> list:
    """
    Get all handlers registered for a topic.

    Args:
        topic: Topic name

    Returns:
        List of handler information dictionaries
    """
    registry = get_registry()
    return registry.get_handlers(topic)


def list_subscriptions() -> Dict[str, Any]:
    """
    List all current subscriptions.

    Returns:
        Dictionary with subscription information
    """
    registry = get_registry()

    return {
        "exact_topics": registry.get_all_topics(),
        "pattern_topics": registry.get_all_patterns(),
        "total_handlers": registry.get_handler_count(),
    }


def register_remote_task(topic: str, task_name: str) -> str:
    """
    Register a remote Celery task as a handler for cross-app communication.

    Use this in your publishing app to register tasks that exist in consumer apps.
    This allows the publisher to send messages to remote workers via Celery's routing.

    Args:
        topic: Topic pattern to route messages to
        task_name: Full Celery task name (e.g. "tchu_tchu.topics.user_created.handle_user")

    Returns:
        Handler ID

    Example:
        # In your publishing app, register remote tasks from consumer apps
        register_remote_task(
            "coolset.scranton.information_request.prepared",
            "tchu_tchu.topics.coolset_scranton_information_request_prepared.InformationRequestPreparedEvent_pulse_execute_information_request_task"
        )

        # Now when you publish, it will route to the Pulse app's worker
        event.publish()
    """
    return subscribe(topic=topic, task_name=task_name)
