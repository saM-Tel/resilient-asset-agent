import sqlite3
import json

try:
    conn = sqlite3.connect('agent_state.db')
    c = conn.cursor()
    
    # Get all tables
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in c.fetchall()]
    
    print("=" * 70)
    print("DATABASE CONTENTS")
    print("=" * 70)
    print(f"\nTables found: {tables}\n")
    
    for table in tables:
        c.execute(f"SELECT COUNT(*) FROM {table}")
        count = c.fetchone()[0]
        print(f"\n[{table}] - {count} records")
        print("-" * 70)
        
        # Show schema
        c.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in c.fetchall()]
        print(f"Columns: {', '.join(columns)}\n")
        
        # Show all rows
        c.execute(f"SELECT * FROM {table}")
        for i, row in enumerate(c.fetchall(), 1):
            print(f"  Record {i}: {row}")
    
    conn.close()
    print("\n" + "=" * 70)
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
