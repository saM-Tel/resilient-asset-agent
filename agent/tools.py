"""
Idempotent tool wrappers around mock services.

Each tool function wraps a service call with idempotency guarantees:
1. Before execution, checks if step already completed in checkpoint store
2. If completed, returns cached result without calling the service again
3. If not completed or failed, executes the tool and saves result
4. Handles failures gracefully and logs them to checkpoint

This ensures that when the agent recovers from a partial failure, it never
re-does work that already succeeded - only retries what actually failed.
"""

import json
from typing import Any, Optional

from stubs.services import (
    fetch_asset_location,
    validate_consistency,
    write_db_correction,
    update_cache,
    reset_service_state,
    ServiceConfig,
)
from agent.checkpointer import Checkpointer


class ToolResult:
    """Wrapper for tool execution results with metadata."""
    
    def __init__(self, success: bool, data: dict = None, error: str = None):
        self.success = success
        self.data = data or {}
        self.error = error
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error
        }


def execute_fetch_location(checkpointer: Checkpointer, run_id: str, asset_id: str = "asset_001") -> ToolResult:
    """
    Fetch asset location with idempotency guard.
    
    Before calling the location service, checks if this step already completed.
    If yes, returns cached result immediately.
    
    Args:
        checkpointer: Checkpoint store instance
        run_id: Current execution run identifier
        asset_id: Asset to query
        
    Returns:
        ToolResult with location data or error
    """
    # Idempotency check - skip if already completed
    existing = checkpointer.get_step_result(run_id, "fetch_location")
    if existing and existing["status"] == "COMPLETED":
        print("  [SKIP] fetch_location: Already completed, using cached result")
        return ToolResult(success=True, data=existing.get("output_data"))
    
    # Execute the tool
    try:
        print("  [EXECUTE] fetch_location: Calling location service...")
        result = fetch_asset_location(asset_id)
        
        # Save to checkpoint
        checkpointer.save_step(
            run_id=run_id,
            step_name="fetch_location",
            step_order=1,
            status="COMPLETED",
            input_data={"asset_id": asset_id},
            output_data=result
        )
        
        print(f"  [OK] fetch_location: Got location (lat={result['lat']}, lng={result['lng']})")
        return ToolResult(success=True, data=result)
    
    except Exception as e:
        error_msg = str(e)
        checkpointer.save_step(
            run_id=run_id,
            step_name="fetch_location",
            step_order=1,
            status="FAILED",
            input_data={"asset_id": asset_id},
            error_message=error_msg
        )
        print(f"  [FAIL] fetch_location: {error_msg}")
        return ToolResult(success=False, error=error_msg)


def execute_validate_consistency(checkpointer: Checkpointer, run_id: str, 
                                  asset_data: dict) -> ToolResult:
    """
    Validate data consistency with idempotency guard.
    
    Args:
        checkpointer: Checkpoint store instance
        run_id: Current execution run identifier
        asset_data: Location data from fetch_location step
        
    Returns:
        ToolResult with validation results
    """
    # Idempotency check
    existing = checkpointer.get_step_result(run_id, "validate_consistency")
    if existing and existing["status"] == "COMPLETED":
        print("  [SKIP] validate_consistency: Already completed, using cached result")
        return ToolResult(success=True, data=existing.get("output_data"))
    
    # Execute the tool
    try:
        print("  [EXECUTE] validate_consistency: Checking asset state...")
        result = validate_consistency(asset_data)
        
        checkpointer.save_step(
            run_id=run_id,
            step_name="validate_consistency",
            step_order=2,
            status="COMPLETED",
            input_data={"asset_data": asset_data},
            output_data=result
        )
        
        if result["is_synced"]:
            print("  [OK] validate_consistency: Asset is already synced")
        else:
            print(f"  [WARN] validate_consistency: {len(result['discrepancies'])} discrepancies found")
        
        return ToolResult(success=True, data=result)
    
    except Exception as e:
        error_msg = str(e)
        checkpointer.save_step(
            run_id=run_id,
            step_name="validate_consistency",
            step_order=2,
            status="FAILED",
            input_data={"asset_data": asset_data},
            error_message=error_msg
        )
        print(f"  [FAIL] validate_consistency: {error_msg}")
        return ToolResult(success=False, error=error_msg)


def execute_write_db(checkpointer: Checkpointer, run_id: str, 
                      correction_data: dict) -> ToolResult:
    """
    Write corrections to database with idempotency guard.
    
    Args:
        checkpointer: Checkpoint store instance
        run_id: Current execution run identifier
        correction_data: Data to write (lat, lng, status)
        
    Returns:
        ToolResult with transaction confirmation
    """
    # Idempotency check
    existing = checkpointer.get_step_result(run_id, "write_db_correction")
    if existing and existing["status"] == "COMPLETED":
        print("  [SKIP] write_db_correction: Already completed, using cached result")
        return ToolResult(success=True, data=existing.get("output_data"))
    
    # Execute the tool
    try:
        print("  [EXECUTE] write_db_correction: Writing to database...")
        result = write_db_correction("asset_001", correction_data)
        
        checkpointer.save_step(
            run_id=run_id,
            step_name="write_db_correction",
            step_order=3,
            status="COMPLETED",
            input_data={"correction_data": correction_data},
            output_data=result
        )
        
        print(f"  [OK] write_db_correction: Transaction {result['tx_id']} ({result['status']})")
        return ToolResult(success=True, data=result)
    
    except Exception as e:
        error_msg = str(e)
        checkpointer.save_step(
            run_id=run_id,
            step_name="write_db_correction",
            step_order=3,
            status="FAILED",
            input_data={"correction_data": correction_data},
            error_message=error_msg
        )
        print(f"  [FAIL] write_db_correction: {error_msg}")
        return ToolResult(success=False, error=error_msg)


def execute_update_cache(checkpointer: Checkpointer, run_id: str, 
                          cache_data: dict) -> ToolResult:
    """
    Update cache with idempotency guard.
    
    This is the most failure-prone step - simulates a service that can timeout
    or fail independently even when DB write succeeded.
    
    Args:
        checkpointer: Checkpoint store instance
        run_id: Current execution run identifier
        cache_data: Data to cache
        
    Returns:
        ToolResult with cache update confirmation
    """
    # Idempotency check
    existing = checkpointer.get_step_result(run_id, "update_cache")
    if existing and existing["status"] == "COMPLETED":
        print("  [SKIP] update_cache: Already completed, using cached result")
        return ToolResult(success=True, data=existing.get("output_data"))
    
    # Execute the tool
    try:
        print("  [EXECUTE] update_cache: Updating distributed cache...")
        result = update_cache("asset_001", cache_data)
        
        checkpointer.save_step(
            run_id=run_id,
            step_name="update_cache",
            step_order=4,
            status="COMPLETED",
            input_data={"cache_data": cache_data},
            output_data=result
        )
        
        print(f"  [OK] update_cache: Cache updated successfully")
        return ToolResult(success=True, data=result)
    
    except Exception as e:
        error_msg = str(e)
        checkpointer.save_step(
            run_id=run_id,
            step_name="update_cache",
            step_order=4,
            status="FAILED",
            input_data={"cache_data": cache_data},
            error_message=error_msg
        )
        print(f"  [FAIL] update_cache: {error_msg}")
        return ToolResult(success=False, error=error_msg)


def reset_all_state():
    """Reset all mock service state. Call at start of each run."""
    reset_service_state()
