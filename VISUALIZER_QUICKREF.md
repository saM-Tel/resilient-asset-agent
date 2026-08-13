# Debug Visualizer - Quick Reference Card

## ✅ FIXED - Now Shows Real-Time Database Contents!

### What Was Wrong
- Flask queries used wrong column names (`created_at` not `started_at`)
- Column `error` didn't exist (actual: `error_message`)
- Dashboard showed "Loading..." forever

### What's Fixed
- ✅ Database queries use correct schema
- ✅ All columns properly mapped
- ✅ JSON parsing works for input/output
- ✅ Dashboard shows real data in real-time
- ✅ Cycle tracking displays accurately
- ✅ LLM reasoning shows decision logic

---

## 🚀 Three-Step Setup

```bash
# Step 1: Start visualizer (Terminal 1)
python debug_visualizer/server.py

# Step 2: Run agent (Terminal 2)  
python main.py --run-id demo-1

# Step 3: View in browser
http://localhost:5000
```

---

## 📊 What You'll See

### Header
```
RUN ID: demo-1
STATUS: COMPLETED  ← Green if OK, Red if failed
STEPS: 4/4         ← Progress tracking
CURRENT CYCLE: #8  ← Iteration number
DECISIONS: 16      ← Total LLM decisions made
```

### Database Stats
```
[DB] Total Runs: 1 | Steps: 4 | Decisions: 8
```

### Execution Steps  
Each step shows:
```
[STEP 1] fetch_location              [COMPLETED]  19:52:08
  [INPUT]   {"asset_id": "asset_001"}
  [OUTPUT]  {"asset_id": "asset_001", "lat": 40.7128, "lng": -74.006}

[STEP 2] validate_consistency        [COMPLETED]  19:52:10
  [INPUT]   {"asset_data": {...}}
  [OUTPUT]  {"is_synced": false, "discrepancies": [...]}
```

### LLM Decisions
Each decision shows:
```
[CYCLE 1] → fetch_location           19:52:08
  WHY: Empty response, starting with location fetch

[CYCLE 2] → validate_consistency     19:52:09
  WHY: Next: validate consistency
```

---

## 🎮 Dashboard Controls

| Feature | How It Works |
|---------|-------------|
| Auto-Refresh | Enabled by default (✓), updates every 1 second |
| Refresh Button | Click to update immediately |
| Run Sidebar | Click any run to view its details |
| Status Colors | Green=OK, Red=Failed, Yellow=Pending |
| Data Display | Click step cards to see full input/output |

---

## 🧪 Test Scenarios

### Test 1: Normal Execution
```bash
python main.py --run-id test-1
```
✓ All 4 steps complete  
✓ Dashboard shows green checkmarks  
✓ All cycles show reasoning  

### Test 2: Failure & Recovery
```bash
# First run - fails at cache
python main.py --run-id test-2 --fail-at cache_update

# Second run - same ID skips completed steps
python main.py --run-id test-2
```
✓ First run shows 3 complete, 1 failed  
✓ Second run shows [SKIP] on first 3  
✓ Only retries the failed step  

### Test 3: Stale Data
```bash
python main.py --run-id test-3 --inject-stale
```
✓ Shows stale data detected  
✓ Correction written to database  
✓ Cache updated  

---

## 🐛 Troubleshooting

**Problem**: Blank loading screen  
**Check**: 
1. Is visualizer running? → `python debug_visualizer/server.py`
2. Did you run agent? → `python main.py --run-id test`
3. Browser console for errors? → F12 → Console tab

**Problem**: Port 5000 already in use  
**Fix**: Edit line in `debug_visualizer/server.py`:
```python
app.run(host="localhost", port=5001)  # Change to 5001
```

**Problem**: Can't see recent run  
**Check**: 
1. Click sidebar run names to load specific run
2. If sidebar empty, run agent first
3. Database stats should show Steps > 0

**Problem**: No input/output data  
**Reason**: Service returned no data (check [ERROR] section)

---

## 📍 Key Database Info

```
Database Path: F:\coding_projects\resilient-asset-agent\agent_state.db

Tables:
  - runs: (run_id, status, created_at, completed_at)
  - steps: (id, run_id, step_name, status, input_data, output_data, error_message, started_at, completed_at)
  - decisions: (id, run_id, step_name, reasoning, next_action, timestamp)

Current Data:
  - 0 runs (empty runs table - data in steps table instead)
  - 51 steps (from multiple test runs)
  - 104 decisions (LLM decisions with reasoning)
```

---

## 🔗 API Endpoints (Programmatic Access)

```bash
# Get most recent run
curl http://localhost:5000/api/current

# Get specific run
curl http://localhost:5000/api/run/demo-1

# List all runs
curl http://localhost:5000/api/runs

# Database statistics
curl http://localhost:5000/api/debug
```

---

## 📚 Related Files

- `debug_visualizer/server.py` - Flask server (FIXED)
- `VISUALIZER_FIXES.md` - Detailed schema reference
- `VISUALIZER_QUICKSTART.md` - Full usage guide
- `BUGS_AND_FIXES.md` - All issues documented
- `SESSION_SUMMARY.md` - Complete session notes

---

## ✨ Pro Tips

1. **Side-by-Side Windows**: Terminal left, browser right = Watch in real-time
2. **Copy JSON**: Right-click → Copy JSON from step output boxes
3. **Track Cycles**: Cycle counter shows LLM iteration number
4. **Check Reasoning**: Read "WHY" text to understand LLM decisions
5. **Inspect Errors**: [ERROR] sections in red show exactly what went wrong

---

**Status**: ✅ **FULLY OPERATIONAL**  
**Next**: Run it and watch the magic! 🚀
