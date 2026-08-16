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
    Write corrections to database with idempotency guard and sub-task tracking.
    
    Implements Upgrade 1 (Sub-Task Granularity) and Upgrade 3 (Idempotency Keys):
    - Generates idempotency key: f"{run_id}:write_db_correction:database_write"
    - Tracks database_write sub-task with SUCCESS/FAILED/UNKNOWN status
    - Emits events to audit trail for every sub-task transition
    
    Args:
        checkpointer: Checkpoint store instance
        run_id: Current execution run identifier
        correction_data: Data to write (lat, lng, status)
        
    Returns:
        ToolResult with transaction confirmation and sub-task status
    """
    # Idempotency check - skip if already completed OR partially failed.
    # A PARTIAL_FAILURE means the DB write committed server-side (only the
    # response was incomplete), so re-executing would be a duplicate write.
    existing = checkpointer.get_step_result(run_id, "write_db_correction")
    if existing and existing["status"] in ("COMPLETED", "PARTIAL_FAILURE"):
        status_label = existing["status"]
        
        # Active Read-Verification Probe (Refinement 2): when recovering from a
        # PARTIAL_FAILURE, verify the transaction actually committed before
        # skipping. This distinguishes UNKNOWN (write may have succeeded) from
        # FAILED (write definitely did not happen).
        if status_label == "PARTIAL_FAILURE":
            tx_id = existing.get("output_data", {}).get("tx_id")
            try:
                from stubs.services import verify_db_transaction
                if tx_id and verify_db_transaction(tx_id):
                    checkpointer.emit_event(
                        run_id=run_id,
                        event="VERIFICATION_PROBE_SUCCESS",
                        sub_task="database_write",
                        tx_id=tx_id,
                        details={"message": "Read probe confirmed transaction exists on server"}
                    )
                    print(f"  [PROBE] write_db_correction: Verified tx {tx_id} exists on database. Skipping write.")
                    return ToolResult(success=True, data=existing.get("output_data"))
            except Exception as e:
                print(f"  [WARN] Verification probe failed for tx {tx_id}: {e}")
        
        print(f"  [SKIP] write_db_correction: Already {status_label}, not re-executing (idempotency)")
        return ToolResult(success=True, data=existing.get("output_data"))
    
    # Generate idempotency key for this mutation (Upgrade 3)
    idempotency_key = f"{run_id}:write_db_correction:database_write"
    
    # Emit event: step started (Upgrade 2)
    checkpointer.emit_event(run_id, "STEP_STARTED", sub_task="database_write", 
                           tx_id=None, details={"idempotency_key": idempotency_key})
    
    # Execute the tool
    try:
        print("  [EXECUTE] write_db_correction: Writing to database...")
        result = write_db_correction("asset_001", correction_data, 
                                     idempotency_key=idempotency_key)
        
        tx_id = result.get('tx_id', 'unknown')
        
        # Check for partial write - database succeeded but response incomplete
        if result.get('status') == 'partial':
            # Sub-task 1: database_write succeeded (Upgrade 1)
            checkpointer.save_sub_task(
                run_id=run_id, step_name="write_db_correction",
                sub_task_name="database_write", status="SUCCESS", tx_id=tx_id,
                idempotency_key=idempotency_key
            )
            checkpointer.emit_event(run_id, "SUBTASK_COMMITTED", sub_task="database_write",
                                   tx_id=tx_id, details={"status": "partial_response"})
            
            # Mark step as PARTIAL_FAILURE (Upgrade 1)
            checkpointer.save_step(
                run_id=run_id, step_name="write_db_correction", step_order=3,
                status="PARTIAL_FAILURE",
                input_data={"correction_data": correction_data},
                output_data=result,
                error_message="Database write succeeded but returned partial response",
                idempotency_key=idempotency_key
            )
            
            print(f"  [PARTIAL] write_db_correction: DB written but incomplete response (tx={tx_id})")
            return ToolResult(success=True, data={**result, "sub_task_status": "PARTIAL_FAILURE"})
        
        # Normal successful write
        checkpointer.save_sub_task(
            run_id=run_id, step_name="write_db_correction",
            sub_task_name="database_write", status="SUCCESS", tx_id=tx_id,
            idempotency_key=idempotency_key
        )
        checkpointer.emit_event(run_id, "SUBTASK_COMMITTED", sub_task="database_write",
                               tx_id=tx_id, details={"status": "completed"})
        
        checkpointer.save_step(
            run_id=run_id, step_name="write_db_correction", step_order=3,
            status="COMPLETED",
            input_data={"correction_data": correction_data},
            output_data=result,
            idempotency_key=idempotency_key
        )
        
        print(f"  [OK] write_db_correction: Transaction {tx_id} ({result['status']})")
        return ToolResult(success=True, data=result)
    
    except TimeoutError as e:
        # Network timeout - result UNKNOWN (Upgrade 1)
        error_msg = str(e)
        checkpointer.save_sub_task(
            run_id=run_id, step_name="write_db_correction",
            sub_task_name="database_write", status="UNKNOWN", error_message=error_msg,
            idempotency_key=idempotency_key
        )
        checkpointer.emit_event(run_id, "NETWORK_TIMEOUT", sub_task="database_write",
                               tx_id=None, details={"error": error_msg})
        checkpointer.save_step(
            run_id=run_id, step_name="write_db_correction", step_order=3,
            status="PARTIAL_FAILURE",
            input_data={"correction_data": correction_data},
            error_message=f"TimeoutError: {error_msg}",
            idempotency_key=idempotency_key
        )
        print(f"  [UNKNOWN] write_db_correction: {error_msg} (write may have succeeded)")
        return ToolResult(success=False, error=error_msg)
    
    except Exception as e:
        error_msg = str(e)
        checkpointer.save_sub_task(
            run_id=run_id, step_name="write_db_correction",
            sub_task_name="database_write", status="FAILED", error_message=error_msg,
            idempotency_key=idempotency_key
        )
        checkpointer.emit_event(run_id, "SUBTASK_FAILED", sub_task="database_write",
                               tx_id=None, details={"error": error_msg})
        checkpointer.save_step(
            run_id=run_id, step_name="write_db_correction", step_order=3,
            status="FAILED",
            input_data={"correction_data": correction_data},
            error_message=error_msg,
            idempotency_key=idempotency_key
        )
        print(f"  [FAIL] write_db_correction: {error_msg}")
        return ToolResult(success=False, error=error_msg)


def execute_update_cache(checkpointer: Checkpointer, run_id: str, 
                          cache_data: dict) -> ToolResult:
    """
    Update cache with idempotency guard and sub-task tracking.
    
    Implements Upgrade 1 (Sub-Task Granularity) and Upgrade 3 (Idempotency Keys):
    - Generates idempotency key: f"{run_id}:update_cache:cache_invalidation"
    - Tracks cache_invalidation sub-task with SUCCESS/FAILED/UNKNOWN status
    - Emits events to audit trail for every sub-task transition
    - Handles UNKNOWN status when cache times out (write may have succeeded)
    
    This is the most failure-prone step - simulates a service that can timeout
    or fail independently even when DB write succeeded.
    
    Args:
        checkpointer: Checkpoint store instance
        run_id: Current execution run identifier
        cache_data: Data to cache
        
    Returns:
        ToolResult with cache update confirmation and sub-task status
    """
    # Idempotency check - ONLY skip if already fully completed.
    # PARTIAL_FAILURE (timeout) means the cache write outcome is indeterminate,
    # so we MUST re-execute to ensure the cache is updated.
    existing = checkpointer.get_step_result(run_id, "update_cache")
    if existing and existing["status"] == "COMPLETED":
        print(f"  [SKIP] update_cache: Already completed, using cached result")
        return ToolResult(success=True, data=existing.get("output_data"))
    
    # Generate idempotency key for this mutation (Upgrade 3)
    idempotency_key = f"{run_id}:update_cache:cache_invalidation"
    
    # Emit event: step started (Upgrade 2)
    checkpointer.emit_event(run_id, "STEP_STARTED", sub_task="cache_invalidation",
                           tx_id=None, details={"idempotency_key": idempotency_key})
    
    # Execute the tool
    try:
        print("  [EXECUTE] update_cache: Updating distributed cache...")
        result = update_cache("asset_001", cache_data,
                             idempotency_key=idempotency_key)
        
        tx_id = result.get('tx_id', 'unknown')
        
        # Successful cache update
        checkpointer.save_sub_task(
            run_id=run_id, step_name="update_cache",
            sub_task_name="cache_invalidation", status="SUCCESS", tx_id=tx_id,
            idempotency_key=idempotency_key
        )
        checkpointer.emit_event(run_id, "SUBTASK_COMMITTED", sub_task="cache_invalidation",
                               tx_id=tx_id, details={"status": "SUCCESS"})
        
        checkpointer.save_step(
            run_id=run_id, step_name="update_cache", step_order=4,
            status="COMPLETED",
            input_data={"cache_data": cache_data},
            output_data=result,
            idempotency_key=idempotency_key
        )
        
        print(f"  [OK] update_cache: Cache updated successfully (tx={tx_id})")
        return ToolResult(success=True, data=result)
    
    except TimeoutError as e:
        # Network timeout - result UNKNOWN (Upgrade 1)
        error_msg = str(e)
        checkpointer.save_sub_task(
            run_id=run_id, step_name="update_cache",
            sub_task_name="cache_invalidation", status="UNKNOWN", error_message=error_msg,
            idempotency_key=idempotency_key
        )
        checkpointer.emit_event(run_id, "NETWORK_TIMEOUT", sub_task="cache_invalidation",
                               tx_id=None, details={"error": error_msg})
        checkpointer.save_step(
            run_id=run_id, step_name="update_cache", step_order=4,
            status="PARTIAL_FAILURE",
            input_data={"cache_data": cache_data},
            error_message=f"TimeoutError: {error_msg}",
            idempotency_key=idempotency_key
        )
        print(f"  [UNKNOWN] update_cache: {error_msg} (cache update may have succeeded)")
        return ToolResult(success=False, error=error_msg)
    
    except Exception as e:
        error_msg = str(e)
        checkpointer.save_sub_task(
            run_id=run_id, step_name="update_cache",
            sub_task_name="cache_invalidation", status="FAILED", error_message=error_msg,
            idempotency_key=idempotency_key
        )
        checkpointer.emit_event(run_id, "SUBTASK_FAILED", sub_task="cache_invalidation",
                               tx_id=None, details={"error": error_msg})
        checkpointer.save_step(
            run_id=run_id, step_name="update_cache", step_order=4,
            status="FAILED",
            input_data={"cache_data": cache_data},
            error_message=error_msg,
            idempotency_key=idempotency_key
        )
        print(f"  [FAIL] update_cache: {error_msg}")
        return ToolResult(success=False, error=error_msg)
