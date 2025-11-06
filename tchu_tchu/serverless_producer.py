"""Serverless producer for serverless environments (Cloud Functions, Lambda, etc.).

This producer uses pika directly instead of Celery, making it suitable for
short-lived serverless functions where Celery's connection pooling doesn't work well.

Similar to the original tchu library's approach.
"""

import json
import uuid
import pika
from typing import Any, Dict, Union, Optional
from urllib.parse import urlparse

from tchu_tchu.utils.json_encoder import dumps_message
from tchu_tchu.utils.error_handling import PublishError
from tchu_tchu.logging.handlers import get_logger, log_error

logger = get_logger(__name__)


class ServerlessProducer:
    """
    Lightweight producer for serverless environments.

    Uses pika directly for short-lived connections that work in
    cloud functions, Lambda, and other serverless platforms.

    Example:
        # In a cloud function
        from tchu_tchu.serverless_producer import ServerlessProducer

        producer = ServerlessProducer(broker_url="amqp://user:pass@host:5672//")
        producer.publish('user.created', {'user_id': 123})
    """

    def __init__(
        self,
        broker_url: str,
        exchange_name: str = "tchu_events",
        connection_timeout: int = 10,
    ) -> None:
        """
        Initialize the ServerlessProducer.

        Args:
            broker_url: RabbitMQ connection URL (e.g., "amqp://user:pass@host:5672//")
            exchange_name: Exchange name (default: "tchu_events")
            connection_timeout: Connection timeout in seconds (default: 10)
        """
        self.broker_url = broker_url
        self.exchange_name = exchange_name
        self.connection_timeout = connection_timeout
        self._connection = None
        self._channel = None

    def _parse_broker_url(self) -> pika.ConnectionParameters:
        """Parse broker URL into pika ConnectionParameters."""
        try:
            parsed = urlparse(self.broker_url)

            # Extract credentials
            username = parsed.username or "guest"
            password = parsed.password or "guest"

            # Extract host and port
            host = parsed.hostname or "localhost"
            port = parsed.port or 5672

            # Extract virtual host (path without leading /)
            vhost = parsed.path.lstrip("/") or "/"

            credentials = pika.PlainCredentials(username, password)

            return pika.ConnectionParameters(
                host=host,
                port=port,
                virtual_host=vhost,
                credentials=credentials,
                socket_timeout=self.connection_timeout,
                connection_attempts=3,
                retry_delay=1,
            )
        except Exception as e:
            raise PublishError(f"Failed to parse broker URL: {e}")

    def _ensure_connection(self) -> None:
        """Ensure connection and channel are established."""
        try:
            if self._connection is None or self._connection.is_closed:
                params = self._parse_broker_url()
                self._connection = pika.BlockingConnection(params)
                self._channel = self._connection.channel()

                # Declare the exchange (idempotent)
                self._channel.exchange_declare(
                    exchange=self.exchange_name,
                    exchange_type="topic",
                    durable=True,
                )

                logger.debug(f"Connected to RabbitMQ at {self.broker_url}")
        except Exception as e:
            log_error(
                logger,
                f"Failed to connect to RabbitMQ",
                e,
                broker_url=self.broker_url,
            )
            raise PublishError(f"Failed to connect to RabbitMQ: {e}")

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

        Args:
            routing_key: Topic routing key (e.g., 'user.created', 'order.*')
            body: Message body (will be serialized to JSON)
            content_type: Content type (default: "application/json")
            delivery_mode: Delivery mode (1=non-persistent, 2=persistent)
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
                serialized_body = (
                    body if isinstance(body, bytes) else body.encode("utf-8")
                )
            else:
                serialized_body = dumps_message(body).encode("utf-8")

            # Ensure connection
            self._ensure_connection()

            # Publish to exchange
            properties = pika.BasicProperties(
                delivery_mode=delivery_mode,
                content_type=content_type,
                message_id=message_id,
            )

            self._channel.basic_publish(
                exchange=self.exchange_name,
                routing_key=routing_key,
                body=serialized_body,
                properties=properties,
            )

            logger.info(
                f"Published message {message_id} to routing key '{routing_key}'",
                extra={"routing_key": routing_key, "message_id": message_id},
            )

            return message_id

        except PublishError:
            raise
        except Exception as e:
            log_error(
                logger,
                f"Failed to publish message to routing key '{routing_key}'",
                e,
                routing_key,
            )
            raise PublishError(f"Failed to publish message: {e}")

    def close(self) -> None:
        """Close the connection."""
        try:
            if self._channel and self._channel.is_open:
                self._channel.close()
            if self._connection and self._connection.is_open:
                self._connection.close()
            logger.debug("Closed RabbitMQ connection")
        except Exception as e:
            logger.warning(f"Error closing connection: {e}")

    def __enter__(self):
        """Context manager entry."""
        self._ensure_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def __del__(self):
        """Cleanup on deletion."""
        try:
            self.close()
        except Exception:
            pass


class ServerlessClient:
    """
    Drop-in replacement for TchuClient that works in serverless environments.

    Example:
        # In a cloud function
        from tchu_tchu.serverless_producer import ServerlessClient

        client = ServerlessClient(broker_url="amqp://user:pass@host:5672//")
        client.publish('user.created', {'user_id': 123})
    """

    def __init__(
        self,
        broker_url: str,
        exchange_name: str = "tchu_events",
        connection_timeout: int = 10,
    ) -> None:
        """
        Initialize the ServerlessClient.

        Args:
            broker_url: RabbitMQ connection URL
            exchange_name: Exchange name (default: "tchu_events")
            connection_timeout: Connection timeout in seconds (default: 10)
        """
        self.producer = ServerlessProducer(
            broker_url=broker_url,
            exchange_name=exchange_name,
            connection_timeout=connection_timeout,
        )

    def publish(self, topic: str, data: Union[Dict[str, Any], Any], **kwargs) -> None:
        """
        Publish a message to a topic (fire-and-forget).

        Args:
            topic: Topic name to publish to
            data: Message data to publish
            **kwargs: Additional arguments passed to the producer
        """
        self.producer.publish(routing_key=topic, body=data, **kwargs)

    def close(self) -> None:
        """Close the connection."""
        self.producer.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
