"""
tchu-tchu: A modern Celery-based messaging library with Pydantic serialization and Django integration.

This package provides a modern alternative to the original tchu package, leveraging Celery's
robust task management system while maintaining backward compatibility through a familiar API.
"""

from tchu_tchu.client import TchuClient
from tchu_tchu.producer import CeleryProducer
from tchu_tchu.subscriber import subscribe
from tchu_tchu.events import TchuEvent
from tchu_tchu.version import __version__

__all__ = [
    "TchuClient",
    "CeleryProducer",
    "subscribe",
    "TchuEvent",
    "__version__",
]
