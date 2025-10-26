"""Celery-based message producer for tchu-tchu."""

import time
from typing import Any, Dict, Union, Optional
from celery import current_app
from celery.result import AsyncResult

from tchu_tchu.registry import get_registry
from tchu_tchu.serializers.pydantic_serializer import default_serializer
from tchu_tchu.utils.error_handling import (
    PublishError,
    TimeoutError as TchuTimeoutError,
)
from tchu_tchu.utils.response_handler import serialize_celery_result
from tchu_tchu.logging.handlers import (
    get_logger,
    log_message_published,
    log_rpc_call,
    log_error,
)

logger = get_logger(__name__)


class CeleryProducer:
    """
    Celery-based message producer that publishes messages to topics.

    This class replaces the original tchu Producer and provides the same API
    while using Celery's task system for message delivery.
    """

    def __init__(
        self, celery_app: Optional[Any] = None, serializer: Optional[Any] = None
    ) -> None:
        """
        Initialize the CeleryProducer.

        Args:
            celery_app: Optional Celery app instance (uses current_app if None)
            serializer: Optional custom serializer (uses default Pydantic serializer if None)
        """
        self.celery_app = celery_app or current_app
        self.serializer = serializer or default_serializer
        self.registry = get_registry()

    def publish(
        self,
        routing_key: str,
        body: Union[Dict[str, Any], Any],
        content_type: str = "application/json",
        delivery_mode: int = 2,
        **kwargs,
    ) -> None:
        """
        Publish a message to a topic (fire-and-forget).

        Args:
            routing_key: Topic name to publish to
            body: Message body (will be serialized)
            content_type: Content type (for compatibility, always uses JSON)
            delivery_mode: Delivery mode (for compatibility, ignored)
            **kwargs: Additional arguments (for compatibility)

        Raises:
            PublishError: If publishing fails
        """
        try:
            # Serialize the message body
            if isinstance(body, (str, bytes)):
                serialized_body = body
            else:
                serialized_body = self.serializer.serialize(body)

            # First, try local registry handlers (same app)
            local_handlers = self.registry.get_handlers(routing_key)
            
            # Get task names that should exist across the cluster
            # Format: tchu_tchu.topics.{topic_normalized}.*
            topic_normalized = routing_key.replace('.', '_').replace('*', 'wildcard')
            task_pattern = f"tchu_tchu.topics.{topic_normalized}."
            
            # Find all registered Celery tasks that match this topic
            registered_tasks = []
            for task_name in self.celery_app.tasks.keys():
                if task_name.startswith(task_pattern):
                    registered_tasks.append(task_name)
            
            # Combine local handlers and discovered tasks
            task_results = []
            sent_task_names = set()
            
            # Send to local handlers first
            for handler_info in local_handlers:
                try:
                    task = handler_info["function"]
                    task_name = handler_info["metadata"].get("task_name")
                    
                    # Apply the task asynchronously
                    result = task.apply_async(args=[serialized_body], **kwargs)
                    task_results.append(result)
                    sent_task_names.add(task_name)
                    
                    log_message_published(logger, routing_key, result.id)

                except Exception as e:
                    log_error(
                        logger,
                        f"Failed to send message to handler '{handler_info['name']}'",
                        e,
                        routing_key,
                    )
                    # Continue with other handlers even if one fails
                    continue
            
            # Send to remote tasks discovered in Celery
            for task_name in registered_tasks:
                if task_name not in sent_task_names:
                    try:
                        # Get the task from Celery's registry
                        task = self.celery_app.tasks.get(task_name)
                        if task:
                            result = task.apply_async(args=[serialized_body], **kwargs)
                            task_results.append(result)
                            sent_task_names.add(task_name)
                            log_message_published(logger, routing_key, result.id)
                    except Exception as e:
                        log_error(
                            logger,
                            f"Failed to send message to remote task '{task_name}'",
                            e,
                            routing_key,
                        )
                        continue

            if not task_results:
                logger.warning(
                    f"No handlers found for topic '{routing_key}'. "
                    f"Make sure consumer apps have started and registered their handlers."
                )
                return

            logger.info(
                f"Published message to topic '{routing_key}' - {len(task_results)} handlers notified",
                extra={"topic": routing_key, "handler_count": len(task_results)},
            )

        except Exception as e:
            log_error(
                logger,
                f"Failed to publish message to topic '{routing_key}'",
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

        Args:
            routing_key: Topic name to send to
            body: Message body (will be serialized)
            content_type: Content type (for compatibility, always uses JSON)
            delivery_mode: Delivery mode (for compatibility, ignored)
            timeout: Timeout in seconds to wait for response
            **kwargs: Additional arguments (for compatibility)

        Returns:
            Response from the first handler that completes

        Raises:
            PublishError: If publishing fails
            TimeoutError: If no response received within timeout
        """
        start_time = time.time()

        try:
            # Serialize the message body
            if isinstance(body, (str, bytes)):
                serialized_body = body
            else:
                serialized_body = self.serializer.serialize(body)

            # Get local handlers
            local_handlers = self.registry.get_handlers(routing_key)
            
            # Get task names that should exist across the cluster
            topic_normalized = routing_key.replace('.', '_').replace('*', 'wildcard')
            task_pattern = f"tchu_tchu.topics.{topic_normalized}."
            
            # Find all registered Celery tasks that match this topic
            registered_tasks = []
            for task_name in self.celery_app.tasks.keys():
                if task_name.startswith(task_pattern):
                    registered_tasks.append(task_name)

            # For RPC calls, we typically want the first handler's response
            # Send to all handlers but return the first successful response
            task_results = []
            sent_task_names = set()

            # Send to local handlers first
            for handler_info in local_handlers:
                try:
                    task = handler_info["function"]
                    task_name = handler_info["metadata"].get("task_name")

                    # Apply the task asynchronously
                    result = task.apply_async(args=[serialized_body], **kwargs)
                    task_results.append(result)
                    sent_task_names.add(task_name)

                    log_message_published(logger, routing_key, result.id)

                except Exception as e:
                    log_error(
                        logger,
                        f"Failed to send RPC message to handler '{handler_info['name']}'",
                        e,
                        routing_key,
                    )
                    continue
            
            # Send to remote tasks discovered in Celery
            for task_name in registered_tasks:
                if task_name not in sent_task_names:
                    try:
                        task = self.celery_app.tasks.get(task_name)
                        if task:
                            result = task.apply_async(args=[serialized_body], **kwargs)
                            task_results.append(result)
                            sent_task_names.add(task_name)
                            log_message_published(logger, routing_key, result.id)
                    except Exception as e:
                        log_error(
                            logger,
                            f"Failed to send RPC message to remote task '{task_name}'",
                            e,
                            routing_key,
                        )
                        continue

            if not task_results:
                raise PublishError(
                    f"No handlers found for topic '{routing_key}'. "
                    f"Make sure consumer apps have started and registered their handlers."
                )

            # Wait for the first result to complete
            primary_result = task_results[0]

            try:
                # Wait for result with timeout
                response = primary_result.get(timeout=timeout)

                # Serialize the response using our response handler
                serialized_response = serialize_celery_result(primary_result)

                execution_time = time.time() - start_time
                log_rpc_call(logger, routing_key, execution_time, primary_result.id)

                return serialized_response

            except Exception as e:
                if "timeout" in str(e).lower():
                    raise TchuTimeoutError(
                        "No response received within the timeout period"
                    )
                else:
                    raise PublishError(f"RPC call failed: {e}")

        except (PublishError, TchuTimeoutError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            log_error(
                logger,
                f"Failed to execute RPC call to topic '{routing_key}'",
                e,
                routing_key,
            )
            raise PublishError(f"Failed to execute RPC call: {e}")

    def get_topic_info(self, routing_key: str) -> Dict[str, Any]:
        """
        Get information about a topic.

        Args:
            routing_key: Topic name

        Returns:
            Dictionary with topic information
        """
        handlers = self.registry.get_handlers(routing_key)

        return {
            "topic": routing_key,
            "handler_count": len(handlers),
            "handlers": [
                {
                    "id": h["id"],
                    "name": h["name"],
                    "task_name": h["metadata"].get("task_name"),
                }
                for h in handlers
            ],
        }

    def list_topics(self) -> Dict[str, Any]:
        """
        List all available topics.

        Returns:
            Dictionary with topic information
        """
        registry = self.registry

        return {
            "exact_topics": registry.get_all_topics(),
            "pattern_topics": registry.get_all_patterns(),
            "total_handlers": registry.get_handler_count(),
        }
