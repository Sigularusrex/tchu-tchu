"""
tchu-tchu: A modern Celery-based messaging library with broadcast event support.

v2.0.0: Complete redesign using RabbitMQ topic exchanges for true broadcast messaging.
- Multiple apps can subscribe to the same events
- Uses existing Celery workers (no separate listener needed)
- Fast and simple (no task discovery/inspection)
- Compatible with the original tchu architecture
"""

from tchu_tchu.client import TchuClient
from tchu_tchu.producer import CeleryProducer
from tchu_tchu.subscriber import (
    subscribe,
    create_topic_dispatcher,
    get_subscribed_routing_keys,
)
from tchu_tchu.events import TchuEvent
from tchu_tchu.utils.error_handling import TchuRPCException
from tchu_tchu.version import __version__
from tchu_tchu.django import setup_celery_queue

__all__ = [
    "TchuClient",
    "CeleryProducer",
    "subscribe",
    "create_topic_dispatcher",
    "get_subscribed_routing_keys",
    "setup_celery_queue",
    "TchuEvent",
    "TchuRPCException",
    "__version__",
]
