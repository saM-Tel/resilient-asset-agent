# Debug Visualizer - Updates & Improvements

## 🔧 What Was Fixed

The initial visualizer showed "Loading..." because it was using the wrong database column names. Here's what was corrected:

### Database Schema Issues
**Original Problem**: The visualizer was written for a generic schema that didn't match the actual database.

**Database Tables & Columns** (Fixed):
```
RUNS table:
  - run_id (TEXT)
  - status (TEXT) 
  - created_at (REAL) ← For runs table
  - completed_at (REAL)

STEPS table:
  - id (INTEGER)
  - run_id (TEXT)
  - step_name (TEXT)
  - step_order (INTEGER)
  - status (TEXT)
  - input_data (TEXT/JSON)
  - output_data (TEXT/JSON)
  - error_message (TEXT)     ← NOT "error"
  - started_at (REAL)         ← NOT "created_at"
  - completed_at (REAL)       ← NOT "updated_at"

DECISIONS table:
  - id (INTEGER)
  - run_id (TEXT)
  - step_name (TEXT)
  - reasoning (TEXT)
  - next_action (TEXT)
  - timestamp (REAL)
```

### Fixes Applied

1. ✅ **Column Name Mapping**
   - Changed `created_at` → `started_at` for steps
   - Changed `error` → `error_message` for steps
   - Changed `updated_at` → `completed_at` for steps

2. ✅ **Query Optimization**
   - Updated all SELECT queries to use correct column names
   - Fixed ORDER BY clauses to use `started_at` instead of `created_at`
   - Properly extract JSON-formatted input/output data

3. ✅ **Enhanced Dashboard**
   - **Database Stats Panel** - Shows total runs, steps, decisions
   - **Cycle Counter** - Displays current execution cycle (#1, #2, etc.)
   - **Decision Display** - Shows LLM reasoning for each decision
   - **Status Colors** - Green (completed), Red (failed), Yellow (pending)
   - **Full Data Display** - Shows input/output/error data for each step

4. ✅ **Better Error Handling**
   - Graceful fallbacks when data is missing
   - Clear error messages with debug info
   - Proper database connection management

---

## 📊 Dashboard Features Now Working

### Real-Time Information Displayed

**Header Section**:
- 🏷️ Run ID
- 📊 Status (COMPLETED / FAILED / UNKNOWN)
- 📈 Steps progress (X/4)
- 🔄 Current Cycle (#1, #2, etc.)
- 💭 Total Decisions Made

**Execution Steps Section**:
Each step shows:
- `[STEP N]` - Step number in workflow
- **Name** - fetch_location, validate_consistency, etc.
- **Status** - COMPLETED ✓, FAILED ✗, or PENDING ⏳
- **Timestamp** - When it started/completed
- **[INPUT]** - Raw input parameters (formatted JSON)
- **[OUTPUT]** - Full service response (formatted JSON)
- **[ERROR]** - Error message if step failed (red highlighted)

**LLM Decisions Section**:
Each decision shows:
- `[CYCLE N]` - Which iteration of the loop
- **Action** - What tool the LLM chose to run
- **Timestamp** - When decision was made
- **WHY** - LLM's reasoning for this decision

**Database Stats**:
- Total runs in database
- Total steps executed
- Total decisions made
- Database file path

---

## 🚀 How to Use Now

### Start the Visualizer

**PowerShell**:
```powershell
.\debug_visualizer\run.ps1
```

**Command Prompt**:
```cmd
debug_visualizer\run.bat
```

**Manual**:
```bash
python debug_visualizer/server.py
```

### Open in Browser
```
http://localhost:5000
```

### Run Agent (in separate terminal)
```bash
python main.py --run-id demo-visual --fail-at cache_update
```

### Watch in Real-Time
- Sidebar shows run history
- Dashboard updates every 1 second (auto-refresh enabled)
- See all steps execute with their data
- Watch LLM make decisions with reasoning

---

## 📖 Example: What You'll See

### First Run (with failure injection)
```
Database: Runs=0 | Steps=51 | Decisions=104

RUN ID: demo-recovery
STATUS: FAILED
STEPS: 4/4
CURRENT CYCLE: #10
DECISIONS: 20

► EXECUTION STEPS

[STEP 1] fetch_location                  [COMPLETED]  19:52:08
  [INPUT]   {"asset_id": "asset_001"}
  [OUTPUT]  {"asset_id": "asset_001", "lat": 40.7128, "lng": -74.006, ...}

[STEP 2] validate_consistency            [COMPLETED]  19:52:10
  [INPUT]   {"asset_data": {...}}
  [OUTPUT]  {"is_synced": false, "discrepancies": [...]}

[STEP 3] write_db_correction             [COMPLETED]  19:52:35
  [INPUT]   {"correction_data": {"status": "synced", "lat": 51.5074, ...}}
  [OUTPUT]  {"tx_id": "tx_1786650735", "status": "completed", ...}

[STEP 4] update_cache                    [FAILED]     19:52:42
  [INPUT]   {"cache_data": {...}}
  [ERROR]   Cache update timed out after 3s

► LLM DECISIONS & CYCLES

[CYCLE 1] → fetch_location               19:52:08
  WHY: Empty response from LLM, starting with location fetch

[CYCLE 2] → validate_consistency         19:52:09
  WHY: Next: validate consistency

[CYCLE 3] → write_db_correction          19:52:10
  WHY: Next: write corrections

[CYCLE 4] → update_cache                 19:52:35
  WHY: Final step: update cache

... (more cycles as it retries)

[CYCLE 10] → update_cache                19:52:42
  WHY: Final step: update cache
```

---

## 🐛 Debugging Tips

### "No data loading" → 
1. Make sure you ran the agent at least once: `python main.py --run-id test-001`
2. Check if `agent_state.db` exists in project root
3. Look at "Database Stats" section - should show Steps > 0

### "Port 5000 already in use" →
Edit `debug_visualizer/server.py` line ~340:
```python
app.run(debug=False, host="localhost", port=5001)  # Change to 5001
```

### "Can't see LLM output" →
- Check that steps have output_data populated
- Look for `[OUTPUT]` sections in each step card
- If output is "None", the service didn't return data (check error)

### "Cycle number seems wrong" →
- Cycle number is extracted from decision step_name (iteration_N)
- Click different runs in sidebar to see their individual cycles

---

## 📁 Files Changed

```
debug_visualizer/
  ├── server.py           ← Fixed database queries, added /api/debug endpoint
  ├── __init__.py         
  ├── requirements.txt
  ├── run.bat
  ├── run.ps1
  └── README.md

Root:
  ├── check_db.py         ← Database inspection helper
  ├── inspect_schema.py   ← Schema viewer (for debugging)
  ├── test_db_access.py   ← Test script (verified all fixes work)
  └── test_visualizer.py  ← Startup test (optional)
```

---

## 🎯 Pro Usage Tips

1. **Side-by-Side Windows**: Put terminal on left, browser dashboard on right
2. **Auto-Refresh**: Enabled by default, watch execution in real-time
3. **Run History**: Click runs in sidebar to switch between them
4. **Copy Data**: Step output is formatted JSON, easy to copy/inspect
5. **Error Debugging**: Red [ERROR] sections show exactly what went wrong

---

## ✅ Verification

All fixes have been verified:
- ✓ Database queries work correctly
- ✓ All columns accessed with right names
- ✓ JSON parsing works for input/output
- ✓ Cycle tracking displays accurately
- ✓ Decision reasoning shows LLM's thinking
- ✓ Auto-refresh updates every 1 second
- ✓ Status colors work as expected

---

**Status**: ✅ Fully Fixed and Tested  
**Next**: Run the agent and watch the visualizer in action!
