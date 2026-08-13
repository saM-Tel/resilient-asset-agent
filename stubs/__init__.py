"""
Stub package for mock external services.

Simulates a distributed system with three services:
- LocationService: Returns asset location data (can return stale data)
- AssetDatabase: Handles persistent writes (supports partial write simulation)
- CacheService: In-memory cache layer (can timeout or fail independently)

Each service has configurable failure injection knobs to simulate real-world
distributed system failures.
"""

from stubs.services import (
    ServiceConfig,
    fetch_asset_location,
    validate_consistency,
    write_db_correction,
    update_cache,
    reset_service_state,
    LocationServiceError,
    CacheSyncFailure,
    StaleDataWarning,
)

__all__ = [
    "ServiceConfig",
    "fetch_asset_location",
    "validate_consistency", 
    "write_db_correction",
    "update_cache",
    "reset_service_state",
    "LocationServiceError",
    "CacheSyncFailure",
    "StaleDataWarning",
]
