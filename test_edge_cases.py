"""
Comprehensive test script verifying all edge cases and bug fixes.
"""

import sys
import os
import sqlite3
import time
from pathlib import Path

# Add workspace to path
sys.path.insert(0, str(Path(__file__).parent))

from agent.checkpointer import Checkpointer
from agent.runner import AssetSyncAgent
from stubs.services import write_db_correction, update_cache, reset_service_state

def test_checkpointer_failed_steps_dedup():
    print("[TEST 1] Testing get_failed_steps deduplication on retries...")
    test_db = "test_temp_state.db"
    if os.path.exists(test_db):
        os.remove(test_db)
    
    cp = Checkpointer(db_path=test_db)
    run_id = "test-retry-run"
    cp.create_run(run_id)
    
    # 1. Step fails on attempt 1
    cp.save_step(run_id=run_id, step_name="fetch_location", step_order=1, status="FAILED", error_message="timeout")
    failed = cp.get_failed_steps(run_id)
    assert len(failed) == 1, f"Expected 1 failed step, got {len(failed)}"
    assert failed[0]["step_name"] == "fetch_location"
    
    # 2. Step succeeds on retry attempt 2
    cp.save_step(run_id=run_id, step_name="fetch_location", step_order=1, status="COMPLETED", output_data={"lat": 1.0, "lng": 2.0})
    
    completed = cp.get_completed_steps(run_id)
    failed = cp.get_failed_steps(run_id)
    
    assert len(completed) == 1, f"Expected 1 completed step, got {len(completed)}"
    assert len(failed) == 0, f"Expected 0 failed steps after successful retry, got {len(failed)}"
    
    cp.close()
    if os.path.exists(test_db):
        os.remove(test_db)
    print("  [OK] Step retry deduplication works correctly.")

def test_already_synced_checkpoint():
    print("\n[TEST 2] Testing write_db_correction 'already synced' checkpointing...")
    test_db = "test_temp_state.db"
    if os.path.exists(test_db):
        os.remove(test_db)
    
    cp = Checkpointer(db_path=test_db)
    run_id = "test-sync-run"
    cp.create_run(run_id)
    
    agent = AssetSyncAgent(client=None, checkpointer=cp, run_id=run_id)
    
    # Seed completed fetch_location and validate_consistency (is_synced = True)
    cp.save_step(run_id=run_id, step_name="fetch_location", step_order=1, status="COMPLETED", output_data={"lat": 51.5074, "lng": -0.1278})
    cp.save_step(run_id=run_id, step_name="validate_consistency", step_order=2, status="COMPLETED", output_data={"is_synced": True, "discrepancies": []})
    
    # Execute write_db_correction action
    success, res = agent.execute_action("write_db_correction", parameters=None)
    assert success is True, f"Expected execute_action to succeed, got {success}"
    
    # Verify write_db_correction is marked as COMPLETED in checkpointer
    completed = cp.get_completed_steps(run_id)
    completed_names = [s["step_name"] for s in completed]
    assert "write_db_correction" in completed_names, "write_db_correction was NOT saved to checkpointer!"
    
    cp.close()
    if os.path.exists(test_db):
        os.remove(test_db)
    print("  [OK] 'already synced' write_db_correction properly checkpointed.")

def test_unique_tx_ids():
    print("\n[TEST 3] Testing tx_id uniqueness...")
    reset_service_state()
    tx_ids = set()
    for i in range(10):
        res = write_db_correction("asset_001", {"lat": 1.0, "lng": 2.0}, idempotency_key=f"key_{i}")
        tx_ids.add(res["tx_id"])
    assert len(tx_ids) == 10, f"Expected 10 unique tx_ids, got {len(tx_ids)}"
    print("  [OK] tx_ids are unique across sub-second calls.")

def test_none_parameters_safety():
    print("\n[TEST 4] Testing safe execution with parameters=None...")
    test_db = "test_temp_state.db"
    if os.path.exists(test_db):
        os.remove(test_db)
    
    cp = Checkpointer(db_path=test_db)
    run_id = "test-none-params"
    cp.create_run(run_id)
    
    agent = AssetSyncAgent(client=None, checkpointer=cp, run_id=run_id)
    # execute fetch_location with parameters=None
    success, res = agent.execute_action("fetch_location", parameters=None)
    assert success is True
    assert "lat" in res["data"]
    
    cp.close()
    if os.path.exists(test_db):
        os.remove(test_db)
    print("  [OK] parameters=None handled safely without exceptions.")

if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING EDGE CASE VERIFICATION TESTS")
    print("=" * 60)
    test_checkpointer_failed_steps_dedup()
    test_already_synced_checkpoint()
    test_unique_tx_ids()
    test_none_parameters_safety()
    print("\n" + "=" * 60)
    print("[ALL TESTS PASSED SUCCESSFULLY]")
    print("=" * 60)
