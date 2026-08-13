# Debug Visualizer - Quick Start Guide

## 🎯 What You Just Created

A **real-time web dashboard** that visualizes everything the agent is doing:
- 📊 Step execution with status (completed/failed/pending)
- 🧠 LLM decisions and reasoning
- 📝 Full execution trace
- 🔄 Run history
- 📈 Live updates every 1 second

## 🚀 Get Started in 30 Seconds

### Option 1: Use the Launcher (Easiest)

**On Windows PowerShell**:
```powershell
.\debug_visualizer\run.ps1
```

**Or in Command Prompt**:
```cmd
debug_visualizer\run.bat
```

This will:
1. ✓ Activate your venv
2. ✓ Install Flask
3. ✓ Start the dashboard on http://localhost:5000

### Option 2: Manual Start

```bash
# Activate venv
.\venv\Scripts\Activate.ps1

# Install Flask
pip install Flask==2.3.0 Werkzeug==2.3.0

# Start visualizer
python debug_visualizer/server.py
```

## 📺 View the Dashboard

Open your browser:
```
http://localhost:5000
```

You'll see:
- **Sidebar**: List of recent runs
- **Header**: Current run status
- **Steps Section**: Each execution step with status & output
- **Decisions Section**: What the LLM decided at each step

## 🔥 Try the Full Demo

### Terminal 1: Start Visualizer
```bash
python debug_visualizer/server.py
```

### Terminal 2: Run Agent (Watch in Browser!)
```bash
# First run - inject cache failure
python main.py --run-id demo-visual --fail-at cache_update
```

**Watch the dashboard**: You'll see steps complete one by one, then fail at cache_update.

```bash
# Second run - retry with same run-id
python main.py --run-id demo-visual --fail-at cache_update
```

**Watch the dashboard**: Now it SKIPS the first 3 steps and only retries step 4 (showing idempotency!).

```bash
# Third run - remove failure injection
python main.py --run-id demo-visual
```

**Watch the dashboard**: Step 4 finally completes, workflow is done!

## 🎨 Dashboard Features

### Step Status Colors
- 🟢 **Green** - Completed successfully
- 🔴 **Red** - Failed
- 🟡 **Yellow** - Pending/In progress

### Each Step Shows
- Step name (fetch_location, validate_consistency, etc.)
- Timestamp (when it executed)
- Status badge
- Full output (JSON formatted)
- Error details (if any)

### LLM Decisions Show
- Iteration number
- Action chosen (which tool to run)
- Timestamp
- Reasoning (why the LLM chose this)

## 💡 Pro Tips

1. **Side-by-Side Windows**: Put browser on right, terminal on left for ultimate debugging
2. **Auto-Refresh**: Enabled by default, watch in real-time
3. **Manual Refresh**: Click "Refresh Now" button anytime
4. **Run History**: Click runs in sidebar to view their full details
5. **API Access**: Use `/api/current` endpoint in curl/Python for programmatic access

## 🔧 Troubleshooting

### "Port 5000 already in use"
Change port in `debug_visualizer/server.py` line 136:
```python
app.run(debug=False, host="localhost", port=5001)  # Change to 5001
```

### "ModuleNotFoundError: No module named 'flask'"
```bash
pip install Flask==2.3.0
```

### "Database file not found"
The visualizer reads from `agent_state.db`. Make sure you've run the agent at least once:
```bash
python main.py --run-id test-001
```

### Dashboard is blank
- Check that the agent has run (look for agent_state.db)
- Check browser console for errors (F12)
- Refresh page (Ctrl+R)

## 📁 Files Created

```
debug_visualizer/
├── server.py              # Main Flask app (all-in-one)
├── __init__.py            # Python package marker
├── requirements.txt       # Python dependencies (Flask)
├── run.bat                # Windows batch launcher
├── run.ps1                # PowerShell launcher
└── README.md              # Full documentation
```

## 🌳 Git Branches

Your working code is safe! Here's the structure:

```
main (original working code)
  └── feature/debug-visualizer (new visualizer branch)
```

To switch between them:
```bash
# Go back to original working code
git checkout main

# Go back to visualizer
git checkout feature/debug-visualizer
```

## 🎬 Recording a Demo Video

1. Open Terminal & Browser side-by-side
2. Start visualizer: `python debug_visualizer/server.py`
3. Open http://localhost:5000 in browser
4. Run the 3-step demo in another terminal (see above)
5. Record the screen showing:
   - Step 1-3 execute
   - Step 4 fails (cache timeout)
   - Step 2 run: Steps 1-3 SKIPPED, step 4 fails again
   - Step 3 run: Steps 1-3 SKIPPED, step 4 succeeds

This perfectly demonstrates **idempotent execution and intelligent failure recovery**!

---

**Questions?** Check `debug_visualizer/README.md` for full docs!
