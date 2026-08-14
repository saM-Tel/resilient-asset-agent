"""Show exactly what's in the agent_state.db file."""
import sqlite3
import json

conn = sqlite3.connect("agent_state.db")
c = conn.cursor()

print("=" * 70)
print("DATABASE CONTENTS - agent_state.db")
print("=" * 70)

# --- TABLES ---
print("\n[1] TABLES:")
tables = [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()]
for t in tables:
    count = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  • {t}: {count} rows")

# --- RUNS TABLE ---
print("\n[2] RUNS TABLE (overall execution status):")
rows = c.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 5").fetchall()
if not rows:
    print("  (empty)")
else:
    for r in rows:
        run_id, status, created, completed = r
        # Count steps/decisions for this run
        step_count = c.execute(
            "SELECT COUNT(*) FROM steps WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        dec_count = c.execute(
            "SELECT COUNT(*) FROM decisions WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        print(f"  • {run_id}")
        print(f"    status: {status}")
        print(f"    created: {created:.1f} ({step_count} steps, {dec_count} decisions)")

# --- STEPS TABLE ---
print("\n[3] STEPS TABLE (what each tool did):")
rows = c.execute(
    "SELECT * FROM steps ORDER BY id DESC LIMIT 8"
).fetchall()
if not rows:
    print("  (empty)")
else:
    for r in reversed(rows):
        sid, run_id, step_name, order, status, inp, outp, err, started, done = r
        # Show a snippet of input/output
        inp_preview = ""
        if inp:
            try:
                d = json.loads(inp)
                inp_preview = f" | input: {json.dumps(d)[:80]}"
            except:
                pass
        outp_preview = ""
        if outp:
            try:
                d = json.loads(outp)
                outp_preview = f" | output: {json.dumps(d)[:80]}"
            except:
                pass
        err_preview = ""
        if err:
            err_preview = f" | ERROR: {err[:60]}"

        print(f"  • [{order}] {step_name} → {status}")
        print(f"    run_id={run_id}{inp_preview}{outp_preview}{err_preview}")

# --- DECISIONS TABLE ---
print("\n[4] DECISIONS TABLE (what the LLM decided):")
rows = c.execute(
    "SELECT * FROM decisions ORDER BY id DESC LIMIT 8"
).fetchall()
if not rows:
    print("  (empty)")
else:
    for r in reversed(rows):
        did, run_id, iter_name, reasoning, action, ts = r
        print(f"  • {iter_name}: chose '{action}'")
        print(f"    reasoning: {reasoning[:100]}")

conn.close()
print("\n" + "=" * 70)
