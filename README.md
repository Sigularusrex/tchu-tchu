# tchu-tchu

A modern Celery-based messaging library with **true broadcast support** for microservices. Designed to replicate the simplicity of the original `tchu` library while leveraging Celery workers for execution.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://badge.fury.io/py/tchu-tchu.svg)](https://badge.fury.io/py/tchu-tchu)

## Features

- ✨ **True Broadcast Messaging** - One event reaches multiple microservices
- 🚀 **Uses Existing Celery Workers** - No separate listener process needed
- 🎯 **Topic-based Routing** - RabbitMQ topic exchange with wildcard patterns
- 🔄 **Drop-in Replacement** - Compatible with original `tchu` API
- 📦 **Pydantic Integration** - Type-safe event serialization
- 🛡️ **Django Support** - Built-in Django REST Framework integration
- ⚡ **Fast** - No task discovery or inspection overhead

## Architecture

**How It Works:**

```
┌─────────────┐
│  Publisher  │──┐
│   (Any App) │  │
└─────────────┘  │
                 ▼
         ┌──────────────┐
         │Topic Exchange│ (RabbitMQ)
         │ tchu_events  │
         └──────┬───────┘
                │
        ┌───────┴───────┐
        │               │
        ▼               ▼
   ┌────────┐      ┌────────┐
   │Queue 1 │      │Queue 2 │
   │(App A) │      │(App B) │
   └───┬────┘      └───┬────┘
       │               │
       ▼               ▼
   [Worker A]      [Worker B]
   Receives event  Receives event
```

Each microservice:
1. Creates its own unique queue
2. Binds the queue to the topic exchange with routing key patterns
3. Runs Celery workers that consume from the queue
4. All matching apps receive the same event simultaneously

## Installation

```bash
pip install tchu-tchu
```

## Quick Start

### 1. Configure Celery (Each Microservice)

Each microservice needs to configure its Celery app to consume from a queue bound to the `tchu_events` exchange:

```python
# myapp/celery.py
from celery import Celery
from kombu import Exchange, Queue
from tchu_tchu import create_topic_dispatcher
from tchu_tchu.events import TchuEvent

app = Celery('myapp')

# ===== Configure context helper (for framework integration) =====
# This is optional but recommended if you're using TchuEvent with request_context
# Define your context reconstruction logic once here:
def my_context_helper(event_data):
    """Reconstruct request context from event data."""
    # Your framework-specific logic (Django, Flask, etc.)
    # See "Framework Integration" section for examples
    from types import SimpleNamespace
    user = event_data.get('user')
    if user:
        mock_request = SimpleNamespace()
        mock_request.user = SimpleNamespace(**user)
        return {'request': mock_request}
    return {}

# Set it globally for all events
TchuEvent.set_context_helper(my_context_helper)

# ===== Configure Celery queues and exchange =====
# Define the topic exchange
tchu_exchange = Exchange('tchu_events', type='topic', durable=True)

# Each app has its own unique queue bound to the exchange
app.conf.task_queues = (
    Queue(
        'myapp_queue',                  # Unique queue name for this app
        exchange=tchu_exchange,
        routing_key='user.*',           # Subscribe to user.* events
        durable=True,
        auto_delete=False,
    ),
)

# Route the dispatcher task to your app's queue
app.conf.task_routes = {
    'tchu_tchu.dispatch_event': {'queue': 'myapp_queue'},
}

# Create the dispatcher task (handles incoming events)
dispatcher = create_topic_dispatcher(app)
```

### 2. Subscribe to Events

```python
# myapp/subscribers.py
from tchu_tchu import subscribe

@subscribe('user.created')
def handle_user_created(event_data):
    """This handler will be called when user.created events are published"""
    print(f"User created: {event_data}")
    # Process the event...

@subscribe('user.*')  # Wildcard pattern
def handle_any_user_event(event_data):
    """This handler receives all user.* events"""
    print(f"User event: {event_data}")
```

### 3. Publish Events

```python
# In any microservice
from tchu_tchu import TchuClient

client = TchuClient()

# Publish an event (all subscribed apps receive it)
client.publish('user.created', {
    'user_id': 123,
    'email': 'user@example.com',
    'name': 'John Doe'
})

# RPC call (request-response pattern)
try:
    result = client.call('user.validate', {
        'email': 'user@example.com'
    }, timeout=5)
    print(f"Validation result: {result}")
except TimeoutError:
    print("No response within timeout")
```

## Multiple Microservices Example

### App 1: User Service (Publisher + Subscriber)

```python
# users/celery.py
from celery import Celery
from kombu import Exchange, Queue
from tchu_tchu import create_topic_dispatcher

app = Celery('users')

tchu_exchange = Exchange('tchu_events', type='topic', durable=True)

app.conf.task_queues = (
    Queue('users_queue', exchange=tchu_exchange, routing_key='user.*'),
)

app.conf.task_routes = {
    'tchu_tchu.dispatch_event': {'queue': 'users_queue'},
}

dispatcher = create_topic_dispatcher(app)

# users/subscribers.py
from tchu_tchu import subscribe

@subscribe('user.deleted')
def cleanup_user_data(event):
    print(f"Cleaning up data for user {event['user_id']}")

# users/views.py
from tchu_tchu import TchuClient

client = TchuClient()

def create_user(request):
    user = User.objects.create(...)
    
    # Publish event - all apps receive it!
    client.publish('user.created', {
        'user_id': user.id,
        'email': user.email
    })
    
    return Response(...)
```

### App 2: Notifications Service (Subscriber Only)

```python
# notifications/celery.py
from celery import Celery
from kombu import Exchange, Queue
from tchu_tchu import create_topic_dispatcher

app = Celery('notifications')

tchu_exchange = Exchange('tchu_events', type='topic', durable=True)

app.conf.task_queues = (
    Queue('notifications_queue', exchange=tchu_exchange, routing_key='user.*'),
)

app.conf.task_routes = {
    'tchu_tchu.dispatch_event': {'queue': 'notifications_queue'},
}

dispatcher = create_topic_dispatcher(app)

# notifications/subscribers.py
from tchu_tchu import subscribe

@subscribe('user.created')
def send_welcome_email(event):
    print(f"Sending welcome email to {event['email']}")
    # Send email...
```

### App 3: Analytics Service (Subscriber Only)

```python
# analytics/celery.py
from celery import Celery
from kombu import Exchange, Queue
from tchu_tchu import create_topic_dispatcher

app = Celery('analytics')

tchu_exchange = Exchange('tchu_events', type='topic', durable=True)

app.conf.task_queues = (
    Queue('analytics_queue', exchange=tchu_exchange, routing_key='#'),  # All events
)

app.conf.task_routes = {
    'tchu_tchu.dispatch_event': {'queue': 'analytics_queue'},
}

dispatcher = create_topic_dispatcher(app)

# analytics/subscribers.py
from tchu_tchu import subscribe

@subscribe('user.*')  # All user events
def track_user_event(event):
    print(f"Tracking event: {event}")
    # Store in analytics DB...
```

## Routing Key Patterns

RabbitMQ topic exchanges support powerful routing patterns:

- `user.created` - Exact match only
- `user.*` - Matches `user.created`, `user.updated`, `user.deleted`
- `*.created` - Matches `user.created`, `order.created`, etc.
- `#` - Matches all events
- `order.#` - Matches `order.created`, `order.payment.completed`, etc.

## RPC (Request-Response) Pattern

tchu-tchu supports RPC-style calls where you send a message and wait for a response:

```python
from tchu_tchu import TchuClient, subscribe

# Publisher (any app)
client = TchuClient()

try:
    result = client.call('order.calculate_total', {
        'items': [{'id': 1, 'quantity': 2}],
        'discount_code': 'SAVE10'
    }, timeout=10)
    
    print(f"Order total: ${result['total']}")
except TimeoutError:
    print("No response within 10 seconds")
except Exception as e:
    print(f"RPC call failed: {e}")

# Subscriber (handler app)
@subscribe('order.calculate_total')
def calculate_order_total(data):
    items = data['items']
    total = sum(item['quantity'] * get_price(item['id']) for item in items)
    
    # Apply discount if provided
    if data.get('discount_code'):
        total = apply_discount(total, data['discount_code'])
    
    # Return value will be sent back to caller
    return {'total': total, 'currency': 'USD'}
```

**Important Notes:**
- RPC calls are **point-to-point** (only one worker processes the request)
- The first handler to respond wins (if multiple handlers exist)
- Requires a result backend (Redis, database, etc.) configured in Celery
- Use appropriate timeouts to avoid hanging requests

## Framework Integration

### Custom Context Reconstruction

`tchu-tchu` is framework-agnostic. To integrate with your framework's auth/context system, provide a context helper:

```python
from tchu_tchu.events import TchuEvent

# Define your context reconstruction logic
def my_context_helper(event_data):
    """
    Reconstruct request context from event data.
    
    Args:
        event_data: Dict containing fields from your event
        
    Returns:
        Context dict for use with serializers
    """
    user = event_data.get('user')
    if not user:
        return {}
    
    # Reconstruct your framework's request/context object
    # Example for Django:
    from types import SimpleNamespace
    mock_request = SimpleNamespace()
    mock_request.user = SimpleNamespace(**user)
    return {'request': mock_request}

# Set globally (affects all events)
TchuEvent.set_context_helper(my_context_helper)

# Or per-instance
event = MyEvent(context_helper=my_context_helper)
```

### Django Integration

**Recommended: Put context helper in your celery.py file**

```python
# myapp/celery.py
from celery import Celery
from kombu import Exchange, Queue
from tchu_tchu import create_topic_dispatcher
from tchu_tchu.events import TchuEvent

# 1. Define your Django context helper
def create_django_request_context(event_data):
    """Reconstruct Django request context from event data."""
    from types import SimpleNamespace
    
    user_data = event_data.get("user")
    company_data = event_data.get("company")
    user_company_data = event_data.get("user_company")
    
    mock_request = SimpleNamespace()
    
    # If no auth data, return empty context
    if not all([user_data, company_data, user_company_data]):
        return {"request": mock_request}
    
    # Build mock user with company and user_company
    mock_user = SimpleNamespace()
    mock_user.id = user_data.get("id")
    mock_user.email = user_data.get("email")
    mock_user.first_name = user_data.get("first_name")
    mock_user.last_name = user_data.get("last_name")
    
    mock_user.company = SimpleNamespace()
    mock_user.company.id = company_data.get("id")
    mock_user.company.name = company_data.get("name")
    
    mock_user.user_company = SimpleNamespace()
    mock_user.user_company.id = user_company_data.get("id")
    
    mock_request.user = mock_user
    return {"request": mock_request}

# Set it globally (runs when celery.py is imported)
TchuEvent.set_context_helper(create_django_request_context)

# ... rest of your Celery configuration ...
app = Celery('myapp')
# etc.
```

**Or: Create a separate helper module and import it**

```python
# myapp/events/django_context_helper.py
from types import SimpleNamespace

def create_django_request_context(event_data):
    # ... same as above ...
    pass

# myapp/celery.py
from tchu_tchu.events import TchuEvent
from myapp.events.django_context_helper import create_django_request_context

# Set it globally
TchuEvent.set_context_helper(create_django_request_context)
```

**Then define your events:**

```python
# myapp/events.py
from tchu_tchu.events import TchuEvent
from rest_framework import serializers

class UserCreatedEvent(TchuEvent):
    class Meta:
        topic = "user.created"
        request_serializer_class = RequestSerializer
    
class RequestSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    email = serializers.EmailField()
    name = serializers.CharField()
```

**Publish events:**

```python
# myapp/views.py
event = UserCreatedEvent()
event.serialize_request({
    'user_id': 123,
    'email': 'user@example.com',
    'name': 'John Doe'
})
event.publish()
```

**Subscribe to events:**

```python
# myapp/subscribers.py
from tchu_tchu import subscribe

@subscribe('user.created')
def handle_user_created(event_data):
    print(f"User {event_data['email']} was created")
    
    # Or use TchuEvent for context:
    event = UserCreatedEvent()
    event.serialize_request(event_data)
    user_id = event.request_context['request'].user.id  # ✅ Works!
```

### Model Signal Integration

```python
from django.db.models.signals import post_save
from django.dispatch import receiver
from tchu_tchu import TchuClient

client = TchuClient()

@receiver(post_save, sender=User)
def publish_user_created(sender, instance, created, **kwargs):
    if created:
        client.publish('user.created', {
            'user_id': instance.id,
            'email': instance.email
})
```

## Configuration

### Celery Settings

```python
# settings.py or celery.py

from kombu import Exchange, Queue

# Broker URL
broker_url = 'amqp://guest:guest@localhost:5672//'

# Define the topic exchange
tchu_exchange = Exchange('tchu_events', type='topic', durable=True)

# Configure your app's queue
task_queues = (
    Queue(
        'myapp_queue',
        exchange=tchu_exchange,
        routing_key='user.*',  # Routing key pattern(s)
        durable=True,
        auto_delete=False,
    ),
)

# Route the dispatcher task to your queue
task_routes = {
    'tchu_tchu.dispatch_event': {'queue': 'myapp_queue'},
}

# Optional: Recommended Celery settings
task_serializer = 'json'
accept_content = ['json']
result_serializer = 'json'
timezone = 'UTC'
enable_utc = True
```

### Multiple Routing Keys

If you want to subscribe to multiple patterns, create multiple queue bindings:

```python
from kombu import Queue, binding

task_queues = (
    Queue(
        'myapp_queue',
        exchange=tchu_exchange,
        bindings=[
            binding(tchu_exchange, routing_key='user.*'),
            binding(tchu_exchange, routing_key='order.*'),
            binding(tchu_exchange, routing_key='payment.*'),
        ],
        durable=True,
    ),
)
```

## API Reference

### TchuClient

```python
from tchu_tchu import TchuClient

client = TchuClient(celery_app=None, serializer=None)
```

Methods:
- `publish(topic, data, **kwargs)` - Publish an event (broadcast to all subscribers)
- `call(topic, data, timeout=30, **kwargs)` - RPC call (request-response, returns result)

### subscribe()

```python
from tchu_tchu import subscribe

@subscribe(routing_key, name=None, handler_id=None, metadata=None)
def my_handler(event_data):
    pass
```

Parameters:
- `routing_key` - Topic pattern to subscribe to
- `name` - Optional handler name
- `handler_id` - Optional unique handler ID
- `metadata` - Optional metadata dict

### create_topic_dispatcher()

```python
from tchu_tchu import create_topic_dispatcher

dispatcher = create_topic_dispatcher(
    celery_app,
    task_name='tchu_tchu.dispatch_event',
    serializer=None
)
```

Creates a Celery task that dispatches incoming events to local handlers.

## Migration from v1.x

v2.0.0 is a **breaking change** with a completely different architecture:

### What Changed

| v1.x | v2.0.0 |
|------|--------|
| Task-based (point-to-point) | Exchange-based (broadcast) |
| Task discovery/inspection | Static queue configuration |
| Automatic remote task registration | Manual queue bindings |
| `register_remote_task()` required | Not needed (deprecated) |
| Slow (task inspection overhead) | Fast (direct routing) |

### Migration Steps

1. **Update Celery Config** - Add queue bindings to `tchu_events` exchange
2. **Create Dispatcher** - Call `create_topic_dispatcher(app)` in your Celery app
3. **Remove `register_remote_task()` calls** - No longer needed
4. **Test** - Ensure events are received by all subscribing apps

### Example Migration

**Before (v1.x):**
```python
# No special Celery config needed
# Tasks auto-discovered via inspection

from tchu_tchu import subscribe, register_remote_task

@subscribe('user.created')
def handle_user_created(event):
    pass

```

**After (v2.0.0):**
```python
# celery.py - NEW: Configure queue bindings
from kombu import Exchange, Queue
from tchu_tchu import create_topic_dispatcher

tchu_exchange = Exchange('tchu_events', type='topic', durable=True)

app.conf.task_queues = (
    Queue('myapp_queue', exchange=tchu_exchange, routing_key='user.*'),
)

app.conf.task_routes = {
    'tchu_tchu.dispatch_event': {'queue': 'myapp_queue'},
}

dispatcher = create_topic_dispatcher(app)  # NEW

# subscribers.py - Same as before!
from tchu_tchu import subscribe

@subscribe('user.created')
def handle_user_created(event):
    pass

# No register_remote_task() needed!
```

## Troubleshooting

### Events Not Received

1. **Check Celery is running:** `celery -A myapp worker -l info`
2. **Check queue bindings:** Use RabbitMQ management UI to verify queue is bound to exchange
3. **Check routing keys:** Ensure publisher routing key matches subscriber patterns
4. **Check task routes:** Verify `tchu_tchu.dispatch_event` routes to your queue
5. **Check logs:** Look for "Registered handler" and "Published message" log entries

### "Received unregistered task" Error

This means Celery received a message for a task it doesn't recognize. Check:
- `create_topic_dispatcher(app)` was called
- Task routes are configured correctly
- The dispatcher task name matches in config and code

### Multiple Apps Not Receiving Events

Each app MUST have:
1. Its own unique queue name
2. Queue bound to the `tchu_events` exchange
3. The `create_topic_dispatcher()` call in its Celery config
4. Celery worker running

## Performance

v2.0.0 is significantly faster than v1.x:

- **No task discovery** - Static configuration means no inspection overhead
- **No queue inspection** - Direct routing via AMQP
- **Parallel delivery** - RabbitMQ broadcasts to all queues simultaneously

Expected latency: < 10ms (vs 500-1500ms in v1.x due to inspection)

## Changelog
### v2.2.3 (2025-10-27)

**Fixed:**
- Fully removed register_remote_task

### v2.2.2 (2025-10-27)

**Fixed:**
- `UnboundLocalError` when using `JSONField` in DRF serializers
- Removed redundant local `Dict` import that shadowed module-level import

### v2.2.0 (2025-10-26) - Framework Agnostic

**Added:**
- Injectable context helper system via `TchuEvent.set_context_helper()`
- Per-instance context helper support
- `TchuEvent.get_context_helper()` class method

**Changed:**
- **BREAKING (for framework integrations):** Removed hardcoded Django `_reconstruct_context_from_data()` method
- `request_context` property now uses configured context helper
- Framework-specific logic must now be provided via context helper

**Removed:**
- Hardcoded `MockUser`, `MockCompany`, `MockUserCompany`, `MockRequest` classes
- Django-specific context reconstruction from core library

**Migration:**
If you were relying on `request_context`, you now need to set a context helper:
```python
def my_context_helper(event_data):
    # Your framework-specific logic
    return {'request': reconstructed_request}

TchuEvent.set_context_helper(my_context_helper)
```

### v2.1.0 (2025-10-26)

**Added:**
- RPC (request-response) support via `client.call()`
- Handlers can return values that are sent back to the caller
- Comprehensive RPC documentation and examples

**Changed:**
- Producer now properly handles RPC responses from dispatcher
- Improved error handling for RPC timeouts and failures

### v2.0.1 (2025-10-26)

**Fixed:**
- Added missing `log_handler_executed()` function to logging handlers
- Fixed ImportError when importing `create_topic_dispatcher`

### v2.0.0 (2025-10-26) - BREAKING CHANGE

**Complete redesign** using RabbitMQ topic exchanges for true broadcast messaging.

**Added:**
- Topic exchange-based architecture
- `create_topic_dispatcher()` for creating event dispatcher tasks
- True broadcast support (multiple apps receive same event)
- Kombu integration for direct exchange publishing
- Comprehensive documentation and examples

**Changed:**
- Producer now uses topic exchange instead of task discovery
- Subscriber uses dispatcher pattern instead of individual tasks
- Configuration now requires queue bindings in Celery config
- Terminology: "topic" → "routing_key" throughout

**Removed:**
- Task discovery/inspection logic (no longer needed)
- `register_remote_task()` (deprecated, kept for compatibility)

**Performance:**
- 100x faster than v1.x (no inspection overhead)
- Reduced latency from ~1000ms to ~10ms

### v1.4.0 (2025-10-26)
- Added generic queue routing via Celery inspect (replaced hardcoded app names)
- Fixed cross-app communication with dynamic queue detection

### v1.3.2 (2025-10-26)
- Added queue routing based on task names (bad design, later removed)

### v1.3.1 (2025-10-26)
- Updated documentation for "Received unregistered task" errors

### v1.3.0 (2025-10-26)
- Added automatic task discovery via `inspect.registered()`
- Enabled cross-app event publishing and consumption

### v1.2.0 (2025-10-25)
- Fixed context serialization with DRF serializers
- Fixed authentication details preservation in event context

### v1.1.0 (2025-10-25)
- Added cross-app task scanning
- Fixed task registry lookup

### v1.0.3 (2025-10-25)
- Fixed `UnboundLocalError` in DRF to Pydantic conversion
- Fixed callable defaults handling

### v1.0.2 (2025-10-25)
- Fixed context handling in DRF serializers
- Added mock request objects for event context

### v1.0.1 (2025-10-25)
- Initial release with Celery-based messaging

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
