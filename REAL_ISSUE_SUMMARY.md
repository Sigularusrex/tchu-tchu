# Tchu-Tchu Real Issue & Solution

## The Real Problem

The library **was working** - the exchange mismatch was a red herring. The actual issue was:

**Connection Error in Web Process:**
```
kombu.exceptions.OperationalError: [Errno 111] Connection refused
```

This occurred when calling RPC methods from Django views because:
1. `TchuClient()` uses Celery's `current_app` by default
2. In the **web process**, `current_app` wasn't properly configured with broker settings
3. The wrapper files were using old `tchu.producer.Producer` with wrong exchange

## The Solution

### What We Did

1. **Deleted all local `TchuClient` wrapper files:**
   - `cs-pulse/pulse/clients/tchu_client.py`
   - `cs-eunice/eunice/clients/tchu_client.py`  
   - `cs-eunice/ada/clients/tchu_client.py`
   - `cs-common/cs_common/events/clients/tchu_client.py`

2. **Updated all imports to use tchu-tchu directly:**
   ```python
   # OLD (wrapper)
   from pulse.clients.tchu_client import TchuClient
   
   # NEW (direct)
   from tchu_tchu import TchuClient
   ```

3. **Result:** 34 files now importing directly from `tchu_tchu`

### Why This Works

The `tchu_tchu.TchuClient`:
- Automatically uses Celery's `current_app` 
- Falls back to creating its own Celery instance if needed
- Uses broker configuration from Django settings (`CELERY_BROKER_URL`)
- Publishes to the correct `tchu_events` exchange via Celery tasks

## What Was Wrong Before

The old wrapper files were using the legacy `tchu.producer.Producer`:

```python
# OLD (broken)
from tchu.producer import Producer

class TchuClient:
    def __init__(self):
        self.producer = Producer(
            amqp_url=CELERY_BROKER_URL,
            exchange="coolset-events",  # ❌ Wrong exchange!
            exchange_type="topic",
        )
```

This caused two problems:
1. **Wrong exchange:** Publishing to `coolset-events` instead of `tchu_events`
2. **Direct connection:** Creating new connections instead of using Celery's pooled connections

## Current State

### Applications Fixed
- ✅ **cs-pulse:** 11 files updated
- ✅ **cs-eunice:** 15 files updated (eunice + ada)
- ✅ **cs-api:** Already using tchu-tchu directly
- ✅ **cs-common:** Unused import removed

### Remaining Issue

The original connection error (`[Errno 111] Connection refused`) suggests that when `TchuClient()` is instantiated in the web process without arguments, it may not have proper Celery app configuration.

**Two possible solutions:**

#### Option A: Import celery app in Django settings (recommended)
Add to `settings/base.py` (at the end):
```python
# Initialize Celery for web process (needed for RPC calls)
import gc_api.celery as celery_module
CELERY_APP = celery_module.app
```

#### Option B: Pass celery_app explicitly (if needed)
```python
from gc_api.celery import app as celery_app
client = TchuClient(celery_app=celery_app)
```

But you said you don't want Option B, so Option A is recommended.

## Testing

To verify the fix works:
1. Restart all Docker containers
2. Test an RPC call that was failing:
   ```bash
   curl http://localhost:8000/api/pulse/document/
   ```
3. Should return documents instead of connection error

## Key Takeaway

**Direct imports > Wrapper classes**
- Simpler code
- Fewer places for configuration errors
- Easier to maintain
- Library handles connection pooling properly

