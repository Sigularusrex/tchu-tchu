"""Celery producer with broadcast support via topic exchange."""

import time
import uuid
from typing import Any, Dict, Union, Optional, List
from celery import current_app

from tchu_tchu.utils.json_encoder import dumps_message
from tchu_tchu.utils.error_handling import (
    PublishError,
    TimeoutError as TchuTimeoutError,
)
from tchu_tchu.logging.handlers import (
    get_logger,
    log_error,
    log_message_sent,
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
        dispatcher_task_name: str = "tchu_tchu.dispatch_event",
    ) -> None:
        """
        Initialize the CeleryProducer.

        Args:
            celery_app: Optional Celery app instance (uses current_app if None)
            dispatcher_task_name: Name of the dispatcher task (default: 'tchu_tchu.dispatch_event')
        """
        self.celery_app = celery_app or current_app
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
                serialized_body = dumps_message(body)

            # Send task to dispatcher with routing_key in properties
            # The exchange/queue routing is configured in each app's Celery config
            self.celery_app.send_task(
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

        Note: RPC calls use point-to-point routing (not broadcast). The first
        worker to process the message returns the response.

        Args:
            routing_key: Topic routing key (e.g., 'user.validate')
            body: Message body (will be serialized)
            content_type: Content type (for compatibility)
            delivery_mode: Delivery mode (for compatibility)
            timeout: Timeout in seconds to wait for response (default: 30)
            **kwargs: Additional arguments passed to send_task

        Returns:
            Response from the handler

        Raises:
            PublishError: If publishing fails
            TimeoutError: If no response received within timeout
        """
        start_time = time.time()

        try:
            # Generate unique message ID
            message_id = str(uuid.uuid4())

            # Serialize the message body
            if isinstance(body, (str, bytes)):
                serialized_body = body
            else:
                serialized_body = dumps_message(body)

            # Send task to dispatcher and wait for result
            # For RPC, we want the result, so we don't use ignore_result
            result = self.celery_app.send_task(
                self.dispatcher_task_name,
                args=[serialized_body],
                kwargs={"routing_key": routing_key},
                routing_key=routing_key,
                task_id=message_id,
                **kwargs,
            )

            logger.info(
                f"RPC call {message_id} sent to routing key '{routing_key}'",
                extra={"routing_key": routing_key, "message_id": message_id},
            )

            try:
                # Wait for result with timeout
                # The dispatcher returns a dict with handler results
                response = result.get(timeout=timeout)

                execution_time = time.time() - start_time
                logger.info(
                    f"RPC call {message_id} completed in {execution_time:.2f} seconds",
                    extra={
                        "routing_key": routing_key,
                        "message_id": message_id,
                        "execution_time": execution_time,
                    },
                )

                # Extract the actual result from the dispatcher response
                if isinstance(response, dict):
                    # Check if there were no handlers
                    if response.get("status") == "no_handlers":
                        raise PublishError(
                            f"No handlers found for routing key '{routing_key}'"
                        )

                    # Extract results, skipping None results to allow handlers to "pass"
                    results = response.get("results", [])
                    if results:
                        # Find first non-None successful result
                        for result_item in results:
                            if result_item.get("status") == "success":
                                result = result_item.get("result")
                                # Skip None results - allows handlers to "pass" to next handler
                                if result is not None:
                                    logger.debug(
                                        f"RPC handler '{result_item.get('handler')}' returned result for '{routing_key}'"
                                    )
                                    return result
                                else:
                                    logger.debug(
                                        f"RPC handler '{result_item.get('handler')}' returned None, trying next handler"
                                    )
                            elif result_item.get("status") == "error":
                                # Handler failed - raise error immediately
                                error = result_item.get("error", "Unknown error")
                                handler_name = result_item.get("handler", "unknown")
                                raise PublishError(
                                    f"Handler '{handler_name}' failed: {error}"
                                )

                        # All handlers returned None
                        logger.warning(
                            f"All handlers for '{routing_key}' returned None. "
                            f"At least one handler should return a non-None response for RPC calls."
                        )
                        return None
                    else:
                        raise PublishError(
                            f"No results returned from handler for routing key '{routing_key}'. "
                            f"Handler may have executed but failed to return a response."
                        )

                # If response is not a dict, return it as-is (backward compatibility)
                return response

            except Exception as e:
                # Check if it's a timeout
                if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                    raise TchuTimeoutError(
                        f"No response received within {timeout} seconds for routing key '{routing_key}'"
                    )
                else:
                    # Re-raise other exceptions
                    raise PublishError(f"RPC call failed: {e}")

        except (PublishError, TchuTimeoutError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            log_error(
                logger,
                f"Failed to execute RPC call to routing key '{routing_key}'",
                e,
                routing_key,
            )
            raise PublishError(f"Failed to execute RPC call: {e}")

    def call_all(
        self,
        routing_key: str,
        body: Union[Dict[str, Any], Any],
        content_type: str = "application/json",
        delivery_mode: int = 2,
        timeout: int = 30,
        **kwargs,
    ) -> List[Any]:
        """
        Send a message and collect all non-None responses from multiple handlers (fan-out/gather).

        Unlike call() which returns the first non-None result, this method collects
        ALL non-None results from all handlers that respond. Useful for gathering
        data from multiple sources or services.

        Args:
            routing_key: Routing key for the message
            body: Message body (dict or serializable object)
            content_type: Content type (default: "application/json")
            delivery_mode: Message persistence (2=persistent)
            timeout: Timeout in seconds to wait for responses
            **kwargs: Additional arguments for send_task

        Returns:
            List of all non-None results from handlers (empty list if all return None)

        Raises:
            PublishError: If publish fails or handlers fail
            TchuTimeoutError: If no response within timeout

        Example:
            # Multiple handlers return different data
            results = client.call_all('query.databases', {'query': 'SELECT ...'})
            # Returns: [{"db1": [...]}, {"db2": [...]}, {"db3": [...]}]

            # Aggregate results
            all_records = []
            for result in results:
                all_records.extend(result.values())
        """
        try:
            import time

            message_id = self._generate_message_id()
            start_time = time.time()

            log_message_sent(
                logger,
                routing_key,
                message_id,
                extra_info={"pattern": "fan-out-gather", "expecting_multiple": True},
            )

            # Use the same send_task mechanism as call()
            result = self._celery_app.send_task(
                self._task_name,
                args=[body, routing_key],
                kwargs={},
                exchange=self._exchange.name,
                routing_key=routing_key,
                serializer=self._serializer.name,
                content_type=content_type,
                delivery_mode=delivery_mode,
                **kwargs,
            )

            try:
                # Wait for result with timeout
                response = result.get(timeout=timeout)

                execution_time = time.time() - start_time
                logger.info(
                    f"Fan-out call {message_id} completed in {execution_time:.2f} seconds",
                    extra={
                        "routing_key": routing_key,
                        "message_id": message_id,
                        "execution_time": execution_time,
                        "pattern": "fan-out-gather",
                    },
                )

                # Extract ALL non-None results
                if isinstance(response, dict):
                    # Check if there were no handlers
                    if response.get("status") == "no_handlers":
                        raise PublishError(
                            f"No handlers found for routing key '{routing_key}'"
                        )

                    # Collect all non-None successful results
                    results = response.get("results", [])
                    collected_results = []

                    for result_item in results:
                        if result_item.get("status") == "success":
                            result_data = result_item.get("result")
                            # Only include non-None results
                            if result_data is not None:
                                collected_results.append(result_data)
                                logger.debug(
                                    f"Collected result from handler '{result_item.get('handler')}'"
                                )
                        elif result_item.get("status") == "error":
                            # Log errors but continue collecting from other handlers
                            error = result_item.get("error", "Unknown error")
                            handler_name = result_item.get("handler", "unknown")
                            logger.warning(
                                f"Handler '{handler_name}' failed during fan-out: {error}"
                            )

                    if not collected_results:
                        logger.warning(
                            f"No handlers returned non-None results for '{routing_key}'"
                        )
                    else:
                        logger.info(
                            f"Collected {len(collected_results)} results from handlers for '{routing_key}'"
                        )

                    return collected_results

                # If response is not a dict, return it as single-item list
                return [response] if response is not None else []

            except Exception as e:
                # Check if it's a timeout
                if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                    raise TchuTimeoutError(
                        f"No response received within {timeout} seconds for routing key '{routing_key}'"
                    )
                else:
                    # Re-raise other exceptions
                    raise PublishError(f"Fan-out call failed: {e}")

        except (PublishError, TchuTimeoutError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            log_error(
                logger,
                f"Failed to execute fan-out call to routing key '{routing_key}'",
                e,
                routing_key,
            )
            raise PublishError(f"Failed to execute fan-out call: {e}")
