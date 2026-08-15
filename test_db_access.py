#!/usr/bin/env python
"""Test if visualizer server can read database"""

import sqlite3
from pathlib import Path

DB_PATH = Path("data/agent_state.db")

print("\n" + "="*70)
print("TESTING VISUALIZER DATABASE ACCESS")
print("="*70 + "\n")

try:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Test 1: Database stats
    print("[TEST 1] Database Statistics:")
    cursor.execute("SELECT COUNT(*) FROM runs")
    print(f"  - Runs: {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT COUNT(*) FROM steps")
    print(f"  - Steps: {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT COUNT(*) FROM decisions")
    print(f"  - Decisions: {cursor.fetchone()[0]}")
    
    # Test 2: Most recent run
    print("\n[TEST 2] Most Recent Run:")
    cursor.execute("SELECT DISTINCT run_id FROM steps ORDER BY started_at DESC LIMIT 1")
    run_result = cursor.fetchone()
    if run_result:
        run_id = run_result[0]
        print(f"  - Run ID: {run_id}")
        
        cursor.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
        status_result = cursor.fetchone()
        if status_result:
            print(f"  - Status: {status_result[0]}")
        
        cursor.execute("SELECT COUNT(*) FROM steps WHERE run_id = ?", (run_id,))
        step_count = cursor.fetchone()[0]
        print(f"  - Steps: {step_count}")
        
        cursor.execute("SELECT COUNT(*) FROM decisions WHERE run_id = ?", (run_id,))
        decision_count = cursor.fetchone()[0]
        print(f"  - Decisions: {decision_count}")
        
        # Test 3: Sample step
        print(f"\n[TEST 3] First Step of {run_id}:")
        cursor.execute("""
            SELECT id, step_name, status, started_at 
            FROM steps 
            WHERE run_id = ? 
            ORDER BY id ASC 
            LIMIT 1
        """, (run_id,))
        step = cursor.fetchone()
        if step:
            print(f"  - ID: {step[0]}")
            print(f"  - Name: {step[1]}")
            print(f"  - Status: {step[2]}")
            print(f"  - Time: {step[3]}")
        
        # Test 4: Sample decision
        print(f"\n[TEST 4] First Decision of {run_id}:")
        cursor.execute("""
            SELECT id, step_name, next_action, reasoning
            FROM decisions 
            WHERE run_id = ? 
            ORDER BY id ASC 
            LIMIT 1
        """, (run_id,))
        decision = cursor.fetchone()
        if decision:
            print(f"  - ID: {decision[0]}")
            print(f"  - Iteration: {decision[1]}")
            print(f"  - Action: {decision[2]}")
            print(f"  - Reasoning: {decision[3][:60]}..." if decision[3] else "  - Reasoning: None")
    
    conn.close()
    print("\n" + "="*70)
    print("[OK] ALL TESTS PASSED - Database is readable!")
    print("="*70 + "\n")
    
except Exception as e:
    print(f"\n[ERROR] {e}")
    import traceback
    traceback.print_exc()
