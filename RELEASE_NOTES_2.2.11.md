# Release Notes: tchu-tchu v2.2.11

**Release Date:** October 28, 2025  
**Type:** Critical Bug Fix  
**Priority:** High - Update Recommended for All Users

---

## 🐛 What Was Fixed

### Critical Issue: Broadcast Events Not Received

**Problem:**
- RPC calls worked ✅
- Broadcast events silently failed ❌
- Queues had incorrect exact-match bindings instead of wildcard patterns

**Root Cause:**
- `get_subscribed_routing_keys()` was called before handlers were registered
- `app.autodiscover_tasks()` is lazy and doesn't import modules immediately
- Resulted in empty routing key list `[]`
- Queues created with fallback binding (exact match to queue name)

**Impact:**
- Any broadcast event (non-RPC routing keys) was not being delivered to subscribers
- Services appeared healthy but were missing critical events
- No error messages logged (silent failure)

---

## ✨ What Changed

### Enhanced `get_subscribed_routing_keys()`

**New Signature:**
```python
def get_subscribed_routing_keys(
    exclude_patterns: Optional[list[str]] = None,
    celery_app=None,  # ← NEW
    force_import: bool = True,  # ← NEW
) -> list[str]:
```

**New Parameters:**
- `celery_app`: Pass your Celery app instance to force immediate handler registration
- `force_import`: Control whether to force imports (default: True)

**Behavior:**
- If `celery_app` is provided, calls `celery_app.loader.import_default_modules()`
- This forces immediate task discovery and handler registration
- Ensures handlers are registered BEFORE queue configuration

---

## 📦 Upgrade Instructions

### For Package Maintainers

```bash
# Build new version
cd /path/to/tchu-tchu
poetry build
poetry publish
```

### For Service Developers

See:
- **Quick Start**: [QUICK_START_2.2.11.md](./QUICK_START_2.2.11.md)
- **Full Migration Guide**: [MIGRATION_2.2.11.md](./MIGRATION_2.2.11.md)

**TL;DR:**
1. Update tchu-tchu: `pip install tchu-tchu==2.2.11`
2. Change: `get_subscribed_routing_keys()` → `get_subscribed_routing_keys(celery_app=app)`
3. Delete old queues: `rabbitmqctl delete_queue <queue_name>`
4. Restart services

---

## 🔍 Technical Details

### Before (v2.2.9)

```python
# celery.py
app = Celery("scranton")
app.autodiscover_tasks(["scranton.subscribers"])  # Lazy - doesn't import yet

all_routing_keys = get_subscribed_routing_keys()  # Returns [] - handlers not registered!
# Creates queue with no bindings → defaults to exact match "scranton"
```

**RabbitMQ Bindings:**
```
tchu_events  exchange  scranton_queue  queue  scranton  []  ❌ Exact match only
```

### After (v2.2.11)

```python
# celery.py
app = Celery("scranton")
app.autodiscover_tasks(["scranton.subscribers"])

all_routing_keys = get_subscribed_routing_keys(celery_app=app)  # Forces import
# Returns ['coolset.scranton.#', 'pulse.compliance.#', ...]
```

**RabbitMQ Bindings:**
```
tchu_events  exchange  scranton_queue  queue  coolset.scranton.#  []  ✅ Wildcard
tchu_events  exchange  scranton_queue  queue  pulse.compliance.#  []  ✅ Wildcard
```

---

## ⚠️ Breaking Changes

**Configuration Update Required:**

All services using `get_subscribed_routing_keys()` must update their `celery.py`:

```python
# BEFORE
all_routing_keys = get_subscribed_routing_keys()

# AFTER
all_routing_keys = get_subscribed_routing_keys(celery_app=app)
```

**Queue Deletion Required:**

Old queues have persistent incorrect bindings. Must delete and recreate:

```bash
rabbitmqctl delete_queue scranton_queue
rabbitmqctl delete_queue data_room_queue
rabbitmqctl delete_queue pulse_queue
rabbitmqctl delete_queue coolset_queue
```

---

## 🎯 Testing Recommendations

### Test 1: Verify Handler Registration

Check logs for handler registration messages:

```
INFO:tchu_tchu.registry:Registered handler 'OrderEnrichedEvent_handler' for routing key 'coolset.scranton.order.enriched'
INFO:scranton.celery:Configuring 8 RabbitMQ bindings:
  [1] coolset.scranton.information_request.prepared
  [2] coolset.accounts.company.invite.accepted
  [3] pulse.compliance.risk_assessment.completed
  ...
```

### Test 2: Verify Queue Bindings

```bash
rabbitmqctl list_bindings | grep "scranton_queue"
```

Should show **wildcard patterns**, not exact matches.

### Test 3: Test Broadcast Event

```python
# Publish from one service
producer.publish(
    routing_key="coolset.scranton.order.enriched",
    payload={"order_id": 123},
)

# Verify received in subscriber service (check logs)
```

### Test 4: Test RPC (Should Still Work)

```python
result = producer.call(
    routing_key="rpc.data_room.documents.list",
    payload={"company_id": 67},
)
```

---

## 📊 Performance Impact

| Metric | Impact |
|--------|--------|
| **Startup time** | +100-500ms (one-time) |
| **Runtime performance** | No change |
| **Memory** | Negligible |

The slight startup delay is worth fixing silent event delivery failures!

---

## 🙏 Credits

Thanks to the team for:
- Identifying the RPC vs broadcast event discrepancy
- Debugging RabbitMQ bindings
- Testing the fix across multiple services

---

## 📝 Files Changed

- `tchu_tchu/subscriber.py` - Enhanced `get_subscribed_routing_keys()`
- `tchu_tchu/version.py` - Bumped to 2.2.11
- `pyproject.toml` - Updated version
- `README.md` - Added upgrade notice
- `CHANGELOG.md` - Added release notes
- `MIGRATION_2.2.11.md` - Migration guide
- `QUICK_START_2.2.11.md` - Quick reference

---

## 🚀 Next Steps

1. **Package maintainer**: Build and publish v2.2.11
2. **Service teams**: Follow [QUICK_START_2.2.11.md](./QUICK_START_2.2.11.md)
3. **Test**: Verify broadcast events work end-to-end
4. **Monitor**: Watch for any routing issues post-upgrade

