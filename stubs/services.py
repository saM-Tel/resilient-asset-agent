"""
Mock external services for the resilient asset agent assessment.

Simulates a distributed system with three services:
1. LocationService - Returns asset location data (can return stale data)
2. AssetDatabase - Handles persistent writes (supports partial write simulation)
3. CacheService - In-memory cache layer (can timeout or fail independently)

Each service has configurable failure injection knobs to simulate real-world
distributed system failures: timeouts, stale reads, partial writes, and
service unavailability.
"""

import time
import random
from typing import Any


class LocationServiceError(Exception):
    """Base exception for location service errors."""
    pass


class CacheSyncFailure(Exception):
    """Exception raised when cache update fails but DB write succeeded."""
    pass


class StaleDataWarning(UserWarning):
    """Warning raised when stale data is detected."""
    pass


# =============================================================================
# Mock Service State (in-memory, persists across calls during a run)
# =============================================================================

_service_state = {
    "asset_location": {"lat": 40.7128, "lng": -74.0060, "status": "active", "last_updated": None},
    "expected_state": {"lat": 51.5074, "lng": -0.1278, "status": "synced"},  # Target: London
    "db_written": False,
    "cache_updated": False,
}


# =============================================================================
# Configuration / Failure Injection Knobs
# =============================================================================

class ServiceConfig:
    """Global configuration for failure injection."""
    
    # Location service failures
    inject_stale_data = False      # Return cached/stale location data
    inject_timeout = False         # Simulate network timeout
    inject_unavailable = False     # Service completely down
    
    # Database failures
    partial_write = False          # Write succeeds but returns incomplete response
    write_delay = 0.1              # Artificial delay (seconds)
    
    # Cache failures
    cache_timeout = False          # Simulate cache timeout
    cache_unavailable = False      # Cache service down
    
    # General
    enable_latency = True          # Add realistic latency to calls


def reset_service_state():
    """Reset all mock service state. Call at start of each run."""
    global _service_state
    _service_state = {
        "asset_location": {"lat": 40.7128, "lng": -74.0060, "status": "active", "last_updated": None},
        "expected_state": {"lat": 51.5074, "lng": -0.1278, "status": "synced"},
        "db_written": False,
        "cache_updated": False,
    }


# =============================================================================
# Location Service
# =============================================================================

def fetch_asset_location(asset_id: str = "asset_001") -> dict[str, Any]:
    """
    Fetch current asset location from the location service.
    
    Simulates a real API call with potential failures:
    - Stale data (returns old cached coordinates)
    - Timeout (simulates network latency)
    - Service unavailable
    
    Args:
        asset_id: Identifier for the asset to query
        
    Returns:
        Dictionary with location data including lat, lng, status
        
    Raises:
        LocationServiceError: On timeout or service unavailability
    """
    config = ServiceConfig
    
    # Simulate network latency
    if config.enable_latency and not (config.inject_timeout or config.inject_unavailable):
        time.sleep(random.uniform(0.2, 0.5))
    
    # Inject failures
    if config.inject_unavailable:
        raise LocationServiceError("Location service is currently unavailable (503)")
    
    if config.inject_timeout:
        time.sleep(5.0)  # Simulate timeout after 5 seconds
        raise LocationServiceError("Location service request timed out after 5s")
    
    # Return data (potentially stale)
    if config.inject_stale_data:
        import warnings
        warnings.warn(
            "Stale data detected - location not updated in >24 hours",
            StaleDataWarning
        )
        return {
            "asset_id": asset_id,
            "lat": 40.7128,  # Old: New York
            "lng": -74.0060,
            "status": "active",
            "last_updated": "2026-08-12T10:00:00Z",  # Yesterday
            "stale": True
        }
    
    return {
        "asset_id": asset_id,
        "lat": _service_state["asset_location"]["lat"],
        "lng": _service_state["asset_location"]["lng"],
        "status": _service_state["asset_location"]["status"],
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stale": False
    }


# =============================================================================
# Consistency Validator
# =============================================================================

def validate_consistency(asset_data: dict, expected_state: dict = None) -> dict[str, Any]:
    """
    Validate data consistency between current asset state and expected target.
    
    Compares fetched location data against the expected synchronized state to
    determine if corrections are needed.
    
    Args:
        asset_data: Current asset location data from LocationService
        expected_state: Expected target state (defaults to global config)
        
    Returns:
        Dictionary with validation results including is_synced, discrepancies
    """
    time.sleep(0.1)  # Simulate processing
    
    if expected_state is None:
        expected_state = _service_state["expected_state"]
    
    lat_diff = abs(asset_data.get("lat", 0) - expected_state["lat"])
    lng_diff = abs(asset_data.get("lng", 0) - expected_state["lng"])
    
    # Consider "synced" if within 0.01 degrees (~1km)
    is_synced = lat_diff < 0.01 and lng_diff < 0.01
    
    discrepancies = []
    if not is_synced:
        discrepancies.append({
            "field": "latitude",
            "current": asset_data.get("lat"),
            "expected": expected_state["lat"],
            "diff": lat_diff
        })
        discrepancies.append({
            "field": "longitude",
            "current": asset_data.get("lng"),
            "expected": expected_state["lng"],
            "diff": lng_diff
        })
    
    return {
        "is_synced": is_synced,
        "discrepancies": discrepancies,
        "validation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }


# =============================================================================
# Asset Database (Write Layer)
# =============================================================================

def write_db_correction(asset_id: str, correction_data: dict) -> dict[str, Any]:
    """
    Write corrections to the asset database.
    
    Simulates a database write operation that may succeed but return partial
    data, or fail entirely.
    
    Args:
        asset_id: Asset identifier
        correction_data: Data to write (lat, lng, status)
        
    Returns:
        Dictionary with transaction ID and confirmation
        
    Raises:
        Exception: On simulated database failure
    """
    config = ServiceConfig
    
    # Simulate write delay
    time.sleep(config.write_delay)
    
    if config.partial_write:
        # Write succeeds but returns incomplete response (simulates partial write)
        _service_state["db_written"] = True
        return {
            "tx_id": f"tx_{int(time.time())}",
            "status": "partial",  # Incomplete response!
            "message": "Write completed with warnings"
        }
    
    # Normal successful write
    _service_state["db_written"] = True
    _service_state["asset_location"]["lat"] = correction_data.get("lat")
    _service_state["asset_location"]["lng"] = correction_data.get("lng")
    _service_state["asset_location"]["status"] = correction_data.get("status", "synced")
    
    return {
        "tx_id": f"tx_{int(time.time())}",
        "status": "completed",
        "message": "Database write successful"
    }


# =============================================================================
# Cache Service (Fast Layer)
# =============================================================================

def update_cache(asset_id: str, cache_data: dict) -> dict[str, Any]:
    """
    Update the distributed cache with latest asset state.
    
    This is the most failure-prone service in our simulation - it can timeout
    or fail independently even when the database write succeeds. This creates
    the exact scenario we need to demonstrate recovery from partial failures.
    
    Args:
        asset_id: Asset identifier
        cache_data: Data to cache
        
    Returns:
        Dictionary with cache update confirmation
        
    Raises:
        CacheSyncFailure: On timeout or service unavailability
    """
    config = ServiceConfig
    
    # Simulate network latency for cache (typically faster than DB)
    if config.enable_latency and not (config.cache_timeout or config.cache_unavailable):
        time.sleep(random.uniform(0.1, 0.3))
    
    # Inject failures
    if config.cache_unavailable:
        raise CacheSyncFailure("Cache service is currently unavailable (503)")
    
    if config.cache_timeout:
        time.sleep(3.0)  # Simulate timeout
        raise CacheSyncFailure("Cache update timed out after 3s")
    
    # Successful cache update
    _service_state["cache_updated"] = True
    
    return {
        "status": "SUCCESS",
        "cached_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "asset_id": asset_id,
        "ttl_seconds": 3600
    }


# =============================================================================
# Health Check Utility
# =============================================================================

def check_service_health() -> dict[str, bool]:
    """
    Check health status of all mock services.
    
    Returns:
        Dictionary mapping service names to their health status (True/False)
    """
    return {
        "location_service": not ServiceConfig.inject_unavailable and not ServiceConfig.inject_timeout,
        "database": True,  # DB is always up in our simulation
        "cache": not ServiceConfig.cache_unavailable and not ServiceConfig.cache_timeout
    }
