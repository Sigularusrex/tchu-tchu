# Tchu-Tchu Exchange Mismatch Fix

## Problem Identified

Your tchu-tchu messaging system was broken due to an **exchange name mismatch**:

### ❌ Before Fix
- **Publishers** (old TchuClient): Publishing to `coolset-events` exchange
- **Consumers** (Celery workers): Listening on `tchu_events` exchange  
- **Result**: Messages sent to `coolset-events` never reached workers listening on `tchu_events`

## Root Cause

You had old `TchuClient` wrapper files in various applications that were still using the legacy `tchu.producer.Producer` with the old exchange name:

```python
# OLD CODE (broken)
from tchu.producer import Producer

class TchuClient:
    def __init__(self):
        self.producer = Producer(
            amqp_url=CELERY_BROKER_URL,
            exchange="coolset-events",  # ❌ WRONG EXCHANGE!
            exchange_type="topic",
        )
```

Meanwhile, all your Celery configurations were correctly using `tchu_events`:

```python
# celery.py (correct)
tchu_exchange = Exchange("tchu_events", type="topic", durable=True)
```

## Applications Affected

### 1. ✅ cs-pulse (FIXED)
- **File**: `/pulse/clients/tchu_client.py`
- **Usage**: 11 files importing and using `TchuClient().publish()`
- **Fix**: Created wrapper that redirects to `tchu_tchu.TchuClient`

### 2. ✅ cs-eunice (FIXED)  
- **Files**:
  - `/eunice/clients/tchu_client.py`
  - `/ada/clients/tchu_client.py`
- **Usage**: Multiple subscribers and management commands
- **Fix**: Created wrappers that redirect to `tchu_tchu.TchuClient`

### 3. ✅ cs-common (FIXED)
- **File**: `/cs_common/events/clients/tchu_client.py`
- **Usage**: Dead import (never actually called)
- **Fix**: Removed unused import from `user_repository.py`

### 4. ✅ cs-api (NO ACTION NEEDED)
- **File**: `/gc_api/clients/tchu_client.py` existed but was never imported
- **Result**: Deleted as dead code

## The Fix

Created backward-compatible wrapper classes that redirect the old `TchuClient` interface to the new `tchu_tchu.TchuClient`:

```python
# NEW CODE (fixed)
from tchu_tchu import TchuClient as NewTchuClient

class TchuClient:
    """
    Wrapper that redirects to tchu_tchu.TchuClient.
    This ensures messages go to the correct 'tchu_events' exchange.
    """
    def __init__(self) -> None:
        self._client = NewTchuClient()

    def publish(self, routing_key: str, body: dict) -> None:
        self._client.publish(topic=routing_key, data=body)

    def call(self, routing_key: str, body: dict, timeout: int = 30):
        return self._client.call(topic=routing_key, data=body, timeout=timeout)
```

### Why This Works

The new `tchu_tchu.TchuClient`:
1. Uses the Celery app's configured broker (from settings)
2. Publishes via `send_task('tchu_tchu.dispatch_event', ...)`
3. Celery automatically routes to the correct exchange (`tchu_events`)
4. No hardcoded exchange names!

## Verification

All applications now correctly:
- ✅ Publish to `tchu_events` exchange (via tchu-tchu library)
- ✅ Subscribe to `tchu_events` exchange (via Celery config)
- ✅ Messages flow properly between services

## Next Steps (Optional Cleanup)

Consider migrating from wrapper classes to direct tchu-tchu usage:

```python
# Instead of:
from pulse.clients.tchu_client import TchuClient
TchuClient().publish(routing_key="...", body={...})

# Use directly:
from tchu_tchu import TchuClient  
TchuClient().publish(topic="...", data={...})
```

Or even better, use TchuEvent classes for type-safe event publishing.
