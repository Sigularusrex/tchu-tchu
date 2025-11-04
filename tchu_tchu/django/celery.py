"""Celery setup helper for Django + tchu-tchu integration."""

import importlib
from typing import List

from kombu import Exchange, Queue, binding
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
        queue_name: Name of the queue (e.g., "coolset_queue", "pulse_queue")
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
    from tchu_tchu.registry import get_registry

    registry = get_registry()
    all_routing_keys = get_subscribed_routing_keys()

    logger.info(f"📊 Handlers registered during setup: {registry.get_handler_count()}")
    logger.info(f"🔑 Routing keys for queue bindings: {len(all_routing_keys)}")

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

    # Set default exchange for cross-service messaging
    celery_app.conf.task_default_exchange = exchange_name
    celery_app.conf.task_default_exchange_type = exchange_type
    celery_app.conf.task_default_routing_key = "tchu_tchu.dispatch_event"

    # Configure for reliable RPC handling
    # Prefetch multiplier of 1 ensures workers only take one task at a time
    # This prevents race conditions when multiple workers handle the same queue
    # This is the KEY setting that fixes intermittent RPC failures with multiple workers
    celery_app.conf.worker_prefetch_multiplier = 1
    logger.info(f"🔧 Set worker_prefetch_multiplier=1 for RPC reliability")

    logger.info(f"✅ Tchu-tchu queue '{queue_name}' configured successfully")

    # Create the dispatcher task (registers tchu_tchu.dispatch_event)
    create_topic_dispatcher(celery_app)
    logger.info(f"✅ setup_celery_queue() completed for queue: {queue_name}")
