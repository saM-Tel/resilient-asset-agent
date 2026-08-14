# Asset Agent Debug Visualizer

A real-time web-based dashboard for monitoring and debugging the Resilient Asset Agent.

## Features

- 🎯 **Real-time Monitoring**: Auto-refreshing dashboard (1-second updates)
- 📊 **Execution Timeline**: View all steps with timestamps and status
- 🧠 **LLM Decision Tracking**: See what decisions the agent made and why
- 📝 **Step Details**: Full output and error information for each step
- 🔄 **Run History**: Quick access to previous runs
- 🎨 **Visual Status Indicators**: Color-coded status (✓ Completed, ✗ Failed, ⏳ Pending)

## Quick Start

### Option 1: Use the Launcher (Easiest)

**PowerShell:**
```powershell
.\debug_visualizer\run.ps1
```

**Command Prompt:**
```cmd
debug_visualizer\run.bat
```

This activates your venv, installs Flask if needed, and starts the dashboard on http://localhost:5000.

### Option 2: Manual Start

```bash
# Activate venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r debug_visualizer/requirements.txt

# Start visualizer
python debug_visualizer/server.py
```

Then open **http://localhost:5000** in your browser.

## Dashboard Sections

### � Run Info (Header)
- Current status (COMPLETED, FAILED, PENDING)
- Steps completed count (e.g., 4/4)
- Current cycle / iteration number
- Total LLM decisions made

### 📋 Execution Steps
Each step card shows:
- Step name and timestamp
- Status badge (color-coded)
- Input data (formatted JSON)
- Output data (formatted JSON)
- Error details (if any, shown in red)

**Step Status Colors:**
- 🟢 Green = COMPLETED
- 🔴 Red = FAILED
- 🟡 Yellow = PENDING

### 💭 LLM Decisions
Each decision card shows:
- Iteration number (`[CYCLE N]`)
- Action chosen by LLM
- Reasoning/explanation (the "WHY")
- Timestamp

## Example Workflow — Failure & Recovery Demo

1. **Terminal 1 - Start Visualizer:**
   ```bash
   python debug_visualizer/server.py
   ```

2. **Terminal 2 - Run Agent with Failure Injection:**
   ```bash
   python main.py --run-id demo-fail --fail-at cache_update
   ```
   Watch: Steps 1-3 complete, Step 4 fails (cache timeout).

3. **Terminal 2 - Retry Same Run (still failing):**
   ```bash
   python main.py --run-id demo-fail --fail-at cache_update
   ```
   Watch: Steps 1-3 are SKIPPED (cached), Step 4 fails again.

4. **Terminal 2 - Remove Failure Injection:**
   ```bash
   python main.py --run-id demo-fail
   ```
   Watch: Steps 1-3 skipped, Step 4 completes → Status: COMPLETED ✅

This demonstrates **idempotent execution and intelligent failure recovery**.

## How It Works

The visualizer reads from the SQLite checkpoint database (`agent_state.db`) that the agent maintains:

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Agent Run   │────▶│  agent_state.db  │────▶│ Flask Dashboard │
│ (main.py)    │     │  (SQLite)        │     │ (:5000)         │
└──────────────┘     └──────────────────┘     └─────────────────┘
                       Tables:
                         - runs (run_id, status, created_at, completed_at)
                         - steps (id, run_id, step_name, status, input_data, output_data, error_message, started_at, completed_at)
                         - decisions (id, run_id, step_name, reasoning, next_action, timestamp)
```

1. **Connects to SQLite** — Reads run, step, and decision records
2. **Formats Data** — Converts raw DB rows to readable JSON
3. **Serves Dashboard** — Flask app serves HTML + live API endpoints
4. **Auto-Refresh** — JavaScript polls every 1 second for updates

## API Endpoints

```bash
# Get all runs
curl http://localhost:5000/api/runs

# Get specific run
curl http://localhost:5000/api/run/demo-fail

# Get most recent run
curl http://localhost:5000/api/current

# Database statistics (debug)
curl http://localhost:5000/api/debug
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Port 5000 already in use | Edit `server.py`: change `port=5000` to another port |
| Blank "Loading..." screen | Run the agent at least once (`python main.py --run-id test-001`) so `agent_state.db` exists |
| No data showing | Check browser console (F12), verify Flask is running, confirm DB file exists |
| ModuleNotFoundError: flask | `pip install -r debug_visualizer/requirements.txt` |

## What Was Fixed (Known Issues Resolved)

The initial visualizer showed "Loading..." forever because it used wrong column names. All issues are now resolved:

- ❌ Used `created_at` → ✅ Changed to `started_at` for steps table
- ❌ Used `error` → ✅ Changed to `error_message` (actual column name)
- ❌ Used `updated_at` → ✅ Changed to `completed_at` for steps table
- ✅ All SQL queries now use correct schema
- ✅ JSON parsing works for input/output data
- ✅ Dashboard shows real data in real-time
- ✅ **N+1 query elimination**: `api_runs`/`get_run_data` now use batched single-query fetches instead of per-run query loops
- ✅ **Concurrency safety**: `timeout=10.0` on DB connections prevents lock collisions with the agent writer

## Files

```
debug_visualizer/
├── server.py              # Flask server with embedded HTML dashboard (FIXED)
├── __init__.py            # Python package marker
├── requirements.txt       # Dependencies: Flask==2.3.0, Werkzeug==2.3.0
├── run.bat                # Windows batch launcher
├── run.ps1                # PowerShell launcher
└── README.md              # This file
```

---

**Pro Tip**: Open the visualizer and agent side-by-side — terminal on left, browser on right — for real-time debugging.
