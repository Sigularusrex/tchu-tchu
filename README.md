# tchu-tchu

A modern Celery-based messaging library with **true broadcast support** for microservices. Designed to replicate the simplicity of the original `tchu` library while leveraging Celery workers for execution.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://badge.fury.io/py/tchu-tchu.svg)](https://badge.fury.io/py/tchu-tchu)

> **🚨 v2.2.30 Released** - CRITICAL FIX for ServerlessProducer bytes encoding! If using v2.2.29, upgrade immediately. **[See Serverless Guide →](#serverless-environments-cloud-functions-lambda)**  
>
> **🚨 v2.2.29 Released** - CRITICAL FIX for ServerlessProducer serialization! If using v2.2.28, upgrade immediately.  
>
> **🚨 v2.2.28 Released** - CRITICAL FIX for ServerlessProducer! If using v2.2.27, upgrade immediately.  
>
> **🚀 v2.2.27 Released** - Serverless producer for serverless environments (Cloud Functions, Lambda)!  
>
> **🚀 v2.2.26 Released** - Extended Celery class with cleaner API! Import `Celery` from tchu-tchu for seamless integration.  
> **[See Quick Start →](#django--celery-simplified-setup)**
>
> **📢 v2.2.11 Critical Fix** - If you're on v2.2.9, broadcast events may be silently failing. **[Upgrade now →](./MIGRATION_2.2.11.md)**  
>
> **❌ Getting "No handlers found" errors?** See **[Troubleshooting Guide →](./TROUBLESHOOTING_RPC_HANDLERS.md)**

## Features

- ✨ **True Broadcast Messaging** - One event reaches multiple microservices
- 🚀 **Uses Existing Celery Workers** - No separate listener process needed
- 🎯 **Topic-based Routing** - RabbitMQ topic exchange with wildcard patterns
- 🔄 **Drop-in Replacement** - Compatible with original `tchu` API
- 📦 **Pydantic Integration** - Type-safe event serialization
- 🛡️ **Django Support** - Built-in Django REST Framework integration with one-line setup
- ⚡ **Fast** - No task discovery or inspection overhead
- 🎨 **Simple** - One function call replaces 60+ lines of boilerplate configuration

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

## RPC vs Broadcast Events

tchu-tchu supports two messaging patterns:

### 🔄 Broadcast Events (Pub/Sub)
**One publisher → Multiple subscribers receive the same event**

```python
# Publisher
client.publish('user.created', {'user_id': 123})

# Subscriber 1 (notifications service)
@subscribe('user.created')
def send_welcome_email(event):
    send_email(event['user_id'])

# Subscriber 2 (analytics service)
@subscribe('user.created')
def track_signup(event):
    track_event(event['user_id'])
```

**Use for:** Event notifications, logging, analytics, cache invalidation

### ⚡ RPC (Request-Response)
**One caller → One responder → Returns result**

```python
# Caller
result = client.call('rpc.app_name.documents.list', {'company_id': 67})
print(result)  # Returns document list

# Responder (only data-room service handles this)
@subscribe('rpc.app_name.documents.list')
def list_documents(data):
    docs = Document.objects.filter(company_id=data['company_id'])
    return [doc.to_dict() for doc in docs]  # Returned to caller
```

**Use for:** Querying data, validation, calculations, inter-service API calls

**Key Difference:** Broadcast events go to ALL subscribers; RPC calls go to ONE handler and return a response.

## Installation

```bash
pip install tchu-tchu
```

## Quick Start

### Django + Celery (Simplified Setup)

**🚀 tchu-tchu v2.2.26+ provides an extended `Celery` class** for the cleanest API:

```python
# myapp/celery.py
import os
import django

from tchu_tchu.django import Celery  # Import extended Celery from tchu-tchu
from tchu_tchu.events import TchuEvent

# 1. Initialize Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.production")
django.setup()

# 2. Create Celery app (with tchu-tchu extensions)
app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")

# 3. Optional: Set context helper for Django request reconstruction
def create_django_context(event_data):
    from types import SimpleNamespace
    user_data = event_data.get("user")
    if not user_data:
        return {}
    mock_request = SimpleNamespace()
    mock_request.user = SimpleNamespace(**user_data)
    return {"request": mock_request}

TchuEvent.set_context_helper(create_django_context)

# 4. Configure message broker in one method call! 🎉
app.message_broker(
    queue_name="my_queue",
    include=[
        "app1.subscribers",
        "app2.subscribers",
        "app3.subscribers",
    ],
)
```

**That's it!** This automatically:
- ✅ Imports all subscriber modules after Django is ready
- ✅ Collects all routing keys from `@subscribe` decorators
- ✅ Creates queue bindings to the `tchu_events` exchange
- ✅ Configures Celery queues and task routes
- ✅ Sets up cross-service RPC messaging
- ✅ Creates the dispatcher task

**Auto-Discovery:** You can also omit `include` to use Celery's `include` parameter:
```python
from tchu_tchu.django import Celery

# Specify full module paths in Celery's 'include'
app = Celery("my_app", include=["app1.subscribers", "app2.subscribers", "app3.subscribers"])
app.config_from_object("django.conf:settings", namespace="CELERY")

# Uses modules from Celery's include parameter
app.message_broker(queue_name="my_queue")
```

**Alternative:** You can still use the standalone `setup_celery_queue()` function:
```python
from celery import Celery  # Standard Celery
from tchu_tchu.django import setup_celery_queue

app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")

setup_celery_queue(
    app,
    queue_name="my_queue",
    subscriber_modules=["app1.subscribers", "app2.subscribers"],
)
```

**Settings needed in Django:**
```python
# settings/base.py
INSTALLED_APPS = [
    # ... other apps ...
    "myapp.apps.MyAppConfig",  # Use explicit AppConfig path
]

# Make sure you have explicit AppConfig paths for your main apps
# This avoids "Apps aren't loaded yet" errors
```

**📖 For complete documentation on the extended Celery class, see [EXTENDED_CELERY_USAGE.md](./EXTENDED_CELERY_USAGE.md)**

### Generic Celery Setup (Non-Django)

For non-Django apps, or if you prefer manual configuration:

```python
# myapp/celery.py
from celery import Celery
from kombu import Exchange, Queue, binding
from tchu_tchu import create_topic_dispatcher, get_subscribed_routing_keys
from tchu_tchu.events import TchuEvent

app = Celery('myapp')

# Configure context helper (optional)
def my_context_helper(event_data):
    """Reconstruct request context from event data."""
    from types import SimpleNamespace
    user = event_data.get('user')
    if user:
        mock_request = SimpleNamespace()
        mock_request.user = SimpleNamespace(**user)
        return {'request': mock_request}
    return {}

TchuEvent.set_context_helper(my_context_helper)

# Import subscribers FIRST so @subscribe decorators run
app.autodiscover_tasks(['myapp.subscribers'])

# Auto-configure queue bindings from subscribed routing keys
tchu_exchange = Exchange('tchu_events', type='topic', durable=True)

# ✅ IMPORTANT: Pass celery_app to force immediate handler registration
all_routing_keys = get_subscribed_routing_keys(celery_app=app)

# Build bindings automatically
all_bindings = [
    binding(tchu_exchange, routing_key=key) 
    for key in all_routing_keys
]

# Configure queues
app.conf.task_queues = (
    Queue(
        'myapp_queue',
        exchange=tchu_exchange,
        bindings=all_bindings,
        durable=True,
        auto_delete=False,
    ),
)

# Route dispatcher to the queue
app.conf.task_routes = {
    'tchu_tchu.dispatch_event': {'queue': 'myapp_queue'},
}

# Create the dispatcher task
dispatcher = create_topic_dispatcher(app)
```

**Key Points:**
- ✅ **Always pass `celery_app=app`** to `get_subscribed_routing_keys()` - this ensures handlers are registered before queue configuration
- ✅ Queue bindings are **automatically generated** from your `@subscribe` decorators
- ✅ Both broadcast events and RPC calls can use the same queue

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
from kombu import Exchange, Queue, binding
from tchu_tchu import create_topic_dispatcher, get_subscribed_routing_keys

app = Celery('users')
app.autodiscover_tasks(['users.subscribers'])

tchu_exchange = Exchange('tchu_events', type='topic', durable=True)

# Auto-collect routing keys from handlers
all_routing_keys = get_subscribed_routing_keys(celery_app=app)
all_bindings = [binding(tchu_exchange, routing_key=key) for key in all_routing_keys]

app.conf.task_queues = (
    Queue(
        'users_queue',
        exchange=tchu_exchange,
        bindings=all_bindings,
        durable=True,
    ),
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
from kombu import Exchange, Queue, binding
from tchu_tchu import create_topic_dispatcher, get_subscribed_routing_keys

app = Celery('notifications')
app.autodiscover_tasks(['notifications.subscribers'])

tchu_exchange = Exchange('tchu_events', type='topic', durable=True)

# Auto-collect routing keys from handlers
all_routing_keys = get_subscribed_routing_keys(celery_app=app)
all_bindings = [binding(tchu_exchange, routing_key=key) for key in all_routing_keys]

app.conf.task_queues = (
    Queue(
        'notifications_queue',
        exchange=tchu_exchange,
        bindings=all_bindings,
        durable=True,
    ),
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
from kombu import Exchange, Queue, binding
from tchu_tchu import create_topic_dispatcher, get_subscribed_routing_keys

app = Celery('analytics')
app.autodiscover_tasks(['analytics.subscribers'])

tchu_exchange = Exchange('tchu_events', type='topic', durable=True)

# Auto-collect routing keys from handlers
all_routing_keys = get_subscribed_routing_keys(celery_app=app)
all_bindings = [binding(tchu_exchange, routing_key=key) for key in all_routing_keys]

app.conf.task_queues = (
    Queue(
        'analytics_queue',
        exchange=tchu_exchange,
        bindings=all_bindings,
        durable=True,
    ),
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

RabbitMQ topic exchanges support powerful routing patterns using wildcards:

### Wildcard Types

- **`*` (star)** - Matches exactly one word
  - `user.*` matches `user.created`, `user.updated`, `user.deleted`
  - `*.created` matches `user.created`, `order.created`, etc.
  - Does NOT match `user.profile.updated` (two words after `user`)

- **`#` (hash)** - Matches zero or more words
  - `user.#` matches `user.created`, `user.profile.updated`, `user.anything.else.here`
  - `#` matches ALL events
  - `order.#` matches `order.created`, `order.payment.completed`, `order.shipping.tracking.updated`

### Examples

| Pattern | Matches | Doesn't Match |
|---------|---------|---------------|
| `user.created` | `user.created` | `user.updated`, `order.created` |
| `user.*` | `user.created`, `user.deleted` | `user.profile.updated` |
| `user.#` | `user.created`, `user.profile.updated` | `order.created` |
| `*.created` | `user.created`, `order.created` | `user.updated` |
| `#` | Everything | Nothing |
| `rpc.app_name.*` | `rpc.app_name.documents`, `rpc.app_name.exports` | `rpc.app_name.documents` |

### RPC Naming Convention

By convention, RPC routing keys start with `rpc.`:
- `rpc.app_name.documents.list` - RPC call to data-room service
- `rpc.app_name.products.validate` - RPC call to app_name service
- `app_name.sub_app_or_model.order.enriched` - Broadcast event (not RPC)

This helps distinguish between point-to-point RPC calls and broadcast events.

## Serverless Environments (Cloud Functions, Lambda)

**v2.2.30+** includes a serverless producer that works in serverless environments where Celery's connection pooling doesn't work well.

### Why a Serverless Producer?

- **Cloud Functions** are short-lived and don't maintain persistent connections
- Celery uses connection pooling, which expects long-running processes
- The serverless producer uses `pika` directly (like the original tchu library)
- Creates short-lived connections that work perfectly in serverless environments

### Usage in Cloud Functions

```python
# cloud_function/main.py
import os
from tchu_tchu.serverless_producer import ServerlessClient

# Get broker URL from environment
BROKER_URL = os.environ.get('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672//')

def publish_event(request):
    """Cloud Function that publishes events to tchu-tchu."""
    # Create client with broker URL
    client = ServerlessClient(broker_url=BROKER_URL)
    
    # Publish event
    client.publish('coolset.data_room_consumer.data_point.submitted', {
        'data_point_id': 123,
        'value': 456.78,
        'timestamp': '2024-11-06T10:30:00Z'
    })
    
    # Close connection (optional, but recommended)
    client.close()
    
    return {'status': 'published'}

def publish_with_context_manager(request):
    """Using context manager (automatically closes connection)."""
    with ServerlessClient(broker_url=BROKER_URL) as client:
        client.publish('user.created', {'user_id': 123})
    
    return {'status': 'published'}
```

### Using ServerlessProducer Directly

```python
from tchu_tchu.serverless_producer import ServerlessProducer

# Create producer
producer = ServerlessProducer(
    broker_url='amqp://user:pass@rabbitmq-host:5672//',
    exchange_name='tchu_events',  # Optional, default: 'tchu_events'
    connection_timeout=10,  # Optional, default: 10 seconds
)

# Publish messages
message_id = producer.publish(
    routing_key='user.created',
    body={'user_id': 123},
    delivery_mode=2,  # 1=non-persistent, 2=persistent
)

# Close when done
producer.close()
```

### Configuration

**Environment Variables:**
```bash
# Set RabbitMQ connection URL
export RABBITMQ_URL="amqp://username:password@rabbitmq-host:5672//"
```

**Requirements:**
```txt
tchu-tchu>=2.2.30
```

### Network Access Requirements

Your cloud function **must have network access** to RabbitMQ:

**Google Cloud Functions:**
```bash
# Create VPC connector
gcloud compute networks vpc-access connectors create rabbitmq-connector \
    --region=us-central1 \
    --network=your-vpc \
    --range=10.8.0.0/28

# Deploy function with VPC access
gcloud functions deploy my-function \
    --vpc-connector=rabbitmq-connector \
    --set-env-vars RABBITMQ_URL="amqp://user:pass@internal-ip:5672//"
```

**AWS Lambda:**
- Place Lambda in same VPC as RabbitMQ (or use Amazon MQ)
- Configure security groups to allow access to RabbitMQ ports

**Azure Functions:**
- Use VNet Integration to connect to RabbitMQ
- Or use Azure Service Bus as an alternative

### Comparison: Serverless vs Celery-based

| Feature | ServerlessClient | TchuClient (Celery) |
|---------|-----------------|---------------------|
| **Use Case** | Cloud Functions, Lambda | Long-running services |
| **Connection** | Short-lived | Persistent pool |
| **Dependencies** | pika only | Celery + kombu |
| **Overhead** | Minimal | Higher (connection pooling) |
| **Publish Support** | ✅ Yes | ✅ Yes |
| **RPC Support** | ❌ No | ✅ Yes |
| **Subscribe Support** | ❌ No (publish-only) | ✅ Yes |

**Key Difference:** `ServerlessClient` is **publish-only** and perfect for serverless environments where you only need to send events, not consume them.

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

### RPC Error Handling with TchuRPCException

Use `TchuRPCException` to return business logic errors as responses (not exceptions). Define separate serializers for success and error cases:

```python
from tchu_tchu import TchuEvent, TchuRPCException
from rest_framework import serializers

# Define your serializers
class RequestSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)

class SuccessResponseSerializer(serializers.Serializer):
    transaction_id = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    status = serializers.CharField()

class ErrorResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    error_message = serializers.CharField()
    error_code = serializers.CharField()
    error_details = serializers.JSONField(required=False, default=dict)

# Define your event
class ProcessPaymentEvent(TchuEvent):
    class Meta:
        topic = "rpc.payments.process"
        request_serializer_class = RequestSerializer
        response_serializer_class = SuccessResponseSerializer
        error_serializer_class = ErrorResponseSerializer

# Handler - raise TchuRPCException for business logic errors
def process_payment_handler(event):
    user_id = event["user_id"]
    amount = event["amount"]
    
    # Business validation - raise TchuRPCException
    if amount <= 0:
        raise TchuRPCException(
            message="Amount must be positive",
            code="INVALID_AMOUNT",
            details={"amount": str(amount)}
        )
    
    if not user_exists(user_id):
        raise TchuRPCException(
            message="User not found",
            code="USER_NOT_FOUND",
            details={"user_id": user_id}
        )
    
    # Process and return success response
    transaction = charge_user(user_id, amount)
    return {
        "transaction_id": transaction.id,
        "amount": transaction.amount,
        "status": "completed"
    }

ProcessPaymentEvent(handler=process_payment_handler).subscribe()

# Caller - check for error_code to detect errors
event = ProcessPaymentEvent()
event.serialize_request({"user_id": 123, "amount": 50.00})
response = event.call(timeout=30)

if "error_code" in response:
    print(f"Failed: {response['error_message']} ({response['error_code']})")
else:
    print(f"Success: {response['transaction_id']}")
```

**Benefits:**
- **Clean separation**: Success and error responses have separate schemas
- **No mixed serializers**: No need to make all fields optional
- **Errors as responses**: Business logic errors returned as proper responses (not exceptions)
- **Better validation**: Each response type is validated against its own serializer
- **No timeouts**: Errors don't cause "No handlers found" or timeout errors
- **Clear error handling**: Caller can distinguish between business logic errors and system failures

**Error Response Structure:**
```python
{
    "success": False,
    "error_message": "User not found",
    "error_code": "USER_NOT_FOUND",
    "error_details": {"user_id": 123}
}
```

**Success Response Structure:**
```python
{
    "transaction_id": "txn_123",
    "amount": 50.00,
    "status": "completed"
}
```

**Note:** If you don't define `error_serializer_class`, error responses will still work but won't be validated.

#### Custom RPC Exceptions

Create domain-specific exceptions by subclassing `TchuRPCException` and overriding `to_response_dict()`:

```python
from tchu_tchu import TchuRPCException

class PaymentException(TchuRPCException):
    """Custom payment error with specific fields."""
    
    def __init__(self, payment_id: str, error_type: str, message: str, retry_after: int = None):
        self.payment_id = payment_id
        self.error_type = error_type
        self.retry_after = retry_after
        super().__init__(message=message, code=error_type)
    
    def to_response_dict(self) -> dict:
        """Return custom response structure."""
        response = {
            "payment_id": self.payment_id,
            "error_type": self.error_type,
            "message": self.message,
        }
        if self.retry_after:
            response["retry_after"] = self.retry_after
        return response

# Handler
def payment_handler(event):
    if insufficient_funds():
        raise PaymentException(
            payment_id="pay_123",
            error_type="INSUFFICIENT_FUNDS",
            message="Your account balance is too low",
            retry_after=3600  # Retry after 1 hour
        )
    # ...

# Define matching error serializer
class PaymentErrorSerializer(serializers.Serializer):
    payment_id = serializers.CharField()
    error_type = serializers.CharField()
    message = serializers.CharField()
    retry_after = serializers.IntegerField(required=False)
```

#### Exception Guide

**Use `TchuRPCException` for:**
- ✅ Business logic errors in RPC handlers
- ✅ Validation failures (user input, business rules)
- ✅ Expected error conditions (user not found, insufficient funds)
- 🎯 **Effect**: Returns error response to caller (not an exception)

```python
if not user_exists(user_id):
    raise TchuRPCException("User not found", code="USER_NOT_FOUND")
```

**Use other exceptions for:**
- ✅ System/infrastructure errors (database down, broker unavailable)
- ✅ Unexpected errors (bugs, null pointers)
- ✅ Broadcast event handler failures (no caller to return to)
- 🎯 **Effect**: Propagates as exception, RPC call times out

```python
from tchu_tchu.utils.error_handling import SerializationError, PublishError

# Serialization errors
if not serializer.is_valid():
    raise SerializationError(f"Invalid data: {serializer.errors}")

# Broker errors
if not broker.is_connected():
    raise PublishError("Failed to connect to RabbitMQ")
```

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

**⚠️ Important:** Context helpers must be **regular functions**, not bound methods. If you encounter `TypeError: context_helper() takes 1 positional argument but 2 were given`, ensure you're passing a function, not a method:

```python
# ❌ WRONG - Don't pass bound methods
class MyClass:
    def my_helper(self, event_data):
        return {}

obj = MyClass()
TchuEvent.set_context_helper(obj.my_helper)  # Will pass (self, event_data)

# ✅ CORRECT - Use standalone functions
def my_helper(event_data):
    return {}

TchuEvent.set_context_helper(my_helper)  # Will pass (event_data)

# ✅ WORKAROUND - Use *args if you need to support both
def safe_context_helper(*args, **kwargs):
    """Handles both (event_data) and (self, event_data) signatures."""
    event_data = args[1] if len(args) >= 2 else args[0]
    # Your logic here
    return create_context(event_data)
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

### Extended Celery Class

**🆕 v2.2.26+** - Import from tchu-tchu for extended functionality:

```python
from tchu_tchu.django import Celery

app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Extended method for message broker configuration
app.message_broker(
    queue_name="my_queue",
    include=["app1.subscribers", "app2.subscribers"],
    exchange_name="tchu_events",  # Optional
    exchange_type="topic",  # Optional
    durable=True,  # Optional
    auto_delete=False,  # Optional
)
```

**Methods:**
- All standard `celery.Celery` methods (fully compatible)
- `message_broker()` - Configure tchu-tchu message broker with subscriber modules

**See [EXTENDED_CELERY_USAGE.md](./EXTENDED_CELERY_USAGE.md) for complete documentation.**

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
- `routing_key` - Topic pattern to subscribe to (e.g., `user.created`, `user.*`, `#`)
- `name` - Optional handler name
- `handler_id` - Optional unique handler ID
- `metadata` - Optional metadata dict

### get_subscribed_routing_keys()

```python
from tchu_tchu import get_subscribed_routing_keys

# ✅ IMPORTANT: Always pass celery_app
all_routing_keys = get_subscribed_routing_keys(
    celery_app=app,  # Required to force handler registration
    exclude_patterns=None,  # Optional: list of patterns to exclude (e.g., ['rpc.*'])
    force_import=True,  # Default: True (forces immediate task import)
)
```

**Returns:** List of all routing keys that have handlers registered via `@subscribe` or `Event().subscribe()`.

**Important:** Without `celery_app`, handlers may not be registered yet (due to lazy `autodiscover_tasks()`), resulting in an empty list and incorrect queue bindings.

### setup_celery_queue()

**🆕 v2.2.12+** - Django helper that simplifies Celery configuration:

```python
from tchu_tchu import setup_celery_queue

setup_celery_queue(
    celery_app,
    queue_name,
    subscriber_modules,
    exchange_name='tchu_events',
    exchange_type='topic',
    durable=True,
    auto_delete=False
)
```

**Parameters:**
- `celery_app` - Celery app instance
- `queue_name` - Name of the queue (e.g., "my_app_queue")
- `subscriber_modules` - List of module paths containing `@subscribe` decorators (e.g., `["app1.subscribers", "app2.subscribers"]`)
- `exchange_name` - RabbitMQ exchange name (default: "tchu_events")
- `exchange_type` - Exchange type (default: "topic")
- `durable` - Whether queue is durable (default: True)
- `auto_delete` - Whether queue auto-deletes (default: False)

**What it does:**
1. Imports all subscriber modules after Django is ready (avoids `AppRegistryNotReady` errors)
2. Collects all routing keys from registered handlers
3. Creates queue bindings to the exchange
4. Configures Celery queues and task routes
5. Sets up cross-service RPC messaging with proper exchange config
6. Creates the dispatcher task

**Example:**
```python
# myapp/celery.py
import django
django.setup()

app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")

setup_celery_queue(
    app,
    queue_name="my_queue",
    subscriber_modules=["app1.subscribers", "app2.subscribers"],
)
```

### create_topic_dispatcher()

```python
from tchu_tchu import create_topic_dispatcher

dispatcher = create_topic_dispatcher(
    celery_app,
    task_name='tchu_tchu.dispatch_event',
    serializer=None
)
```

Creates a Celery task that dispatches incoming events to local handlers. Call this in your `celery.py` after configuring queues.

**Note:** If using `setup_celery_queue()`, you don't need to call this manually - it's handled automatically.

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

### Broadcast Events Not Received (v2.2.11 Fix)

**Symptom:** RPC works but broadcast events are silently failing.

**Cause:** You're not passing `celery_app` to `get_subscribed_routing_keys()`, resulting in empty routing keys `[]` and incorrect queue bindings.

**Solution:**
```python
# ❌ WRONG (returns empty list)
all_routing_keys = get_subscribed_routing_keys()

# ✅ CORRECT (forces handler registration)
all_routing_keys = get_subscribed_routing_keys(celery_app=app)
```

**If you upgraded from v2.2.9**, you MUST:
1. Update code to pass `celery_app=app`
2. Delete old queues: `rabbitmqctl delete_queue your_queue_name`
3. Restart services

See [MIGRATION_2.2.11.md](./MIGRATION_2.2.11.md) for details.

### Verify Queue Bindings

Check that your queue has wildcard bindings:

```bash
rabbitmqctl list_bindings | grep "your_queue_name"
```

**Should see:**
```
tchu_events  exchange  your_queue  queue  app_name.sub_app_or_model.#  []  ✅
tchu_events  exchange  your_queue  queue  app_name.#  []  ✅
```

**NOT:**
```
tchu_events  exchange  your_queue  queue  your_queue  []  ❌ Wrong!
```

### Events Still Not Received

1. **Check Celery is running:** `celery -A myapp worker -l info`
2. **Check handler registration:** Look for `Registered handler 'X' for routing key 'Y'` in logs
3. **Check routing keys match:** Publisher routing key must match subscriber pattern
4. **Check task routes:** Verify `tchu_tchu.dispatch_event` routes to your queue
5. **Check queue bindings:** Verify in RabbitMQ that patterns match your handlers

### "Received unregistered task" Error

This means Celery received a message for a task it doesn't recognize. Check:
- `create_topic_dispatcher(app)` was called
- Task routes are configured correctly
- The dispatcher task name matches in config and code

### Context Helper TypeError

**Error:** `TypeError: context_helper() takes 1 positional argument but 2 were given`

**Cause:** You passed a bound method (instance method) instead of a standalone function.

**Solution:**
```python
# ❌ WRONG - Bound method
obj = MyClass()
TchuEvent.set_context_helper(obj.my_helper)

# ✅ CORRECT - Standalone function
def my_context_helper(event_data):
    return create_context(event_data)

TchuEvent.set_context_helper(my_context_helper)

# ✅ WORKAROUND - Support both signatures
def safe_helper(*args, **kwargs):
    event_data = args[1] if len(args) >= 2 else args[0]
    return create_context(event_data)
```

See [Framework Integration](#framework-integration) for more details.

### Multiple Apps Not Receiving Events

Each app MUST have:
1. Its own unique queue name
2. Queue bound to the `tchu_events` exchange with correct routing patterns
3. The `create_topic_dispatcher()` call in its Celery config
4. Celery worker running
5. Handlers registered (visible in logs at startup)

## Performance

v2.0.0 is significantly faster than v1.x:

- **No task discovery** - Static configuration means no inspection overhead
- **No queue inspection** - Direct routing via AMQP
- **Parallel delivery** - RabbitMQ broadcasts to all queues simultaneously

Expected latency: < 10ms (vs 500-1500ms in v1.x due to inspection)

## Changelog

For detailed version history, see [CHANGELOG.md](./CHANGELOG.md).

### v2.2.26 (2025-11-05) - Current

**🚀 New: Extended Celery Class**

**Added:**
- **NEW**: Extended `Celery` class that wraps standard Celery with tchu-tchu integration
- Import with `from tchu_tchu.django import Celery` for seamless integration
- New `app.message_broker()` method for cleaner configuration API
- Fully compatible with standard Celery - all original methods preserved
- More Pythonic and intuitive than standalone function approach

**Example:**
```python
from tchu_tchu.django import Celery  # Extended Celery class

app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Clean method-based API
app.message_broker(
    queue_name="my_queue",
    subscriber_modules=["app1.subscribers", "app2.subscribers"],
)
```

**Migration:** Optional - `setup_celery_queue()` function still available and fully supported.

---

### v2.2.11 (2025-10-28)

**🚨 Critical Fix: Broadcast Events Now Work**

**Fixed:**
- **CRITICAL**: Fixed broadcast events not being received due to incorrect RabbitMQ queue bindings
- `get_subscribed_routing_keys()` was being called before handlers were registered
- RPC calls worked, but broadcast events failed silently

**Added:**
- New `celery_app` parameter to `get_subscribed_routing_keys()` to force immediate handler registration
- New `force_import` parameter (default: `True`) to control import behavior
- Improved documentation and migration guide

**Migration Required:**
```python
# ❌ OLD (v2.2.9)
all_routing_keys = get_subscribed_routing_keys()

# ✅ NEW (v2.2.11)
all_routing_keys = get_subscribed_routing_keys(celery_app=app)
```

**IMPORTANT:** If upgrading from v2.2.9:
1. Update code to pass `celery_app=app`
2. Delete old queues from RabbitMQ
3. Restart services

See [MIGRATION_2.2.11.md](./MIGRATION_2.2.11.md) for complete upgrade instructions.

---

### Recent Versions

**v2.2.3** - Auto-configuration with `get_subscribed_routing_keys()`  
**v2.2.2** - Fixed `JSONField` serialization errors  
**v2.2.0** - Framework-agnostic with injectable context helpers  
**v2.1.0** - RPC (request-response) support  
**v2.0.0** - Complete redesign with topic exchanges (100x faster)

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
