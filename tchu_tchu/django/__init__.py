"""Django integration utilities for tchu-tchu."""

from tchu_tchu.django.decorators import auto_publish
from tchu_tchu.django.celery import setup_celery_queue

__all__ = ["auto_publish", "setup_celery_queue"]
