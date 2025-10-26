"""Celery producer with broadcast support via topic exchange."""

import uuid
from typing import Any, Dict, Union, Optional
from celery import current_app

from tchu_tchu.serializers.pydantic_serializer import default_serializer
from tchu_tchu.utils.error_handling import PublishError
from tchu_tchu.logging.handlers import (
    get_logger,
    log_error,
)

logger = get_logger(__name__)


class CeleryProducer:
    """
    Celery producer that publishes to a topic exchange for broadcast messaging.

    This uses Celery's send_task() with proper exchange/routing configuration
    to enable true broadcast: multiple apps can subscribe to the same events.

    Key features:
    - Publishes to a topic exchange (not direct task calls)
    - Multiple apps receive the same message
    - Uses existing Celery workers
    - Fast (no task discovery needed)
    """

    def __init__(
        self,
        celery_app: Optional[Any] = None,
        serializer: Optional[Any] = None,
        dispatcher_task_name: str = "tchu_tchu.dispatch_event",
    ) -> None:
        """
        Initialize the CeleryProducer.

        Args:
            celery_app: Optional Celery app instance (uses current_app if None)
            serializer: Optional custom serializer (uses default Pydantic serializer if None)
            dispatcher_task_name: Name of the dispatcher task (default: 'tchu_tchu.dispatch_event')
        """
        self.celery_app = celery_app or current_app
        self.serializer = serializer or default_serializer
        self.dispatcher_task_name = dispatcher_task_name

    def publish(
        self,
        routing_key: str,
        body: Union[Dict[str, Any], Any],
        content_type: str = "application/json",
        delivery_mode: int = 2,
        **kwargs,
    ) -> str:
        """
        Publish a message to a routing key (broadcast to all subscribers).

        This sends a task to the dispatcher, which is configured to consume
        from queues bound to a topic exchange. All apps with matching queue
        bindings will receive the message.

        Args:
            routing_key: Topic routing key (e.g., 'user.created', 'order.*')
            body: Message body (will be serialized)
            content_type: Content type (for compatibility)
            delivery_mode: Delivery mode (for compatibility)
            **kwargs: Additional arguments (for compatibility)

        Returns:
            Message ID for tracking

        Raises:
            PublishError: If publishing fails
        """
        try:
            # Generate unique message ID
            message_id = str(uuid.uuid4())

            # Serialize the message body
            if isinstance(body, (str, bytes)):
                serialized_body = body
            else:
                serialized_body = self.serializer.serialize(body)

            # Send task to dispatcher with routing_key in properties
            # The exchange/queue routing is configured in each app's Celery config
            result = self.celery_app.send_task(
                self.dispatcher_task_name,
                args=[serialized_body],
                kwargs={"routing_key": routing_key},
                routing_key=routing_key,  # This is used by AMQP for routing to queues
                task_id=message_id,
            )

            logger.info(
                f"Published message {message_id} to routing key '{routing_key}'",
                extra={"routing_key": routing_key, "message_id": message_id},
            )

            return message_id

        except Exception as e:
            log_error(
                logger,
                f"Failed to publish message to routing key '{routing_key}'",
                e,
                routing_key,
            )
            raise PublishError(f"Failed to publish message: {e}")

    def call(
        self,
        routing_key: str,
        body: Union[Dict[str, Any], Any],
        content_type: str = "application/json",
        delivery_mode: int = 2,
        timeout: int = 30,
        **kwargs,
    ) -> Any:
        """
        Send a message and wait for a response (RPC-style).

        Note: RPC pattern is more complex with broadcast exchanges.
        This will be implemented in a future version.

        Args:
            routing_key: Topic routing key
            body: Message body
            content_type: Content type
            delivery_mode: Delivery mode
            timeout: Timeout in seconds
            **kwargs: Additional arguments

        Raises:
            NotImplementedError: RPC not yet supported with broadcast pattern
        """
        raise NotImplementedError(
            "RPC calls are not yet supported with the broadcast pattern. "
            "Use publish() for fire-and-forget messaging. "
            "RPC support will be added in a future version."
        )
