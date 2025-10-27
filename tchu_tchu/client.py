"""TchuClient - Drop-in replacement for the original tchu client."""

from typing import Any, Dict, Union, Optional

from tchu_tchu.producer import CeleryProducer
from tchu_tchu.logging.handlers import get_logger

logger = get_logger(__name__)


class TchuClient:
    """
    Drop-in replacement for the original TchuClient.

    This class provides the exact same interface as your existing TchuClient
    to ensure seamless integration with your existing TchuEvent system.
    """

    def __init__(self, celery_app: Optional[Any] = None) -> None:
        """
        Initialize the TchuClient.

        Args:
            celery_app: Optional Celery app instance
        """
        self.producer = CeleryProducer(celery_app=celery_app)

    def publish(self, topic: str, data: Union[Dict[str, Any], Any], **kwargs) -> None:
        """
        Publish a message to a topic (fire-and-forget).

        This method matches the signature of your existing TchuClient.publish()
        method to ensure compatibility with your TchuEvent.publish() calls.

        Args:
            topic: Topic name to publish to
            data: Message data to publish
            **kwargs: Additional arguments passed to the producer
        """
        self.producer.publish(routing_key=topic, body=data, **kwargs)

    def call(
        self, topic: str, data: Union[Dict[str, Any], Any], timeout: int = 30, **kwargs
    ) -> Any:
        """
        Send a message and wait for a response (RPC-style).

        This method matches the signature of your existing TchuClient.call()
        method to ensure compatibility with your TchuEvent.call() calls.

        Args:
            topic: Topic name to send to
            data: Message data to send
            timeout: Timeout in seconds to wait for response
            **kwargs: Additional arguments passed to the producer

        Returns:
            Response from the handler
        """
        return self.producer.call(
            routing_key=topic, body=data, timeout=timeout, **kwargs
        )

    def get_topic_info(self, topic: str) -> Dict[str, Any]:
        """
        Get information about a topic.

        Args:
            topic: Topic name

        Returns:
            Dictionary with topic information
        """
        return self.producer.get_topic_info(topic)

    def list_topics(self) -> Dict[str, Any]:
        """
        List all available topics.

        Returns:
            Dictionary with topic information
        """
        return self.producer.list_topics()
