# Quick Start: tchu-tchu v2.2.11 Upgrade

## 🚨 What's Fixed

**Broadcast events now work!** They were silently failing because queue bindings were incorrect.

---

## ⚡ 3-Step Upgrade

### Step 1: Update Your Code

In **every service's `celery.py`**, change one line:

```python
# ❌ BEFORE (v2.2.9)
all_routing_keys = get_subscribed_routing_keys()

# ✅ AFTER (v2.2.11)
all_routing_keys = get_subscribed_routing_keys(celery_app=app)
```

### Step 2: Delete Old Queues

```bash
docker exec -it rabbitmq-container bash
rabbitmqctl delete_queue scranton_queue
rabbitmqctl delete_queue data_room_queue
rabbitmqctl delete_queue pulse_queue
rabbitmqctl delete_queue coolset_queue
exit
```

### Step 3: Restart Services

```bash
docker-compose restart scranton data-room pulse coolset
```

---

## ✅ Verify It Works

Check queue bindings:

```bash
docker exec -it rabbitmq-container rabbitmqctl list_bindings | grep "scranton_queue"
```

**Should see wildcards** like:
```
tchu_events  exchange  scranton_queue  queue  coolset.scranton.#  []
tchu_events  exchange  scranton_queue  queue  pulse.compliance.risk_assessment.completed  []
```

**NOT exact matches** like:
```
tchu_events  exchange  scranton_queue  queue  scranton  []  ❌
```

---

## 📋 Service Checklist

- [ ] **scranton**: Updated `celery.py` + deleted queue + restarted
- [ ] **data-room**: Updated `celery.py` + deleted queue + restarted  
- [ ] **pulse**: Updated `celery.py` + deleted queue + restarted
- [ ] **coolset**: Updated `celery.py` + deleted queue + restarted

---

## 🔍 What Was Broken?

- **RPC**: ✅ Worked (you were testing this)
- **Broadcast events**: ❌ Broken (silently failing)

### Why?

`get_subscribed_routing_keys()` was called **before** handlers registered, returning `[]`. This created queues with wrong bindings.

### The Fix

Pass `celery_app=app` to force immediate handler registration:

```python
all_routing_keys = get_subscribed_routing_keys(celery_app=app)
```

---

## 📖 Full Documentation

- **Migration Guide**: [MIGRATION_2.2.11.md](./MIGRATION_2.2.11.md)
- **Changelog**: [CHANGELOG.md](./CHANGELOG.md)

---

## ❓ Need Help?

1. Verify handlers are registered (check logs for `Registered handler` messages)
2. Verify queue bindings match your routing keys
3. Make sure you deleted old queues before restarting

