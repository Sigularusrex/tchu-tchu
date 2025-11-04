# Fix Summary: v2.2.20 - RPC Handlers Not Being Registered

## Date
November 4, 2025

## Problem
RPC calls were failing with the error:
```
ERROR: Failed to list documents: RPC call failed: No handlers found for routing key 'rpc.cs_pulse.documents.document.list'
```

## Root Cause
The `setup_celery_queue()` function was using `@celery_app.on_after_configure.connect` to register a callback that would import subscriber modules and register handlers. However, this callback **never executed** because:

1. In the typical celery.py setup, the sequence is:
   ```python
   app = Celery("my_app")
   app.config_from_object("django.conf:settings", namespace="CELERY")  # Fires on_after_configure
   setup_celery_queue(app, ...)  # Registers callback AFTER it already fired
   ```

2. The `on_after_configure` signal fires when `config_from_object()` is called
3. `setup_celery_queue()` is called **after** `config_from_object()` 
4. Therefore, the callback registered by `setup_celery_queue()` never executes
5. Subscriber modules are never imported
6. Handlers are never registered
7. RabbitMQ bindings were created (from previous runs) but no handlers exist to process messages

## Evidence
Logs showed:
- ✅ `setup_celery_queue() called` - function was called
- ✅ `Registered on_after_configure callback` - callback was registered
- ❌ `🚀 TCHU-TCHU SETUP` - **MISSING** - callback never executed
- ❌ `Registered handler...` - **MISSING** - handlers never registered

RabbitMQ bindings existed:
```
tchu_events exchange pulse_queue queue rpc.cs_pulse.documents.document.list []
```

But the handler registry was empty when messages arrived.

## Solution
Changed `setup_celery_queue()` to use `@celery_app.on_after_finalize.connect` instead of `on_after_configure`:

```python
# OLD (broken)
@celery_app.on_after_configure.connect
def _setup_tchu_queue(sender, **kwargs):
    # This never ran because on_after_configure already fired
    ...

# NEW (fixed)
@celery_app.on_after_finalize.connect
def _setup_tchu_queue(sender, **kwargs):
    # This runs when Celery is fully finalized
    ...
```

### Why `on_after_finalize` Works
- Fires when the Celery app is **fully configured and finalized**
- Happens **after** Django apps are ready
- Happens **before** workers start processing tasks
- Always fires, regardless of when `setup_celery_queue()` is called

## Changes Made
1. **tchu_tchu/django/celery.py**: Changed from `on_after_configure` to `on_after_finalize`
2. **tchu_tchu/version.py**: Bumped version to 2.2.19
3. **pyproject.toml**: Updated version to 2.2.19
4. **CHANGELOG.md**: Documented the fix

## Migration Steps
Services using tchu-tchu need to:

1. Update tchu-tchu to v2.2.20:
   ```bash
   pip install --upgrade tchu-tchu==2.2.20
   ```

2. Restart Celery workers:
   ```bash
   docker compose restart <service>-celery
   ```

3. Verify handlers are registered in logs:
   ```
   🚀 TCHU-TCHU SETUP: <queue_name>
   📦 Importing subscriber module: ...
   Registered handler '...' for routing key '...'
   📊 Total handlers registered: X
   ```

## No Code Changes Required
The fix is entirely in the tchu-tchu library. Services using `setup_celery_queue()` don't need any changes to their code - just update the package version and restart.

## Testing
After deploying v2.2.20:

1. Check logs show handlers being registered:
   ```bash
   docker compose logs <service>-celery | grep "TCHU-TCHU SETUP"
   ```

2. Test RPC calls:
   ```python
   from tchu_tchu import TchuClient
   client = TchuClient()
   result = client.call('rpc.cs_pulse.documents.document.list', {'company_ids': [67]})
   ```

3. Should return data instead of "No handlers found" error

## Related Issues
This is a recurring issue that was "fixed" before but broke again. Previous attempts:
- Fixed exchange mismatch (coolset-events vs tchu_events)
- Fixed direct imports vs wrappers
- But the core callback timing issue remained

This fix addresses the root cause of why handlers weren't being registered.

## Prevention
To prevent this in the future:
1. The fix ensures callbacks fire regardless of call order
2. Added detailed logging to make it obvious when setup doesn't execute
3. Document clearly shows expected log output for verification

## Files Changed
- tchu_tchu/django/celery.py
- tchu_tchu/version.py  
- pyproject.toml
- CHANGELOG.md
- FIX_SUMMARY_2.2.19.md (this file)

