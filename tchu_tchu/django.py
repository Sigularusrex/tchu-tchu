"""Django integration helpers for tchu-tchu."""

import importlib
from typing import List, Optional
from kombu import Exchange, Queue, binding

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

    @celery_app.on_after_configure.connect
    def _setup_tchu_queue(sender, **kwargs):
        """Configure tchu-tchu queue bindings after Celery is configured."""

        # Import subscriber modules NOW (after Django is ready)
        # This ensures @subscribe decorators execute and register handlers
        logger.info("=" * 80)
        logger.info(f"🚀 TCHU-TCHU SETUP: {queue_name}")
        logger.info("=" * 80)

        for module in subscriber_modules:
            logger.info(f"📦 Importing subscriber module: {module}")
            try:
                importlib.import_module(module)
            except Exception as e:
                logger.error(f"❌ Failed to import {module}: {e}", exc_info=True)
                raise

        # Collect all routing keys from registered handlers
        from tchu_tchu.registry import get_registry

        registry = get_registry()
        all_routing_keys = get_subscribed_routing_keys()

        logger.info(f"📊 Total handlers registered: {registry.get_handler_count()}")
        logger.info(f"🔑 Total unique routing keys: {len(all_routing_keys)}")
        if all_routing_keys:
            logger.info(f"🔑 Sample routing keys: {sorted(all_routing_keys)[:10]}...")
        logger.info("=" * 80)

        # Create topic exchange
        tchu_exchange = Exchange(exchange_name, type=exchange_type, durable=durable)

        # Build bindings for each routing key
        all_bindings = [
            binding(tchu_exchange, routing_key=key) for key in all_routing_keys
        ]

        # Configure queue
        sender.conf.task_queues = (
            Queue(
                queue_name,
                exchange=tchu_exchange,
                bindings=all_bindings,
                durable=durable,
                auto_delete=auto_delete,
            ),
        )

        # Route dispatcher task to this queue
        sender.conf.task_routes = {
            "tchu_tchu.dispatch_event": {
                "queue": queue_name,
                "exchange": exchange_name,
                "routing_key": "tchu_tchu.dispatch_event",
            },
        }

        # Set default exchange for cross-service messaging
        sender.conf.task_default_exchange = exchange_name
        sender.conf.task_default_exchange_type = exchange_type
        sender.conf.task_default_routing_key = "tchu_tchu.dispatch_event"

        logger.info(f"✅ Tchu-tchu queue '{queue_name}' configured successfully")

    # Create the dispatcher task (registers tchu_tchu.dispatch_event)
    create_topic_dispatcher(celery_app)
