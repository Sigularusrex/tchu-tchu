# Changelog

All notable changes to tchu-tchu will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.26] - 2025-11-05

### Added
- **NEW**: Extended `Celery` class that wraps standard `celery.Celery` with tchu-tchu integration
  - Import with `from tchu_tchu.django import Celery` for seamless Django integration
  - Provides `app.message_broker()` method for cleaner, more Pythonic API
  - **Parameter naming**: Uses `include` parameter (matches Celery's naming convention)
  - **Auto-discovery**: `include` parameter is optional
    - If not provided to `message_broker()`, uses Celery's `include` constructor parameter
    - No automatic path modifications - full module paths required
    - Example: `Celery("app", include=["app1.subscribers", "app2.subscribers"])`
  - Stores `include` from kwargs in `self.tchu_include` for easy access
  - Fully backward compatible - all standard Celery functionality preserved
  - More intuitive than standalone function approach
- Added comprehensive documentation in `EXTENDED_CELERY_USAGE.md`
- Updated `tchu_tchu.django.__init__.py` to export the extended `Celery` class

### Changed
- `message_broker()` method wraps `setup_celery_queue()` for better encapsulation
- Uses `include` parameter name to match Celery's API (not `subscriber_modules`)
- `include` parameter is optional - defaults to Celery's `include` from constructor
- README updated to show extended Celery class as the recommended approach
- Standalone `setup_celery_queue()` function remains available for backward compatibility

### Examples
```python
from tchu_tchu.django import Celery  # Extended class

# With explicit include modules
app = Celery("my_app")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.message_broker(
    queue_name="my_queue",
    include=["app1.subscribers", "app2.subscribers"],
)

# With auto-discovery from Celery's include parameter
app = Celery("my_app", include=["app1.subscribers", "app2.subscribers"])
app.config_from_object("django.conf:settings", namespace="CELERY")
app.message_broker(queue_name="my_queue")  # Uses app1.subscribers, app2.subscribers
```

## [2.2.25] - 2025-11-04

### Fixed
- **CRITICAL**: Fixed `@celery.shared_task` tasks broadcasting to all services
  - Removed `task_default_exchange` setting that was causing regular tasks to use broadcast exchange
  - Regular @celery.shared_task tasks now use direct routing to service's own queue
  - Only tchu-tchu event dispatcher uses the broadcast topic exchange
  - Prevents tasks from one service being sent to workers of other services

### Changed
- `setup_celery_queue()` now only sets `task_default_queue` without changing default exchange
- Regular Celery tasks stay within their service, broadcast events go to all services

## [2.2.24] - 2025-11-04

### Fixed
- **CRITICAL**: Fixed `@celery.shared_task` tasks not being routed to any queue
  - Added `task_default_queue` setting to route all tasks (including regular Celery tasks) to tchu-tchu queue
  - Ensures `.delay()` and `@shared_task` work properly alongside `@subscribe` handlers
  - Previously, only tchu-tchu dispatcher tasks were routed, leaving regular tasks orphaned

### Changed
- `setup_celery_queue()` now sets `task_default_queue` to ensure all tasks go to the configured queue
- Both event-driven handlers (@subscribe) and async tasks (@shared_task) now work together

## [2.2.23] - 2025-11-04

### Changed
- Added explicit logging for `worker_prefetch_multiplier=1` setting to verify it's being applied
- Makes it easier to diagnose if the RPC reliability fix is active

## [2.2.22] - 2025-11-04

### Fixed
- **CRITICAL**: Fixed intermittent RPC call failures with `rpc://` result backend
  - Set `worker_prefetch_multiplier=1` to prevent workers from prefetching multiple tasks
  - Removed `acks_late=True` settings that are incompatible with RabbitMQ's `rpc://` result backend
  - This is the KEY fix: prefetch multiplier prevents race conditions when multiple workers handle RPC calls
  - Works with both `rpc://` (RabbitMQ) and Redis result backends

### Changed
- Simplified task configuration to work with all result backend types
- `setup_celery_queue()` now only sets `worker_prefetch_multiplier=1` (the critical fix)
- No migration required - just update tchu-tchu and restart services

### Root Cause
- Default Celery `worker_prefetch_multiplier=4` caused workers to prefetch multiple RPC tasks
- Multiple workers prefetching the same or overlapping tasks created race conditions with result storage
- With `rpc://` backend, temporary result queues had timing issues with prefetched tasks
- Setting prefetch to 1 ensures each worker processes one RPC call at a time (eliminates races)

## [2.2.21] - 2025-11-04 (Yanked - incompatible with rpc:// backend)

### Fixed
- Attempted fix for intermittent RPC failures but incompatible with `rpc://` result backend
- Use v2.2.22 instead

## [2.2.20] - 2025-11-04

### Fixed
- **CRITICAL**: Fixed `setup_celery_queue()` callback never executing, causing RPC handlers to not be registered
  - Added `worker_process_init` signal to import subscriber modules when worker starts
  - Added graceful exception handling for `AppRegistryNotReady` errors during Django initialization
  - Allows both Celery workers and web processes to initialize successfully without crashes
  - Fixes "No handlers found for routing key" errors for RPC calls

### Changed
- `setup_celery_queue()` now uses dual approach: immediate import (if Django ready) + `worker_process_init` signal
- Gracefully handles `AppRegistryNotReady` exceptions when called during Django app initialization
- No migration required - just update tchu-tchu and restart services

## [2.2.11] - 2025-10-28

### Fixed
- **CRITICAL**: Fixed broadcast events not being received due to incorrect RabbitMQ queue bindings
  - `get_subscribed_routing_keys()` was being called before handlers were registered
  - Resulted in empty routing key list and queues with exact-match-only bindings
  - RPC calls worked, but broadcast events failed silently

### Added
- New `celery_app` parameter to `get_subscribed_routing_keys()` to force immediate handler registration
- New `force_import` parameter (default: `True`) to control import behavior
- Improved documentation and examples in function docstring

### Changed
- `get_subscribed_routing_keys()` now calls `celery_app.loader.import_default_modules()` if `celery_app` is provided
- This ensures handlers are registered before queue configuration

### Migration Required
- **BREAKING**: Services must pass `celery_app` parameter: `get_subscribed_routing_keys(celery_app=app)`
- **CRITICAL**: Delete old queues from RabbitMQ to remove incorrect persistent bindings
- See [MIGRATION_2.2.11.md](./MIGRATION_2.2.11.md) for detailed upgrade instructions

## [2.2.10] - 2025-10-28 (Unreleased)

### Changed
- Enhanced error messages for RPC calls with no handlers
- Improved logging to distinguish between RPC and broadcast event routing issues

## [2.2.9] - 2025-10-28

### Added
- Initial stable release with RPC and broadcast event support
- Topic exchange-based routing with Celery
- `@subscribe` decorator for handler registration
- `CeleryProducer` for publishing events and making RPC calls
- `create_topic_dispatcher` for event dispatching

### Changed
- Migrated from Pika-based implementation to Celery-only implementation
- Unified RPC and broadcast events under single topic exchange

---

## Upgrade Guide

### From 2.2.9 to 2.2.11

This is a **critical bug fix release**. All services using broadcast events should upgrade immediately.

**Quick upgrade:**
```bash
# 1. Update library
pip install tchu-tchu==2.2.11

# 2. Update celery.py
# FROM: all_routing_keys = get_subscribed_routing_keys()
# TO:   all_routing_keys = get_subscribed_routing_keys(celery_app=app)

# 3. Delete old RabbitMQ queues
rabbitmqctl delete_queue your_queue_name

# 4. Restart services
docker-compose restart your_service
```

See [MIGRATION_2.2.11.md](./MIGRATION_2.2.11.md) for complete instructions.

---

## Version History

- **2.2.11** (2025-10-28): Fixed broadcast event routing
- **2.2.9** (2025-10-28): Stable Celery-based release
- **2.2.0-2.2.8**: Development versions
- **2.1.x**: Pika-based implementation (deprecated)
- **2.0.x**: Initial release

