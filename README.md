# tchu-tchu

`tchu-tchu` is a modern, Celery-based messaging library that provides high-performance event publishing and consumption with Pydantic serialization and Django integration. It serves as a drop-in replacement for the original `tchu` package while leveraging Celery's robust task management system.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

## Features

- **🚀 High Performance**: Pydantic serialization for fast data validation and serialization
- **🔄 Drop-in Replacement**: Compatible API with existing tchu-based systems
- **📊 Built-in Metrics**: Comprehensive metrics collection with Prometheus support
- **🏗️ Django Integration**: Automatic model event publishing with decorators
- **🔍 Structured Logging**: JSON-formatted logs with correlation tracking
- **🎯 Topic Patterns**: Support for wildcard topic subscriptions (e.g., "user.*")
- **⚡ Parallel Processing**: Multiple handlers per topic with parallel execution
- **🔒 Type Safety**: Full typing support with Pydantic models
- **📈 Scalable**: Built on Celery's proven distributed task system

## Installation

```bash
pip install tchu-tchu
```

### Optional Dependencies

```bash
# For Django integration
pip install tchu-tchu[django]

# For Protobuf support (future feature)
pip install tchu-tchu[protobuf]

# Install all optional dependencies
pip install tchu-tchu[all]
```

## Quick Start

### 1. Basic Publishing and Subscription

```python
from tchu_tchu import TchuClient, subscribe

# Subscribe to events
def handle_user_created(data):
    print(f"User created: {data['user_id']}")

subscribe("user.created", handle_user_created)

# Publish events
client = TchuClient()
client.publish("user.created", {
    "user_id": "123",
    "name": "John Doe",
    "email": "john@example.com"
})
```

### 2. Using with Your Existing TchuEvent Classes

```python
from tchu_tchu import TchuEvent
from rest_framework import serializers

class UserCreatedEventRequest(serializers.Serializer):
    user_id = serializers.CharField()
    name = serializers.CharField()
    email = serializers.EmailField()

class UserCreatedEvent(TchuEvent):
    class Meta:
        topic = "user.created"
        request_serializer_class = UserCreatedEventRequest

# Publishing events (same API as before)
event = UserCreatedEvent()
event.serialize_request({
    "user_id": "123",
    "name": "John Doe",
    "email": "john@example.com"
})
event.publish()

# Subscribing to events (same API as before)
def handle_user_created(event_instance):
    user_id = event_instance.get("user_id")
    print(f"Handling user creation: {user_id}")

UserCreatedEvent(handler=handle_user_created).subscribe()
```

### 3. Django Model Auto-Publishing

```python
from django.db import models
from tchu_tchu.django import auto_publish

@auto_publish(
    topic_prefix="myapp.users",
    include_fields=["id", "username", "email", "is_active"],
    publish_on=["created", "updated"]
)
class User(models.Model):
    username = models.CharField(max_length=150)
    email = models.EmailField()
    is_active = models.BooleanField(default=True)

# Events are automatically published:
# - myapp.users.user.created (when user is created)
# - myapp.users.user.updated (when user is updated)
```

## Advanced Usage

### Multiple Handlers per Topic

```python
from tchu_tchu import subscribe

def send_welcome_email(data):
    print(f"Sending welcome email to {data['email']}")

def update_analytics(data):
    print(f"Updating analytics for user {data['user_id']}")

def sync_to_crm(data):
    print(f"Syncing user {data['user_id']} to CRM")

# All handlers will run in parallel when a message is published
subscribe("user.created", send_welcome_email)
subscribe("user.created", update_analytics)
subscribe("user.created", sync_to_crm)
```

### Wildcard Topic Subscriptions

```python
from tchu_tchu import subscribe

def handle_all_user_events(data):
    print(f"User event received: {data}")

def handle_all_order_events(data):
    print(f"Order event received: {data}")

# Subscribe to all user-related events
subscribe("user.*", handle_all_user_events)

# Subscribe to all order-related events  
subscribe("order.*", handle_all_order_events)
```

### RPC-Style Messaging

```python
from tchu_tchu import TchuClient, subscribe

# Set up RPC handler
def validate_user(data):
    user_id = data.get("user_id")
    # Perform validation logic
    return {
        "valid": True,
        "user_id": user_id,
        "status": "active"
    }

subscribe("user.validate", validate_user)

# Make RPC call
client = TchuClient()
try:
    response = client.call("user.validate", {"user_id": "123"}, timeout=5)
    print(f"Validation result: {response}")
except TimeoutError:
    print("Validation timed out")
```

### Django Model Mixin

```python
from django.db import models
from tchu_tchu.django.mixins import EventPublishingMixin

class Product(EventPublishingMixin, models.Model):
    name = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    
    class Meta:
        tchu_topic_prefix = "ecommerce.products"
        tchu_publish_on = ["created", "updated", "deleted"]
        tchu_include_fields = ["id", "name", "price"]

# Manual event publishing
product = Product.objects.get(id=1)
product.publish_event("price_changed", {
    "old_price": "10.00",
    "new_price": "12.00"
})
```

### Metrics and Monitoring

```python
from tchu_tchu.metrics import get_metrics_collector, MetricsReporter
from tchu_tchu.metrics.exporters import PrometheusExporter, JSONExporter
from datetime import timedelta

# Get metrics summary
collector = get_metrics_collector()
summary = collector.get_summary(time_window=timedelta(hours=1))
print(f"Messages in last hour: {summary['total_messages']}")

# Export metrics
reporter = MetricsReporter(exporters=[
    PrometheusExporter("/tmp/metrics.prom"),
    JSONExporter("/tmp/metrics.json")
])
reporter.export_report(time_window=timedelta(hours=24))

# Topic-specific metrics
topic_stats = collector.get_topic_stats("user.created")
print(f"User creation events: {topic_stats}")
```

### Custom Serialization

```python
from tchu_tchu.serializers import PydanticSerializer
from pydantic import BaseModel
from typing import Optional

class UserModel(BaseModel):
    user_id: str
    name: str
    email: str
    age: Optional[int] = None

# Use custom serializer
serializer = PydanticSerializer(UserModel)
client = TchuClient(serializer=serializer)

client.publish("user.created", {
    "user_id": "123",
    "name": "John Doe", 
    "email": "john@example.com",
    "age": 30
})
```

## Cross-App Communication

`tchu-tchu` **automatically discovers** tasks from all active workers! Just subscribe in consumer apps, and publishers will automatically find and route to them.

### Requirements

1. **Shared Celery Broker**: All apps must connect to the same Redis/RabbitMQ broker
2. **Consumer Workers Running**: Consumer apps must be running when publisher sends messages

### Setup Example (Automatic Discovery)

**Step 1: Consumer App (Scranton Service) - Register Handler:**
```python
# scranton/subscribers/information_request_subscriber.py
from tchu_tchu.events import TchuEvent
import celery

class InformationRequestPreparedEvent(TchuEvent):
    class Meta:
        topic = "coolset.scranton.information_request.prepared"
        request_serializer_class = InformationRequestSerializer

@celery.shared_task
def execute_information_request_task(event, **kwargs):
    # Handle the event
    information_request_data = event.get("information_request")
    serializer = InformationRequestSerializer(
        data=information_request_data,
        context=event.request_context
    )
    if serializer.is_valid():
        return serializer.save()

# Subscribe - task is auto-discoverable by other apps!
InformationRequestPreparedEvent(handler=execute_information_request_task).subscribe()
```

**Step 2: Publisher App - Just Publish! (No Registration Needed)**
```python
# api/views.py or pulse/views.py
from scranton.events import InformationRequestPreparedEvent

def create_information_request(request):
    event = InformationRequestPreparedEvent()
    event.serialize_request(
        {"information_request": {"order_id": 123}},
        context={"request": request}
    )
    event.publish()  # Auto-discovers and routes to Scranton worker!
```

### How It Works (Automatic Discovery)

1. **Consumer registers task**: `subscribe()` creates a Celery `@shared_task`
2. **Publisher auto-discovers**: Uses `celery.control.inspect()` to find tasks on all workers
3. **Publisher routes via `send_task()`**: Sends to broker by task name
4. **Celery delivers**: Broker routes to the appropriate worker

### Performance

- **1-second timeout** for task discovery (doesn't block requests)
- **Graceful fallback** if no workers available
- Discovery happens on each publish (ensures fresh task list)

### Important Notes

When using auto-discovery with multiple consumers:
- **All discovered tasks are sent** to the broker
- **Each worker processes only its tasks** and ignores others
- You may see `"Received unregistered task"` errors in logs - **this is normal**
- Celery automatically discards tasks that workers don't recognize
- To suppress these log messages, configure `task_reject_on_worker_lost=True`

### Multiple Consumers for One Event

Just subscribe in each app - automatic discovery finds them all:

```python
# Scranton app
InformationRequestPreparedEvent(handler=execute_in_scranton).subscribe()

# Pulse app  
InformationRequestPreparedEvent(handler=execute_in_pulse).subscribe()

# Publisher app - just publish!
event.publish()  # Both handlers auto-discovered and executed!
```

### Manual Registration (Optional)

If you prefer explicit registration or need it for some reason:

```python
from tchu_tchu import register_remote_task

register_remote_task(
    "coolset.scranton.information_request.prepared",
    "tchu_tchu.topics.coolset_scranton_information_request_prepared.InformationRequestPreparedEvent_execute_information_request_task"
)
```

### Troubleshooting

**"No handlers found for topic"**:
- Verify consumer app's Celery workers are running
- Check both apps use the same broker URL (Redis/RabbitMQ)
- Make sure consumer called `subscribe()` during startup
- Check worker logs to confirm task is registered

**"Received unregistered task" errors**:
- **This is normal with auto-discovery!** When multiple apps subscribe to the same topic, all tasks are sent to the broker and workers ignore tasks they don't have
- The system is working correctly - these are just informational warnings
- To suppress these errors, add to your Celery config:
  ```python
  # Celery will silently ignore unregistered tasks instead of logging errors
  app.conf.task_reject_on_worker_lost = True
  ```

**Discovery timeout warnings**:
- Normal if no workers running yet
- Increase timeout if needed (default 1 second)

## Configuration

### Celery Configuration

```python
# celery_config.py
from celery import Celery

app = Celery('myapp')
app.config_from_object({
    'broker_url': 'redis://localhost:6379/0',
    'result_backend': 'redis://localhost:6379/0',
    'task_serializer': 'json',
    'accept_content': ['json'],
    'result_serializer': 'json',
    'timezone': 'UTC',
    'enable_utc': True,
    # Recommended: Suppress "unregistered task" errors with auto-discovery
    'task_reject_on_worker_lost': True,
})

# Use with tchu-tchu
from tchu_tchu import TchuClient
client = TchuClient(celery_app=app)
```

### Django Settings

```python
# settings.py
INSTALLED_APPS = [
    # ... other apps
    'tchu_tchu.django',
]

# Celery configuration
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'

# tchu-tchu specific settings
TCHU_METRICS_ENABLED = True
TCHU_LOG_LEVEL = 'INFO'
```

## Migration from Original tchu

### 1. Update Imports

```python
# Before (original tchu)
from tchu import Producer, Consumer
from cs_common.events.clients.tchu_client import TchuClient

# After (tchu-tchu)
from tchu_tchu import CeleryProducer, TchuClient, subscribe
```

### 2. Replace Consumers with Subscriptions

```python
# Before (original tchu)
def message_handler(ch, method, properties, body, is_rpc):
    # Handle message
    pass

consumer = Consumer(
    amqp_url="amqp://localhost:5672/",
    exchange="my-exchange",
    routing_keys=["user.*"],
    callback=message_handler
)
consumer.run()

# After (tchu-tchu)
def message_handler(data):
    # Handle message (simplified signature)
    pass

subscribe("user.*", message_handler)
# No need to run consumer - Celery handles it
```

### 3. Update TchuClient Usage

```python
# Your existing TchuEvent classes work unchanged!
class MyEvent(TchuEvent):
    class Meta:
        topic = "my.topic"
        request_serializer_class = MyRequestSerializer

# Same API
event = MyEvent()
event.serialize_request(data)
event.publish()  # Now uses Celery instead of RabbitMQ directly
```

## Performance Benefits

- **Faster Serialization**: Pydantic is significantly faster than DRF serializers
- **Better Concurrency**: Celery's worker pools handle concurrent processing
- **Reduced Memory Usage**: No persistent RabbitMQ connections per consumer
- **Horizontal Scaling**: Easy to scale by adding more Celery workers
- **Built-in Retries**: Celery's robust retry mechanisms

## Development

### Running Tests

```bash
# Install development dependencies
pip install -e .[dev]

# Run tests
pytest

# Run with coverage
pytest --cov=tchu_tchu --cov-report=html
```

### Code Quality

```bash
# Format code
black tchu_tchu/
isort tchu_tchu/

# Lint code
flake8 tchu_tchu/
mypy tchu_tchu/
```

## Troubleshooting

### Common Issues

1. **No handlers registered for topic**: Make sure you call `subscribe()` before publishing messages
2. **Celery workers not processing tasks**: Ensure Celery workers are running with `celery -A myapp worker`
3. **Import errors**: Check that optional dependencies are installed if using Django features

### Debugging

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Check registered handlers
from tchu_tchu.subscriber import list_subscriptions
print(list_subscriptions())

# View metrics
from tchu_tchu.metrics import get_metrics_collector
collector = get_metrics_collector()
print(collector.get_summary())
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Changelog

### v1.3.2
- **FIX**: Automatic queue detection for apps with separate Celery queues
- Detects queue name from task name (e.g., `_pulse_` -> queue: `pulse`)
- Tasks now route to the correct worker queues automatically
- Supports `pulse`, `scranton`, and other common queue names
- Manual queue override still possible via `kwargs`

### v1.3.1
- **DOCS**: Added explanation for "Received unregistered task" warnings
- Clarified that these warnings are normal with auto-discovery
- Added Celery config recommendation: `task_reject_on_worker_lost=True`
- Updated cross-app communication documentation with important notes
- System works correctly - warnings are informational only

### v1.3.0
- **AUTOMATIC TASK DISCOVERY**: No manual registration needed for cross-app communication! 🎉
- Producer automatically discovers tasks from all active workers via Celery inspect
- Just subscribe in consumer apps - publishers automatically find and route to them
- Falls back gracefully if inspection fails (e.g., no workers running)
- 1-second timeout for discovery to avoid blocking requests
- Works with both `publish()` and `call()` methods
- `register_remote_task()` still available but no longer required

### v1.2.1
- **IMPROVED**: `publish()` now logs warning instead of raising exception when no handlers found
- Better for model signal-triggered events that may not always have handlers
- RPC `call()` still raises exception (as you expect a response)
- More helpful warning message explaining when this is normal behavior

### v1.2.0
- **PROPER CELERY IMPLEMENTATION**: Cross-app messaging using `send_task()` 
- New `register_remote_task()` function for registering remote handlers
- Producer now uses `send_task()` instead of `apply_async()` for proper cross-worker routing
- Simplified architecture - no complex task discovery needed
- Publisher apps explicitly register remote tasks as proxies
- Follows Celery best practices for distributed task execution
- Comprehensive cross-app communication documentation

### v1.1.0
- Initial attempt at cross-app event handling (improved in v1.2.0)
- Task discovery across apps
- Better logging for missing handlers

### v1.0.3
- **CRITICAL FIX**: Properly handle DRF serializers with `EventAuthorizationSerializer` and HiddenFields
- DRF serializers now use the actual request context during publishing to populate auth fields
- Event handlers receive reconstructed context via `event.request_context` with user/company data
- Fixes `TypeError: 'NoneType' object is not subscriptable` in handlers using `InformationRequestSerializer`
- Support for `skip_authorization` parameter passed through to DRF serializers
- Hidden fields (company, user_company, user) are now properly serialized and transmitted

### v1.0.2
- Context (authentication) data transmission improvements
- Authentication data automatically extracted and included in messages
- Mock request objects for handler context reconstruction

### v1.0.1
- Fixed `UnboundLocalError` in DRF to Pydantic conversion when using `Any` type
- Fixed context handling for DRF serializers with callable defaults
- Improved error handling for fields that depend on request context

### v1.0.0
- Initial release
- Celery-based message processing
- Pydantic serialization
- Django integration
- Metrics collection
- Drop-in replacement for original tchu
