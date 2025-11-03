# Celery Configuration Template for tchu-tchu

## Recommended Pattern: Manual Imports

This pattern works reliably in **all environments** (local, production, GCP).

```python
# your_service/celery.py

from celery import Celery
from kombu import Exchange, Queue, binding
from tchu_tchu import create_topic_dispatcher, get_subscribed_routing_keys

# 1. Create Celery app
app = Celery(
    "your_service_name",  # Replace with your service name
)

# 2. Load Django settings (if using Django)
app.config_from_object("django.conf:settings", namespace="CELERY")

# 3. Configure broker URL (if not in settings)
# app.conf.broker_url = "amqp://guest:guest@rabbitmq:5672//"

# 4. Define the topic exchange (MUST be "tchu_events" across all services)
tchu_exchange = Exchange("tchu_events", type="topic", durable=True)

# 5. ✅ MANUALLY IMPORT ALL SUBSCRIBER MODULES
# Add one import line for each subscriber file that contains @subscribe decorators
import your_service.subscribers.example_subscriber  # noqa
import your_service.subscribers.user_subscriber  # noqa
import your_service.subscribers.order_subscriber  # noqa
# Add more as needed...

# 6. Get routing keys from registered handlers
all_routing_keys = get_subscribed_routing_keys()

# Optional: Log routing keys for debugging
print(f"📋 Registered routing keys: {all_routing_keys}")

# 7. Create bindings for each routing key
all_bindings = [
    binding(tchu_exchange, routing_key=key) 
    for key in all_routing_keys
]

# 8. Configure queue with bindings
app.conf.task_queues = (
    Queue(
        "your_service_queue",  # Replace with unique queue name
        exchange=tchu_exchange,
        bindings=all_bindings,
        durable=True,
        auto_delete=False,
    ),
)

# 9. Route the dispatcher task to your queue
app.conf.task_routes = {
    "tchu_tchu.dispatch_event": {"queue": "your_service_queue"},
}

# 10. Create the dispatcher (registers the tchu_tchu.dispatch_event task)
dispatcher = create_topic_dispatcher(app)

# 11. Optional: Additional Celery configuration
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
```

## Example Subscriber File

```python
# your_service/subscribers/example_subscriber.py

from tchu_tchu import subscribe
import logging

logger = logging.getLogger(__name__)

# RPC handler - MUST return a value
@subscribe('rpc.your_service.resource.action')
def handle_rpc_request(data):
    """Handle RPC request."""
    logger.info(f"Handling RPC request: {data}")
    
    # Your business logic here
    result = process_data(data)
    
    # MUST return a value for RPC handlers
    return {
        "status": "success",
        "result": result
    }

# Broadcast event handler - can return None
@subscribe('other_service.event.created')
def handle_event(data):
    """Handle broadcast event."""
    logger.info(f"Received event: {data}")
    
    # Your business logic here
    process_event(data)
    
    # No need to return anything for broadcast events
```

## Real-World Example: CS Pulse Service

```python
# cs_pulse/celery.py

from celery import Celery
from kombu import Exchange, Queue, binding
from tchu_tchu import create_topic_dispatcher, get_subscribed_routing_keys

app = Celery("cs_pulse")
app.config_from_object("django.conf:settings", namespace="CELERY")

tchu_exchange = Exchange("tchu_events", type="topic", durable=True)

# ✅ Manually import all subscriber modules
import cs_pulse.subscribers.document_subscriber  # noqa
import cs_pulse.subscribers.user_subscriber  # noqa
import cs_pulse.subscribers.compliance_subscriber  # noqa

# Get routing keys
all_routing_keys = get_subscribed_routing_keys()

# Create bindings
all_bindings = [binding(tchu_exchange, routing_key=key) for key in all_routing_keys]

# Configure queue
app.conf.task_queues = (
    Queue(
        "cs_pulse_queue",
        exchange=tchu_exchange,
        bindings=all_bindings,
        durable=True,
        auto_delete=False,
    ),
)

# Route dispatcher
app.conf.task_routes = {
    "tchu_tchu.dispatch_event": {"queue": "cs_pulse_queue"},
}

# Create dispatcher
dispatcher = create_topic_dispatcher(app)
```

## Why Manual Imports?

### ✅ Advantages
- Works in local development (Django runserver)
- Works in production (GCP, Kubernetes, Cloud Run)
- No timing issues with `autodiscover_tasks()`
- No conflicts with Django auto-reload
- More explicit - you can see what's imported
- Easier to debug
- No "No handlers found" errors

### ❌ Disadvantages
- Requires manual maintenance when adding new subscriber files
- A few extra lines of code

### Comparison with Other Approaches

| Approach | Local Dev | Production | Explicit | Maintenance |
|----------|-----------|------------|----------|-------------|
| **Manual imports** | ✅ Works | ✅ Works | ✅ Yes | ⚠️ Manual |
| `celery_app=app` | ❌ May fail | ✅ Works | ⚠️ Hidden | ✅ Auto |
| `autodiscover_tasks()` only | ❌ Fails | ❌ Fails | ⚠️ Hidden | ✅ Auto |

## Troubleshooting

### "No handlers found for routing key"

**Cause:** Handler module not imported.

**Solution:** Add import to celery.py:
```python
import your_service.subscribers.missing_subscriber  # noqa
```

### Handler not registered in logs

**Check logs for:**
```
INFO:tchu_tchu.registry:Registered handler 'handle_document_list' for routing key 'rpc.cs_pulse.documents.document.list'
```

**If missing:** The module wasn't imported. Add it to celery.py.

### Import order matters

Always import subscriber modules **BEFORE** calling `get_subscribed_routing_keys()`:

```python
# ✅ Correct order
import your_service.subscribers.example_subscriber  # noqa
all_routing_keys = get_subscribed_routing_keys()

# ❌ Wrong order
all_routing_keys = get_subscribed_routing_keys()
import your_service.subscribers.example_subscriber  # noqa - TOO LATE!
```

## Running the Worker

```bash
# Development
celery -A your_service worker -l info

# Production
celery -A your_service worker -l info --concurrency=4

# With autoreload (development only)
watchmedo auto-restart -d . -p '*.py' -- celery -A your_service worker -l info
```

## Verification

After starting your worker, check:

1. **Handler registration logs:**
   ```
   INFO:tchu_tchu.registry:Registered handler 'handle_document_list' for routing key 'rpc.cs_pulse.documents.document.list'
   ```

2. **RabbitMQ bindings:**
   ```bash
   docker exec -it rabbitmq3 rabbitmqctl list_bindings | grep your_service_queue
   ```

3. **Test RPC call:**
   ```python
   from tchu_tchu import TchuClient
   client = TchuClient()
   result = client.call('rpc.your_service.test', {'test': 'data'})
   ```

## Related Documentation

- [Migration Guide](./MIGRATION_2.2.11.md)
- [Troubleshooting Guide](./TROUBLESHOOTING_RPC_HANDLERS.md)
- [Main README](./README.md)

