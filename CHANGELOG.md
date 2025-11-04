# Changelog

All notable changes to tchu-tchu will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.21] - 2025-11-04

### Fixed
- **CRITICAL**: Fixed intermittent RPC call failures due to race conditions with multiple workers
  - Added `track_started=True` to dispatcher task to properly track task execution state
  - Added `acks_late=True` to ensure tasks are only acknowledged after completion (prevents lost results)
  - Added `reject_on_worker_lost=True` to requeue tasks if worker dies during processing
  - Set `worker_prefetch_multiplier=1` in `setup_celery_queue()` to prevent workers from prefetching multiple RPC tasks
  - These changes ensure reliable RPC result delivery even with multiple Celery workers

### Changed
- `dispatch_event` task now properly configured for RPC reliability with late acknowledgment and task tracking
- `setup_celery_queue()` now automatically configures Celery for reliable RPC handling
- No migration required - just update tchu-tchu and restart services

### Root Cause
- Multiple Celery workers consuming from the same queue could create race conditions
- Default Celery prefetching allowed workers to grab multiple tasks before processing
- Tasks were acknowledged before completion, risking result loss on worker failure
- This caused intermittent failures where some RPC calls succeeded and others failed

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

