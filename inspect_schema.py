#!/usr/bin/env python
"""Check the actual database schema"""

import sqlite3
from pathlib import Path

DB_PATH = Path("agent_state.db")

print("\n" + "="*70)
print("DATABASE SCHEMA INSPECTION")
print("="*70 + "\n")

try:
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    
    print(f"Tables: {tables}\n")
    
    for table in tables:
        print(f"[{table}]")
        cursor.execute(f"PRAGMA table_info({table})")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  {col[1]:20s} {col[2]:15s} {'NOT NULL' if col[3] else 'nullable'}")
        print()
    
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
