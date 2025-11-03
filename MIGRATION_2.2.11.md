# Migration Guide: tchu-tchu v2.2.11

## Overview

Version 2.2.11 fixes a critical issue where **broadcast events were not being received** by services due to incorrect RabbitMQ queue bindings.

### The Problem

`get_subscribed_routing_keys()` was being called **before** handlers were registered because `app.autodiscover_tasks()` is lazy. This resulted in:
- Empty routing key list `[]`
- Queues created with incorrect bindings (exact match only)
- **RPC calls worked**, but **broadcast events failed**

### The Fix

`get_subscribed_routing_keys()` now accepts a `celery_app` parameter to force immediate task discovery, ensuring handlers are registered before queue configuration.

---

## Upgrade Steps

### 1. Update tchu-tchu

```bash
pip install tchu-tchu==2.2.11
# or
poetry add tchu-tchu@2.2.11
```

### 2. Update Your Celery Configuration

**Before (v2.2.9):**
```python
from tchu_tchu import get_subscribed_routing_keys

app = Celery("my_service")
app.autodiscover_tasks(["my_service.subscribers"])

# This returns [] because handlers aren't registered yet!
all_routing_keys = get_subscribed_routing_keys()
```

**After (v2.2.11) - Option 1: Manual Imports (Recommended):**
```python
from tchu_tchu import get_subscribed_routing_keys

app = Celery("my_service")

# ✅ RECOMMENDED: Explicitly import all subscriber modules
import my_service.subscribers.user_subscriber  # noqa
import my_service.subscribers.order_subscriber  # noqa
import my_service.subscribers.other_subscriber  # noqa

# Now get routing keys - handlers are already registered
all_routing_keys = get_subscribed_routing_keys()
```

**After (v2.2.11) - Option 2: Pass celery_app (Production only):**
```python
from tchu_tchu import get_subscribed_routing_keys

app = Celery("my_service")
app.autodiscover_tasks(["my_service.subscribers"])

# Pass celery_app to force immediate handler registration (may cause issues locally)
all_routing_keys = get_subscribed_routing_keys(celery_app=app)
```

### 3. Delete Old Queues (CRITICAL)

Old queues have **incorrect persistent bindings** that won't update automatically. Delete them:

```bash
# Connect to RabbitMQ container
docker exec -it <rabbitmq-container> bash

# Delete the queue (replace with your queue name)
rabbitmqctl delete_queue scranton_queue
rabbitmqctl delete_queue data_room_queue
rabbitmqctl delete_queue pulse_queue
rabbitmqctl delete_queue coolset_queue

# Exit container
exit
```

### 4. Restart Services

After deleting queues, restart your services. They will recreate queues with **correct bindings**.

```bash
docker-compose restart scranton
docker-compose restart data-room
docker-compose restart pulse
docker-compose restart coolset
```

### 5. Verify Bindings

Check that queues now have correct wildcard bindings:

```bash
docker exec -it <rabbitmq-container> bash
rabbitmqctl list_bindings | grep "your_queue_name"
```

**Expected output:**
```
tchu_events  exchange  scranton_queue  queue  coolset.scranton.#  []
tchu_events  exchange  scranton_queue  queue  pulse.compliance.risk_assessment.completed  []
tchu_events  exchange  scranton_queue  queue  coolset.global.storage.save_object_to_bucket  []
```

**NOT this:**
```
tchu_events  exchange  scranton_queue  queue  scranton  []  # ❌ Wrong!
```

---

## Example Celery Configurations

### Scranton Service

```python
from celery import Celery
from kombu import Exchange, Queue, binding
from tchu_tchu import create_topic_dispatcher, get_subscribed_routing_keys

app = Celery(
    "scranton",
    include=["scranton", "eudr", "cs_pulse_consumer"],
)

app.config_from_object("django.conf:settings", namespace="CELERY")

# Configure topic exchange
tchu_exchange = Exchange("tchu_events", type="topic", durable=True)

# ✅ RECOMMENDED: Manually import all subscriber modules
import scranton.subscribers.information_request_subscriber  # noqa
import scranton.subscribers.value_chain_subscriber  # noqa
import scranton.subscribers.data_import_subscriber  # noqa
import cs_pulse_consumer.subscribers.risk_assessment_subscriber  # noqa
import cs_pulse_consumer.subscribers.storage_subscriber  # noqa
import eudr.subscribers.order_subscriber  # noqa

# Get routing keys from registered handlers
all_routing_keys = get_subscribed_routing_keys()

# Build bindings from registered handlers
all_bindings = [binding(tchu_exchange, routing_key=key) for key in all_routing_keys]

# Configure queue
app.conf.task_queues = (
    Queue(
        "scranton_queue",
        exchange=tchu_exchange,
        bindings=all_bindings,
        durable=True,
        auto_delete=False,
    ),
)

# Route dispatcher
app.conf.task_routes = {
    "tchu_tchu.dispatch_event": {"queue": "scranton_queue"},
}

# Create dispatcher
dispatcher = create_topic_dispatcher(app)
```

### Data Room Service

```python
from celery import Celery
from kombu import Exchange, Queue, binding
from tchu_tchu import create_topic_dispatcher, get_subscribed_routing_keys

app = Celery(
    "data_room",
    include=["data_room", "data_room.subscribers.observability_subscriber"],
)

app.config_from_object("django.conf:settings", namespace="CELERY")

tchu_exchange = Exchange("tchu_events", type="topic", durable=True)

# ✅ RECOMMENDED: Manually import all subscriber modules
import data_room.subscribers.document_subscriber  # noqa
import data_room.subscribers.observability_subscriber  # noqa
import cs_eunice_consumer.subscribers.eunice_subscriber  # noqa
import cs_pulse_consumer.subscribers.compliance_subscriber  # noqa

# Get routing keys from registered handlers
all_routing_keys = get_subscribed_routing_keys()

all_bindings = [binding(tchu_exchange, routing_key=key) for key in all_routing_keys]

app.conf.task_queues = (
    Queue(
        "data_room_queue",
        exchange=tchu_exchange,
        bindings=all_bindings,
        durable=True,
        auto_delete=False,
    ),
)

app.conf.task_routes = {
    "tchu_tchu.dispatch_event": {"queue": "data_room_queue"},
}

dispatcher = create_topic_dispatcher(app)
```

---

## Recommended Approach: Manual Imports

**This is the most reliable approach** and works in all environments (local, production, GCP):

```python
from tchu_tchu import get_subscribed_routing_keys

# ✅ Explicit imports (forces immediate handler registration)
import scranton.subscribers.information_request_subscriber  # noqa
import scranton.subscribers.value_chain_subscriber  # noqa
import scranton.subscribers.data_import_subscriber  # noqa
import cs_pulse_consumer.subscribers.risk_assessment_subscriber  # noqa
import cs_pulse_consumer.subscribers.storage_subscriber  # noqa

# Now get keys (no celery_app needed)
all_routing_keys = get_subscribed_routing_keys()
```

**Why this is best:**
- ✅ Works in local development and production
- ✅ No timing issues with autodiscover_tasks()
- ✅ No conflicts with Django runserver auto-reload
- ✅ More explicit - you can see what's imported
- ✅ Easier to debug
- ❌ Requires manual maintenance when adding new subscribers (but that's minor)

**Note:** If you use `celery_app=app` locally with Django runserver, you may see "No handlers found" errors due to double-import timing issues. Manual imports avoid this problem entirely.

---

## Testing

### Test RPC (Should Already Work)

```python
# In pulse-web or any client
from tchu_tchu import CeleryProducer

producer = CeleryProducer(app)
result = producer.call(
    routing_key="rpc.data_room.documents.list",
    payload={"company_id": 67},
    timeout=10,
)
print(result)  # Should return document list
```

### Test Broadcast Events (NOW FIXED)

```python
# Publisher (e.g., scranton)
from tchu_tchu import CeleryProducer

producer = CeleryProducer(app)
producer.publish(
    routing_key="coolset.scranton.order.enriched",
    payload={
        "order_id": 123,
        "company_id": 67,
    },
)

# Subscriber (e.g., eudr)
# Should see handler execute in logs:
# INFO:tchu_tchu.dispatcher:Dispatching event 'coolset.scranton.order.enriched' to 1 handler(s)
```

---

## Troubleshooting

### "Still seeing empty routing keys []"

**Problem:** `get_subscribed_routing_keys()` returns `[]`

**Solution:** Ensure you're passing `celery_app=app`:
```python
all_routing_keys = get_subscribed_routing_keys(celery_app=app)
```

### Context Helper TypeError

**Problem:** `TypeError: context_helper() takes 1 positional argument but 2 were given`

**Cause:** You passed a bound method instead of a standalone function to `TchuEvent.set_context_helper()`.

**Solution:**
```python
# ❌ WRONG - Don't pass bound methods
class MyClass:
    def my_helper(self, event_data):
        return {}

obj = MyClass()
TchuEvent.set_context_helper(obj.my_helper)  # ❌ Will fail

# ✅ CORRECT - Use standalone functions
def my_context_helper(event_data):
    return create_context(event_data)

TchuEvent.set_context_helper(my_context_helper)  # ✅ Works

# ✅ WORKAROUND - Handle both signatures (for older code)
def safe_context_helper(*args, **kwargs):
    """Backwards-compatible helper that handles both signatures."""
    event_data = args[1] if len(args) >= 2 else args[0]
    return create_request_context_from_event(event_data)

TchuEvent.set_context_helper(safe_context_helper)
```

### "Events still not received"

**Problem:** Broadcast events published but not received

**Checklist:**
1. ✅ Updated to tchu-tchu v2.2.11
2. ✅ Added `celery_app=app` parameter
3. ✅ Deleted old queues from RabbitMQ
4. ✅ Restarted all services
5. ✅ Verified bindings with `rabbitmqctl list_bindings`

### "RabbitMQ bindings show exact match instead of wildcards"

**Problem:** `rabbitmqctl list_bindings` shows:
```
tchu_events  exchange  scranton_queue  queue  scranton  []
```

**Solution:** 
1. Delete the queue: `rabbitmqctl delete_queue scranton_queue`
2. Ensure `get_subscribed_routing_keys(celery_app=app)` is called
3. Restart service to recreate queue with correct bindings

---

## Performance Impact

- **Startup time**: +100-500ms (one-time, during service initialization)
- **Runtime performance**: No impact (happens once at startup)
- **Memory**: Negligible

The performance cost is minimal compared to the debugging time saved from broken broadcast events!

---

## Questions?

If you encounter issues:
1. Check that handlers are registered: Look for logs like:
   ```
   INFO:tchu_tchu.registry:Registered handler 'MyHandler' for routing key 'my.routing.key'
   ```
2. Verify queue bindings in RabbitMQ match your handler routing keys
3. Ensure you deleted old queues before restarting

---

## Summary

| Change | Before | After |
|--------|--------|-------|
| **Library version** | 2.2.9 | 2.2.11 |
| **get_subscribed_routing_keys()** | `get_subscribed_routing_keys()` | `get_subscribed_routing_keys(celery_app=app)` |
| **Queue bindings** | Exact match (broken) | Wildcard patterns (correct) |
| **RPC** | ✅ Works | ✅ Works |
| **Broadcast events** | ❌ Broken | ✅ Fixed |

**Action Required:**
1. Update tchu-tchu to v2.2.11
2. Add `celery_app=app` parameter
3. Delete old queues from RabbitMQ
4. Restart services

