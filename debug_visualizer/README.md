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

### 1. Install Dependencies
```bash
pip install -r debug_visualizer/requirements.txt
```

### 2. Start the Visualizer
```bash
python debug_visualizer/server.py
```

### 3. Open in Browser
Go to: **http://localhost:5000**

The dashboard will auto-refresh every second and show:
- Current run status
- All execution steps
- LLM decisions and reasoning
- Recent run history

### 4. Run Agent (in another terminal)
While the visualizer is running, start the agent:

```bash
python main.py --run-id demo-debug
```

You'll see the dashboard update in real-time as the agent executes!

## Dashboard Sections

### 📌 Sidebar - Recent Runs
- Shows last 20 runs
- Click any run to view its details
- Color-coded status indicators

### 🔍 Run Info
- Current status (COMPLETED, FAILED, PENDING)
- Steps completed count
- Run creation timestamp

### 📋 Execution Steps
Each step card shows:
- Step name and timestamp
- Status badge (color-coded)
- Output data (formatted JSON)
- Error details (if any)

**Step Status Colors**:
- 🟢 Green = COMPLETED
- 🔴 Red = FAILED
- 🟡 Yellow = PENDING

### 💭 LLM Decisions
Each decision card shows:
- Iteration number
- Action chosen by LLM
- Reasoning/explanation
- Timestamp

## Example Workflow

1. **Terminal 1 - Start Visualizer**:
```bash
python debug_visualizer/server.py
```

2. **Terminal 2 - Run Agent with Failure Injection**:
```bash
python main.py --run-id demo-fail --fail-at cache_update
```

3. **Browser - Watch in Real-time**:
Open http://localhost:5000 and watch:
- Step 1 (fetch_location) → COMPLETED ✓
- Step 2 (validate_consistency) → COMPLETED ✓
- Step 3 (write_db_correction) → COMPLETED ✓
- Step 4 (update_cache) → FAILED ✗

4. **Terminal 2 - Retry Same Run**:
```bash
python main.py --run-id demo-fail --fail-at cache_update
```

5. **Browser - See Recovery**:
- Steps 1-3 → SKIPPED (using cached results)
- Step 4 → FAILED again (still injecting failure)

6. **Terminal 2 - Remove Failure Injection**:
```bash
python main.py --run-id demo-fail
```

7. **Browser - See Completion**:
- Steps 1-3 → SKIPPED
- Step 4 (update_cache) → COMPLETED ✓
- Overall Status → COMPLETED ✓

This demonstrates **idempotent execution and intelligent failure recovery**!

## How It Works

The visualizer reads from the SQLite checkpoint database (`agent_state.db`) that the agent maintains:

1. **Connects to SQLite** - Reads run, step, and decision records
2. **Formats Data** - Converts raw DB rows to readable JSON
3. **Serves Dashboard** - Flask app serves HTML + live API endpoints
4. **Auto-Refresh** - JavaScript polls every 1 second for updates

## API Endpoints

If you want to integrate this with other tools:

```bash
# Get all runs
curl http://localhost:5000/api/runs

# Get specific run
curl http://localhost:5000/api/run/demo-fail

# Get most recent run
curl http://localhost:5000/api/current
```

## Troubleshooting

### Port Already in Use
If port 5000 is busy, modify `server.py`:
```python
app.run(debug=False, host="localhost", port=5001)  # Change to 5001
```

### Database Not Found
Make sure `agent_state.db` exists in the project root. Run the agent at least once to create it.

### Blank Dashboard
- Check if agent has run yet (look for db file)
- Check browser console for errors (F12)
- Make sure Flask is running (check terminal output)

## Files

- `server.py` - Flask server with embedded HTML dashboard
- `requirements.txt` - Python dependencies (just Flask)
- `README.md` - This file

---

**Pro Tip**: Have the visualizer and agent running side-by-side for the ultimate debugging experience! 🚀
