"""Registry for managing routing key-to-handler mappings."""

import re
from typing import Dict, List, Callable, Any, Optional
from collections import defaultdict
from threading import Lock

from tchu_tchu.utils.error_handling import SubscriptionError
from tchu_tchu.logging.handlers import get_logger

logger = get_logger(__name__)


class TopicRegistry:
    """
    Global registry for managing routing key-to-handler mappings.

    Supports:
    - Multiple handlers per routing key
    - Wildcard pattern matching (e.g., "user.*")
    - Thread-safe operations
    - Handler metadata tracking
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._pattern_handlers: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._lock = Lock()
        self._handler_counter = 0

    def register_handler(
        self,
        routing_key: str,
        handler: Optional[Callable],
        name: Optional[str] = None,
        handler_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Register a handler for a routing key.

        Args:
            routing_key: Routing key pattern (supports wildcards like "user.*")
            handler: Handler function to call (None for remote task proxies)
            name: Optional custom handler name
            handler_id: Optional custom handler ID
            metadata: Optional metadata to store with handler

        Returns:
            Unique handler ID

        Raises:
            SubscriptionError: If registration fails
        """
        with self._lock:
            try:
                self._handler_counter += 1

                if handler_id is None:
                    handler_id = f"handler_{self._handler_counter}"

                if name is None:
                    name = f"{getattr(handler, '__name__', 'handler')}_{self._handler_counter}"

                handler_info = {
                    "id": handler_id,
                    "name": name,
                    "function": handler,
                    "routing_key": routing_key,
                    "metadata": metadata or {},
                }

                # Check if routing_key contains wildcards
                if "*" in routing_key or "?" in routing_key:
                    self._pattern_handlers[routing_key].append(handler_info)
                    logger.info(
                        f"Registered pattern handler '{name}' for routing key pattern '{routing_key}'"
                    )
                else:
                    self._handlers[routing_key].append(handler_info)
                    logger.info(
                        f"Registered handler '{name}' for routing key '{routing_key}'"
                    )

                return handler_info["id"]

            except Exception as e:
                logger.error(
                    f"Failed to register handler for routing key '{routing_key}': {e}",
                    exc_info=True,
                )
                raise SubscriptionError(f"Failed to register handler: {e}")

    def get_handlers(self, routing_key: str) -> List[Dict[str, Any]]:
        """
        Get all handlers for a specific routing key.

        Args:
            routing_key: Exact routing key

        Returns:
            List of handler info dictionaries
        """
        with self._lock:
            handlers = []

            # Add exact match handlers
            handlers.extend(self._handlers.get(routing_key, []))

            # Add pattern match handlers
            for pattern, pattern_handlers in self._pattern_handlers.items():
                if self._matches_pattern(routing_key, pattern):
                    handlers.extend(pattern_handlers)

            return handlers

    def unregister_handler(self, handler_id: str) -> bool:
        """
        Unregister a handler by ID.

        Args:
            handler_id: Handler ID returned by register_handler

        Returns:
            True if handler was found and removed, False otherwise
        """
        with self._lock:
            # Search in exact handlers
            for routing_key, handlers in self._handlers.items():
                for i, handler_info in enumerate(handlers):
                    if handler_info["id"] == handler_id:
                        removed_handler = handlers.pop(i)
                        logger.info(
                            f"Unregistered handler '{removed_handler['name']}' from routing key '{routing_key}'"
                        )
                        return True

            # Search in pattern handlers
            for pattern, handlers in self._pattern_handlers.items():
                for i, handler_info in enumerate(handlers):
                    if handler_info["id"] == handler_id:
                        removed_handler = handlers.pop(i)
                        logger.info(
                            f"Unregistered pattern handler '{removed_handler['name']}' from pattern '{pattern}'"
                        )
                        return True

            return False

    def get_all_routing_keys(self) -> List[str]:
        """Get all registered routing keys (exact matches only)."""
        with self._lock:
            return list(self._handlers.keys())

    def get_all_patterns(self) -> List[str]:
        """Get all registered routing key patterns."""
        with self._lock:
            return list(self._pattern_handlers.keys())

    def get_all_routing_keys_and_patterns(self) -> List[str]:
        """
        Get all registered routing keys and patterns (combined).

        Returns:
            List of all routing keys and patterns that have handlers registered
        """
        with self._lock:
            all_keys = list(self._handlers.keys()) + list(self._pattern_handlers.keys())
            return list(set(all_keys))  # Remove duplicates

    def get_handler_count(self, routing_key: Optional[str] = None) -> int:
        """
        Get count of handlers.

        Args:
            routing_key: Optional specific routing key to count handlers for

        Returns:
            Number of handlers
        """
        with self._lock:
            if routing_key is None:
                # Count all handlers
                total = sum(len(handlers) for handlers in self._handlers.values())
                total += sum(
                    len(handlers) for handlers in self._pattern_handlers.values()
                )
                return total
            else:
                # Count handlers for specific routing key
                count = 0

                # Add exact match handlers
                count += len(self._handlers.get(routing_key, []))

                # Add pattern match handlers
                for pattern, pattern_handlers in self._pattern_handlers.items():
                    if self._matches_pattern(routing_key, pattern):
                        count += len(pattern_handlers)

                return count

    def clear(self) -> None:
        """Clear all registered handlers."""
        with self._lock:
            self._handlers.clear()
            self._pattern_handlers.clear()
            self._handler_counter = 0
            logger.info("Cleared all registered handlers")

    def _matches_pattern(self, routing_key: str, pattern: str) -> bool:
        """
        Check if a routing key matches a wildcard pattern.

        Args:
            routing_key: Routing key to check
            pattern: Pattern with wildcards (* and ?)

        Returns:
            True if routing key matches pattern
        """
        # Convert wildcard pattern to regex
        # * matches any sequence of characters
        # ? matches any single character
        regex_pattern = pattern.replace(".", r"\.").replace("*", ".*").replace("?", ".")
        regex_pattern = f"^{regex_pattern}$"

        try:
            return bool(re.match(regex_pattern, routing_key))
        except re.error:
            logger.warning(f"Invalid pattern '{pattern}', treating as exact match")
            return routing_key == pattern


# Global registry instance
_global_registry = TopicRegistry()


def get_registry() -> TopicRegistry:
    """Get the global topic registry instance."""
    return _global_registry
