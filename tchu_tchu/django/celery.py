"""Celery setup helper for Django + tchu-tchu integration."""

import importlib
from typing import List, Optional

from kombu import Exchange, Queue, binding
from celery import Celery as CeleryCelery
from celery.signals import worker_process_init

from tchu_tchu.subscriber import get_subscribed_routing_keys, create_topic_dispatcher
from tchu_tchu.logging.handlers import get_logger

logger = get_logger(__name__)


def setup_celery_queue(
    celery_app,
    queue_name: str,
    subscriber_modules: List[str],
    exchange_name: str = "tchu_events",
    exchange_type: str = "topic",
    durable: bool = True,
    auto_delete: bool = False,
) -> None:
    """
    Set up Celery queue with tchu-tchu event handlers for Django apps.

    This helper function handles all the boilerplate of:
    1. Importing subscriber modules (after Django is ready)
    2. Collecting routing keys from registered handlers
    3. Creating queue bindings
    4. Configuring Celery queues and task routes
    5. Setting default exchange for cross-service messaging
    6. Creating the dispatcher task

    Usage:
        # In your celery.py
        import django
        django.setup()

        app = Celery("my_app")
        app.config_from_object("django.conf:settings", namespace="CELERY")

        from tchu_tchu.django import setup_celery_queue
        setup_celery_queue(
            app,
            queue_name="my_queue",
            subscriber_modules=[
                "app1.subscribers",
                "app2.subscribers",
            ]
        )

    Args:
        celery_app: Celery app instance
        queue_name: Name of the queue (e.g., "acme_queue", "pulse_queue")
        subscriber_modules: List of module paths containing @subscribe decorators
        exchange_name: RabbitMQ exchange name (default: "tchu_events")
        exchange_type: Exchange type (default: "topic")
        durable: Whether queue is durable (default: True)
        auto_delete: Whether queue auto-deletes (default: False)
    """
    logger.info(f"📞 setup_celery_queue() called for queue: {queue_name}")

    # Register a worker_process_init signal handler to import modules when worker starts
    # This ensures Django is fully ready before importing subscriber modules
    @worker_process_init.connect
    def _import_subscribers_on_worker_init(sender=None, **kwargs):
        """Import subscriber modules when worker process initializes (Django is ready)."""
        logger.info("=" * 80)
        logger.info(f"🚀 TCHU-TCHU WORKER INIT: {queue_name}")
        logger.info("=" * 80)

        for module in subscriber_modules:
            logger.info(f"📦 Importing subscriber module: {module}")
            try:
                importlib.import_module(module)
            except Exception as e:
                logger.error(f"❌ Failed to import {module}: {e}", exc_info=True)

        from tchu_tchu.registry import get_registry

        registry = get_registry()
        logger.info(f"📊 Total handlers registered: {registry.get_handler_count()}")
        logger.info("=" * 80)

    # Try to import modules NOW to get routing keys for queue configuration
    # If Django isn't ready, skip and let worker_process_init handle it
    for module in subscriber_modules:
        try:
            importlib.import_module(module)
        except Exception as e:
            # Check if it's a Django not ready error (check exception type and message)
            exception_str = str(type(e).__name__) + " " + str(e)
            if (
                "AppRegistryNotReady" in exception_str
                or "Apps aren't loaded yet" in exception_str
            ):
                logger.info(
                    "⏳ Skipping remaining imports - Django not ready (will import on worker init)"
                )
                break  # Skip remaining modules
            else:
                logger.warning(f"⚠️  Could not import {module}: {e}")

    # Collect all routing keys from registered handlers
    all_routing_keys = get_subscribed_routing_keys()

    # Create topic exchange
    tchu_exchange = Exchange(exchange_name, type=exchange_type, durable=durable)

    # Build bindings for each routing key
    all_bindings = [binding(tchu_exchange, routing_key=key) for key in all_routing_keys]

    # FORCEFULLY override queue config (even if Django settings defined one)
    celery_app.conf.task_queues = (
        Queue(
            queue_name,
            exchange=tchu_exchange,
            bindings=all_bindings,
            durable=durable,
            auto_delete=auto_delete,
        ),
    )

    # Route dispatcher task to this queue
    celery_app.conf.task_routes = {
        "tchu_tchu.dispatch_event": {
            "queue": queue_name,
            "exchange": exchange_name,
            "routing_key": "tchu_tchu.dispatch_event",
        },
    }

    # Set default queue for all tasks (including @celery.shared_task)
    # This ensures regular Celery tasks also go to the service's queue
    celery_app.conf.task_default_queue = queue_name

    # DON'T set task_default_exchange - let regular tasks use direct routing
    # Only tchu-tchu dispatcher events should use the topic exchange
    # Regular @celery.shared_task tasks will use default direct routing to the queue

    # Configure for reliable RPC handling
    # Prefetch multiplier of 1 ensures workers only take one task at a time
    # This prevents race conditions when multiple workers handle the same queue
    # This is the KEY setting that fixes intermittent RPC failures with multiple workers
    celery_app.conf.worker_prefetch_multiplier = 1
    logger.info("🔧 Set worker_prefetch_multiplier=1 for RPC reliability")

    logger.info(f"✅ Tchu-tchu queue '{queue_name}' configured successfully")

    # Create the dispatcher task (registers tchu_tchu.dispatch_event)
    create_topic_dispatcher(celery_app)
    logger.info(f"✅ setup_celery_queue() completed for queue: {queue_name}")


class Celery(CeleryCelery):
    """
    Extended Celery class with tchu-tchu integration.

    This class extends the standard Celery app with tchu-tchu-specific
    functionality, providing a cleaner API for Django projects.

    Usage:
        # In your celery.py
        import django
        django.setup()

        from tchu_tchu.django import Celery

        app = Celery("my_app")
        app.config_from_object("django.conf:settings", namespace="CELERY")

        # Configure message broker with tchu-tchu
        app.message_broker(
            queue_name="my_queue",
            subscriber_modules=[
                "app1.subscribers",
                "app2.subscribers",
            ]
        )

    All standard Celery functionality is preserved - this class simply
    adds convenience methods for tchu-tchu integration.
    """

    def __init__(self, *args, **kwargs):
        """Initialize extended Celery app and capture include parameter."""
        # Capture include parameter before parent constructor processes it
        self.tchu_include = kwargs.get("include", []) or []

        # Call parent constructor
        super().__init__(*args, **kwargs)

    def message_broker(
        self,
        queue_name: str,
        include: Optional[List[str]] = None,
        exchange_name: str = "tchu_events",
        exchange_type: str = "topic",
        durable: bool = True,
        auto_delete: bool = False,
    ) -> None:
        """
        Configure message broker with tchu-tchu event handling.

        This is a convenience method that wraps setup_celery_queue(),
        providing a more Pythonic API by attaching the setup logic
        directly to the Celery app instance.

        Args:
            queue_name: Name of the queue (e.g., "acme_queue", "pulse_queue")
            include: List of full module paths containing @subscribe decorators.
                If not provided, uses Celery's 'include' parameter from constructor.
                Matches Celery's naming convention for consistency.
                Note: Full paths required (e.g., "app1.subscribers", not just "app1")
            exchange_name: RabbitMQ exchange name (default: "tchu_events")
            exchange_type: Exchange type (default: "topic")
            durable: Whether queue is durable (default: True)
            auto_delete: Whether queue auto-deletes (default: False)

        Example:
            # Explicit include modules (full paths)
            app = Celery("my_app")
            app.config_from_object("django.conf:settings", namespace="CELERY")
            app.message_broker(
                queue_name="my_queue",
                include=["app1.subscribers", "app2.subscribers"]
            )

            # Auto-discover from Celery's include parameter (full paths)
            app = Celery("my_app", include=["app1.subscribers", "app2.subscribers"])
            app.config_from_object("django.conf:settings", namespace="CELERY")
            app.message_broker(queue_name="my_queue")  # Uses app1.subscribers, app2.subscribers
        """
        # If include not provided, use stored include from Celery constructor
        subscriber_modules = include if include is not None else self.tchu_include

        if subscriber_modules:
            logger.info(f"📦 Using subscriber modules: {subscriber_modules}")

        setup_celery_queue(
            celery_app=self,
            queue_name=queue_name,
            subscriber_modules=subscriber_modules,
            exchange_name=exchange_name,
            exchange_type=exchange_type,
            durable=durable,
            auto_delete=auto_delete,
        )
