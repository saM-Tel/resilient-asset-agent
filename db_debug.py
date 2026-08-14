"""Debug why runs table shows UNKNOWN status."""
import sqlite3
import json

conn = sqlite3.connect("agent_state.db")
c = conn.cursor()

print("=" * 70)
print("RUNS TABLE DEBUG")
print("=" * 70)

# Check if runs table has any data
run_count = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
step_count = c.execute("SELECT COUNT(*) FROM steps").fetchone()[0]
dec_count = c.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]

print(f"\nRuns: {run_count} | Steps: {step_count} | Decisions: {dec_count}")

# Show all runs
print("\n[runs table]:")
rows = c.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 10").fetchall()
if not rows:
    print("  (EMPTY - no run records exist!)")
else:
    for r in rows:
        print(f"  {r}")

# Show distinct run_ids from steps table
print("\n[distinct run_ids in steps]:")
rows = c.execute("SELECT DISTINCT run_id FROM steps ORDER BY started_at DESC LIMIT 10").fetchall()
for r in rows:
    # Check if this run_id exists in runs table
    has_run = c.execute("SELECT COUNT(*) FROM runs WHERE run_id=?", (r[0],)).fetchone()[0]
    print(f"  {r[0]} → runs_table_exists={has_run}")

conn.close()
