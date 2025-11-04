# Django Helper - v2.2.12 Summary

## What Changed

Added a new `setup_celery_queue()` helper function that dramatically simplifies Django + Celery + tchu-tchu integration.

## Before (60+ lines of boilerplate)

```python
# myapp/celery.py
from __future__ import absolute_import, unicode_literals

import os
import django
import logging
import importlib

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue, binding
from tchu_tchu import create_topic_dispatcher, get_subscribed_routing_keys
from tchu_tchu.registry import get_registry
from tchu_tchu.events import TchuEvent

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.production")
django.setup()

app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Set context helper
def create_context(event_data):
    # ... context reconstruction logic ...
    pass

TchuEvent.set_context_helper(create_context)

# Configure exchange
tchu_exchange = Exchange("tchu_events", type="topic", durable=True)

@app.on_after_configure.connect
def setup_tchu_queue(sender, **kwargs):
    logger = logging.getLogger(__name__)
    
    # Import subscriber modules
    for module in [
        "app1.subscribers",
        "app2.subscribers",
        "app3.subscribers",
    ]:
        importlib.import_module(module)
    
    registry = get_registry()
    all_routing_keys = get_subscribed_routing_keys()
    
    logger.info("=" * 80)
    logger.info("🔧 CELERY QUEUE CONFIGURATION")
    # ... logging ...
    logger.info("=" * 80)
    
    # Build bindings
    all_bindings = [binding(tchu_exchange, routing_key=key) for key in all_routing_keys]
    
    # Configure queues
    sender.conf.task_queues = (
        Queue(
            "my_queue",
            exchange=tchu_exchange,
            bindings=all_bindings,
            durable=True,
            auto_delete=False,
        ),
    )

app.conf.task_routes = {
    "tchu_tchu.dispatch_event": {
        "queue": "my_queue",
        "exchange": "tchu_events",
        "routing_key": "tchu_tchu.dispatch_event",
    },
}

app.conf.task_default_exchange = "tchu_events"
app.conf.task_default_exchange_type = "topic"
app.conf.task_default_routing_key = "tchu_tchu.dispatch_event"

dispatcher = create_topic_dispatcher(app)
```

## After (ONE FUNCTION CALL!)

```python
# myapp/celery.py
from __future__ import absolute_import, unicode_literals

import os
import django

from celery import Celery
from tchu_tchu import setup_celery_queue
from tchu_tchu.events import TchuEvent

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.production")
django.setup()

app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Optional: Set context helper
def create_context(event_data):
    # ... context reconstruction logic ...
    pass

TchuEvent.set_context_helper(create_context)

# ONE LINE to set up everything! 🎉
setup_celery_queue(
    app,
    queue_name="my_queue",
    subscriber_modules=[
        "app1.subscribers",
        "app2.subscribers",
        "app3.subscribers",
    ],
)
```

## What `setup_celery_queue()` Does

1. **Imports subscriber modules** after Django is ready (avoids `AppRegistryNotReady` errors)
2. **Collects routing keys** from all registered `@subscribe` handlers
3. **Creates queue bindings** to the `tchu_events` exchange
4. **Configures Celery** queues and task routes automatically
5. **Sets up RPC messaging** with proper exchange configuration for cross-service calls
6. **Creates dispatcher task** (`tchu_tchu.dispatch_event`)
7. **Logs configuration** for debugging

## Benefits

✅ **60+ lines → 8 lines** - Massive reduction in boilerplate  
✅ **No manual imports** - Subscriber modules loaded automatically  
✅ **No timing issues** - Properly handles Django initialization  
✅ **No exchange config** - Sets up RPC messaging correctly  
✅ **No dispatcher creation** - Handled automatically  
✅ **Better logging** - Consistent debug information  
✅ **Easier maintenance** - One function to update vs scattered config  

## API Reference

```python
from tchu_tchu import setup_celery_queue

setup_celery_queue(
    celery_app,
    queue_name,
    subscriber_modules,
    exchange_name='tchu_events',      # Optional
    exchange_type='topic',            # Optional
    durable=True,                     # Optional
    auto_delete=False                 # Optional
)
```

**Parameters:**
- `celery_app`: Celery app instance
- `queue_name`: Name of the queue (e.g., "my_app_queue")
- `subscriber_modules`: List of module paths (e.g., `["app1.subscribers", "app2.subscribers"]`)
- `exchange_name`: RabbitMQ exchange name (default: "tchu_events")
- `exchange_type`: Exchange type (default: "topic")
- `durable`: Whether queue is durable (default: True)
- `auto_delete`: Whether queue auto-deletes (default: False)

## Migration

**Existing code still works!** This is an optional simplification.

To migrate:

1. Replace the entire `@app.on_after_configure.connect` block with one `setup_celery_queue()` call
2. Remove unused imports (`importlib`, `logging`, `kombu`, `get_registry`, etc.)
3. Remove manual `dispatcher = create_topic_dispatcher(app)` call

**Before and after configurations are functionally identical** - this is purely a developer experience improvement.

## Files Changed

### In tchu-tchu library:

1. **`tchu_tchu/django.py`** (NEW) - Contains `setup_celery_queue()` helper
2. **`tchu_tchu/__init__.py`** - Exports `setup_celery_queue`
3. **`README.md`** - Updated Quick Start, API Reference, and Changelog
4. **Package rebuilt** - v2.2.12 published

### In consuming apps (cs-api, cs-pulse):

1. **`celery.py`** - Simplified from ~80 lines to ~30 lines
2. **Removed imports**: `importlib`, `logging`, `kombu`, `get_registry`, `get_subscribed_routing_keys`, `create_topic_dispatcher`
3. **Removed code**: Entire `@app.on_after_configure.connect` decorator block

## Testing

To verify the setup works:

```bash
# 1. Install updated tchu-tchu in your app
pip install --upgrade /path/to/tchu-tchu/dist/tchu_tchu-2.2.12-py3-none-any.whl

# 2. Start Celery worker
celery -A myapp worker -l info

# 3. Check logs for confirmation
# Should see:
# [INFO] 🚀 TCHU-TCHU SETUP: my_queue
# [INFO] 📦 Importing subscriber module: app1.subscribers
# [INFO] 📊 Total handlers registered: 43
# [INFO] 🔑 Total unique routing keys: 43
# [INFO] ✅ Tchu-tchu queue 'my_queue' configured successfully

# 4. Test event publishing
python manage.py tchu_test_publish

# 5. Verify RPC calls work
# (Test your existing RPC endpoints)
```

## Backward Compatibility

✅ **100% backward compatible** - existing configurations continue to work  
✅ **Optional migration** - upgrade at your own pace  
✅ **No breaking changes** - all existing APIs unchanged  

## Next Steps

1. **cs-api**: Already updated ✅
2. **cs-pulse**: Already updated ✅
3. **Other services**: Can adopt the new pattern when convenient

## Documentation

- Full README updated with Django Quick Start section
- API Reference section includes `setup_celery_queue()`
- Changelog updated to v2.2.12

## Impact

**Before this change:**
- Every microservice had 60-80 lines of complex Celery configuration
- Easy to make mistakes in timing (Django not ready, imports too early)
- Hard to maintain consistency across services
- Exchange configuration for RPC often wrong or missing

**After this change:**
- One function call does everything correctly
- Timing handled automatically
- Consistent configuration across all services
- RPC messaging configured properly by default

This brings tchu-tchu's ease of use on par with the original tchu library while maintaining all the power and flexibility of v2.x!

