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

            # Get all handlers from local registry
            handlers = self.registry.get_handlers(routing_key)

            # AUTO-DISCOVERY: Check for remote tasks matching this topic
            # This allows cross-app messaging without manual registration
            topic_normalized = routing_key.replace(".", "_").replace("*", "wildcard")
            task_pattern = f"tchu_tchu.topics.{topic_normalized}."

            # Discover tasks from all active workers via Celery inspect
            try:
                inspect = self.celery_app.control.inspect(timeout=1.0)
                registered_tasks = inspect.registered()

                if registered_tasks:
                    # registered_tasks is a dict: {worker_name: [task_names]}
                    all_tasks = set()
                    for worker_tasks in registered_tasks.values():
                        all_tasks.update(worker_tasks)

                    # Find matching tasks that aren't already in our handlers
                    handler_task_names = {
                        h["metadata"].get("task_name") for h in handlers
                    }

                    for task_name in all_tasks:
                        if (
                            task_name.startswith(task_pattern)
                            and task_name not in handler_task_names
                        ):
                            # Found a remote task! Add it to handlers
                            handlers.append(
                                {
                                    "id": f"discovered_{task_name}",
                                    "name": task_name.split(".")[-1],
                                    "function": None,  # Remote task, no local function
                                    "metadata": {
                                        "task_name": task_name,
                                        "is_remote_proxy": True,
                                        "auto_discovered": True,
                                    },
                                }
                            )
                            logger.debug(f"Auto-discovered remote task: {task_name}")
            except Exception as e:
                # Inspection failed - maybe no workers available or timeout
                # This is not critical, just log and continue with local handlers
                logger.debug(
                    f"Task auto-discovery failed (this is normal if no remote workers): {e}"
                )

            if not handlers:
                logger.warning(
                    f"No handlers found for topic '{routing_key}' (checked local registry and remote workers). "
                    f"Message will be discarded. If this is intentional (e.g., model signals), this is normal."
                )
                return

            # Send message to all registered handlers in parallel
            # Use send_task() which works across all workers via the broker
            task_results = []
            for handler_info in handlers:
                try:
                    task_name = handler_info["metadata"].get("task_name")

                    # Always use send_task() - the proper Celery way
                    # This sends the task to the broker, which routes it to any
                    # worker that has this task registered, regardless of which app
                    #
                    # For apps with separate queues, find which worker has this task
                    # and route to that worker's queue
                    send_kwargs = kwargs.copy()
                    if "queue" not in send_kwargs and handler_info["metadata"].get(
                        "auto_discovered"
                    ):
                        # This is an auto-discovered remote task
                        # Find which queue the worker is consuming from
                        queue_name = self._find_task_queue(task_name)
                        if queue_name:
                            send_kwargs["queue"] = queue_name
                            logger.debug(
                                f"Routing task {task_name} to queue: {queue_name}"
                            )

                    result = self.celery_app.send_task(
                        task_name, args=[serialized_body], **send_kwargs
                    )
                    task_results.append(result)
                    log_message_published(logger, routing_key, result.id)

                except Exception as e:
                    log_error(
                        logger,
                        f"Failed to send message to task '{task_name}'",
                        e,
                        routing_key,
                    )
                    # Continue with other handlers even if one fails
                    continue

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

            # Get all handlers from registry
            handlers = self.registry.get_handlers(routing_key)

            # AUTO-DISCOVERY: Check for remote tasks matching this topic
            topic_normalized = routing_key.replace(".", "_").replace("*", "wildcard")
            task_pattern = f"tchu_tchu.topics.{topic_normalized}."

            try:
                inspect = self.celery_app.control.inspect(timeout=1.0)
                registered_tasks = inspect.registered()

                if registered_tasks:
                    all_tasks = set()
                    for worker_tasks in registered_tasks.values():
                        all_tasks.update(worker_tasks)

                    handler_task_names = {
                        h["metadata"].get("task_name") for h in handlers
                    }

                    for task_name in all_tasks:
                        if (
                            task_name.startswith(task_pattern)
                            and task_name not in handler_task_names
                        ):
                            handlers.append(
                                {
                                    "id": f"discovered_{task_name}",
                                    "name": task_name.split(".")[-1],
                                    "function": None,
                                    "metadata": {
                                        "task_name": task_name,
                                        "is_remote_proxy": True,
                                        "auto_discovered": True,
                                    },
                                }
                            )
                            logger.debug(
                                f"Auto-discovered remote task for RPC: {task_name}"
                            )
            except Exception as e:
                logger.debug(f"Task auto-discovery failed for RPC: {e}")

            if not handlers:
                raise PublishError(
                    f"No handlers found for topic '{routing_key}' (checked local registry and remote workers)."
                )

            # For RPC calls, send to all handlers and return the first response
            task_results = []
            for handler_info in handlers:
                try:
                    task_name = handler_info["metadata"].get("task_name")

                    # Use send_task() - works across all workers
                    # For auto-discovered tasks, find the correct queue
                    send_kwargs = kwargs.copy()
                    if "queue" not in send_kwargs and handler_info["metadata"].get(
                        "auto_discovered"
                    ):
                        queue_name = self._find_task_queue(task_name)
                        if queue_name:
                            send_kwargs["queue"] = queue_name
                            logger.debug(
                                f"Routing RPC task {task_name} to queue: {queue_name}"
                            )

                    result = self.celery_app.send_task(
                        task_name, args=[serialized_body], **send_kwargs
                    )
                    task_results.append(result)
                    log_message_published(logger, routing_key, result.id)

                except Exception as e:
                    log_error(
                        logger,
                        f"Failed to send RPC message to task '{task_name}'",
                        e,
                        routing_key,
                    )
                    continue

            if not task_results:
                raise PublishError("Failed to send message to any handlers")

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

    def _find_task_queue(self, task_name: str) -> Optional[str]:
        """
        Find which queue a task is registered on by inspecting active workers.

        Args:
            task_name: Full task name to find

        Returns:
            Queue name if found, None otherwise
        """
        try:
            inspect = self.celery_app.control.inspect(timeout=0.5)

            # Get active queues for each worker
            active_queues = inspect.active_queues()

            # Get registered tasks for each worker
            registered = inspect.registered()

            if not active_queues or not registered:
                return None

            # Find which worker has this task
            for worker_name, tasks in registered.items():
                if task_name in tasks:
                    # Found the worker! Now get its queue(s)
                    worker_queues = active_queues.get(worker_name, [])
                    if worker_queues:
                        # Return the first queue (usually the main one)
                        # Queue info is dict with 'name', 'exchange', 'routing_key'
                        queue_name = worker_queues[0].get("name")
                        return queue_name

            return None

        except Exception as e:
            logger.debug(f"Failed to find queue for task {task_name}: {e}")
            return None

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
