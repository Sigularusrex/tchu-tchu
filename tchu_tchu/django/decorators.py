"""Django model decorators for automatic event publishing."""

from typing import List, Optional, Callable, Any, Dict, Union
from functools import wraps

from tchu_tchu.client import TchuClient
from tchu_tchu.logging.handlers import get_logger
from tchu_tchu.utils.error_handling import PublishError

logger = get_logger(__name__)

try:
    from django.db.models.signals import post_save, post_delete
    from django.db import models

    DJANGO_AVAILABLE = True
except ImportError:
    DJANGO_AVAILABLE = False
    logger.warning("Django not available. Django integration features disabled.")


def auto_publish(
    topic_prefix: Optional[str] = None,
    include_fields: Optional[List[str]] = None,
    exclude_fields: Optional[List[str]] = None,
    publish_on: Optional[List[str]] = None,
    client: Optional[TchuClient] = None,
    condition: Optional[Callable] = None,
):
    """
    Class decorator for Django models that automatically publishes events.

    Args:
        topic_prefix: Optional custom prefix for topics (default: app_name.model_name)
        include_fields: Optional list of fields to include in event payload
        exclude_fields: Optional list of fields to exclude from event payload
        publish_on: Optional list of events to publish ("created", "updated", "deleted")
        client: Optional TchuClient instance (creates new one if None)
        condition: Optional function to determine if event should be published

    Returns:
        Decorated model class

    Example:
        @auto_publish(
            topic_prefix="pulse.compliance",
            include_fields=["id", "status", "company_id"],
            exclude_fields=["password"],
            publish_on=["created", "updated"]
        )
        class RiskAssessment(models.Model):
            company_id = models.IntegerField()
            status = models.CharField(max_length=50)
            # ... other fields
    """
    if not DJANGO_AVAILABLE:

        def no_op_decorator(cls):
            logger.warning(
                f"Django not available. Skipping auto_publish decorator for {cls.__name__}"
            )
            return cls

        return no_op_decorator

    def decorator(model_class):
        if not issubclass(model_class, models.Model):
            raise ValueError("auto_publish can only be applied to Django Model classes")

        # Get model metadata
        app_label = model_class._meta.app_label
        model_name = model_class._meta.model_name

        # Generate topic prefix if not provided
        if topic_prefix is None:
            base_topic = f"{app_label}.{model_name}"
        else:
            base_topic = f"{topic_prefix}.{model_name}"

        # Default events to publish
        events_to_publish = publish_on or ["created", "updated", "deleted"]

        # Create client if not provided
        event_client = client or TchuClient()

        def get_model_data(
            instance: models.Model, fields_changed: Optional[List[str]] = None
        ) -> Dict[str, Any]:
            """Extract model data for event payload."""
            data = {}

            # Get all field values
            for field in instance._meta.fields:
                field_name = field.name

                # Skip excluded fields
                if exclude_fields and field_name in exclude_fields:
                    continue

                # Include only specified fields if include_fields is set
                if include_fields and field_name not in include_fields:
                    continue

                try:
                    value = getattr(instance, field_name)

                    # Handle special field types
                    if hasattr(value, "isoformat"):  # datetime/date/time
                        data[field_name] = value.isoformat()
                    elif hasattr(value, "__str__"):
                        data[field_name] = str(value) if value is not None else None
                    else:
                        data[field_name] = value

                except Exception as e:
                    logger.warning(f"Failed to get value for field '{field_name}': {e}")
                    continue

            # Add metadata
            data["_meta"] = {
                "app_label": app_label,
                "model_name": model_name,
                "pk": instance.pk,
            }

            if fields_changed:
                data["_meta"]["fields_changed"] = fields_changed

            return data

        def should_publish_event(instance: models.Model, event_type: str) -> bool:
            """Check if event should be published based on condition."""
            if event_type not in events_to_publish:
                return False

            if condition and not condition(instance, event_type):
                return False

            return True

        def publish_event(
            instance: models.Model,
            event_type: str,
            fields_changed: Optional[List[str]] = None,
        ):
            """Publish an event for the model instance."""
            if not should_publish_event(instance, event_type):
                return

            try:
                topic = f"{base_topic}.{event_type}"
                data = get_model_data(instance, fields_changed)

                event_client.publish(topic, data)

                logger.info(
                    f"Published {event_type} event for {model_class.__name__}",
                    extra={"topic": topic, "model_pk": instance.pk},
                )

            except Exception as e:
                logger.error(
                    f"Failed to publish {event_type} event for {model_class.__name__}: {e}",
                    extra={"model_pk": instance.pk},
                    exc_info=True,
                )

        def handle_post_save(sender, instance, created, **kwargs):
            """Handle post_save signal."""
            if created and "created" in events_to_publish:
                publish_event(instance, "created")
            elif not created and "updated" in events_to_publish:
                # Try to determine which fields changed
                fields_changed = None
                if hasattr(instance, "_state") and hasattr(
                    instance._state, "fields_cache"
                ):
                    # This is a best-effort attempt to detect changed fields
                    # In practice, you might want to use django-model-utils or similar
                    pass

                publish_event(instance, "updated", fields_changed)

        def handle_post_delete(sender, instance, **kwargs):
            """Handle post_delete signal."""
            if "deleted" in events_to_publish:
                publish_event(instance, "deleted")

        # Connect signals
        if "created" in events_to_publish or "updated" in events_to_publish:
            post_save.connect(handle_post_save, sender=model_class, weak=False)

        if "deleted" in events_to_publish:
            post_delete.connect(handle_post_delete, sender=model_class, weak=False)

        # Add metadata to the model class
        model_class._tchu_auto_publish_config = {
            "topic_prefix": topic_prefix,
            "base_topic": base_topic,
            "include_fields": include_fields,
            "exclude_fields": exclude_fields,
            "publish_on": events_to_publish,
            "client": event_client,
            "condition": condition,
        }

        logger.info(
            f"Auto-publish configured for {model_class.__name__} with base topic '{base_topic}'"
        )

        return model_class

    return decorator


def get_auto_publish_config(model_class) -> Optional[Dict[str, Any]]:
    """
    Get the auto-publish configuration for a model class.

    Args:
        model_class: Django model class

    Returns:
        Configuration dictionary or None if not configured
    """
    return getattr(model_class, "_tchu_auto_publish_config", None)
