"""
Real-time debug visualizer for Resilient Asset Agent.

This Flask server provides a simple web-based dashboard showing:
- Current run status
- Step execution history
- LLM decisions
- Service responses
- Checkpoint state

Usage:
    python debug_visualizer/server.py
    
Then open http://localhost:5000 in your browser
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)
DB_PATH = Path(__file__).parent.parent / "agent_state.db"


def get_db_connection():
    """Create a database connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_run_data(run_id: str = None) -> dict:
    """Get all data for a specific run or the most recent run."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get most recent run if not specified
        if not run_id:
            cursor.execute("SELECT DISTINCT run_id FROM steps ORDER BY started_at DESC LIMIT 1")
            result = cursor.fetchone()
            run_id = result[0] if result else None
        
        if not run_id:
            return {
                "error": "No runs found",
                "debug": "Database is empty or no steps recorded",
                "run_id": None,
                "run_info": {},
                "steps": [],
                "decisions": [],
                "all_runs": []
            }
        
        # Get run info from runs table
        cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        run_row = cursor.fetchone()
        run_info = dict(run_row) if run_row else {"run_id": run_id, "status": "UNKNOWN", "created_at": None}
        
        # Get steps
        cursor.execute(
            "SELECT id, run_id, step_name, step_order, status, input_data, output_data, error_message, started_at, completed_at FROM steps WHERE run_id = ? ORDER BY id ASC",
            (run_id,)
        )
        steps = []
        for row in cursor.fetchall():
            step = {
                "id": row[0],
                "run_id": row[1],
                "step_name": row[2],
                "step_order": row[3],
                "status": row[4],
                "input_data": row[5],
                "output_data": row[6],
                "error": row[7],
                "created_at": row[8],
                "updated_at": row[9]
            }
            
            # Parse JSON fields
            for key in ["input_data", "output_data"]:
                if step.get(key):
                    try:
                        step[key] = json.loads(step[key])
                    except:
                        pass
            
            steps.append(step)
        
        # Get decisions
        cursor.execute(
            "SELECT * FROM decisions WHERE run_id = ? ORDER BY id ASC",
            (run_id,)
        )
        decisions = []
        for row in cursor.fetchall():
            decision = {
                "id": row[0],
                "run_id": row[1],
                "step_name": row[2],
                "reasoning": row[3],
                "next_action": row[4],
                "timestamp": row[5]
            }
            decisions.append(decision)
        
        # Get all runs for sidebar
        cursor.execute("SELECT DISTINCT run_id FROM steps ORDER BY started_at DESC LIMIT 20")
        all_runs = []
        for row in cursor.fetchall():
            run_id_item = row[0]
            cursor.execute("SELECT status FROM runs WHERE run_id = ? LIMIT 1", (run_id_item,))
            status_row = cursor.fetchone()
            status = status_row[0] if status_row else "UNKNOWN"
            
            cursor.execute("SELECT MAX(started_at) FROM steps WHERE run_id = ?", (run_id_item,))
            created_row = cursor.fetchone()
            created_at = created_row[0] if created_row else None
            
            all_runs.append({
                "run_id": run_id_item,
                "status": status,
                "created_at": created_at
            })
        
        return {
            "run_id": run_id,
            "run_info": run_info,
            "steps": steps,
            "decisions": decisions,
            "all_runs": all_runs,
            "debug": f"Loaded {len(steps)} steps and {len(decisions)} decisions"
        }
    
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "debug": traceback.format_exc(),
            "run_id": run_id,
            "run_info": {},
            "steps": [],
            "decisions": [],
            "all_runs": []
        }
    
    finally:
        conn.close()


@app.route("/api/debug")
def api_debug():
    """Get debug information about database state."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get database statistics
        cursor.execute("SELECT COUNT(*) FROM runs")
        total_runs = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM steps")
        total_steps = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM decisions")
        total_decisions = cursor.fetchone()[0]
        
        # Get recent runs with counts
        cursor.execute("""
            SELECT run_id, status, 
                   (SELECT COUNT(*) FROM steps WHERE run_id = runs.run_id) as step_count,
                   (SELECT COUNT(*) FROM decisions WHERE run_id = runs.run_id) as decision_count
            FROM runs 
            ORDER BY created_at DESC 
            LIMIT 10
        """)
        recent_runs = [dict(zip(['run_id', 'status', 'step_count', 'decision_count'], row)) 
                      for row in cursor.fetchall()]
        
        return jsonify({
            "status": "ok",
            "total_runs": total_runs,
            "total_steps": total_steps,
            "total_decisions": total_decisions,
            "recent_runs": recent_runs,
            "db_path": str(DB_PATH)
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})
    finally:
        conn.close()


@app.route("/")
def dashboard():
    """Serve the main dashboard."""
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/runs")
def api_runs():
    """Get list of all runs."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT DISTINCT run_id FROM steps ORDER BY started_at DESC LIMIT 20")
        runs = []
        for row in cursor.fetchall():
            run_id = row[0]
            cursor.execute("SELECT status FROM runs WHERE run_id = ? LIMIT 1", (run_id,))
            status_row = cursor.fetchone()
            status = status_row[0] if status_row else "UNKNOWN"
            
            cursor.execute("SELECT MAX(started_at) FROM steps WHERE run_id = ?", (run_id,))
            created_row = cursor.fetchone()
            created_at = created_row[0] if created_row else None
            
            runs.append({"run_id": run_id, "status": status, "created_at": created_at})
        
        return jsonify({"runs": runs})
    except Exception as e:
        return jsonify({"runs": [], "error": str(e)})
    finally:
        conn.close()


@app.route("/api/run/<run_id>")
def api_run(run_id):
    """Get detailed data for a specific run."""
    data = get_run_data(run_id)
    return jsonify(data)


@app.route("/api/current")
def api_current():
    """Get data for the most recent run (auto-refresh)."""
    data = get_run_data()
    return jsonify(data)


# HTML template for the dashboard
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Asset Agent Debug Visualizer</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
        }
        
        .container {
            display: flex;
            height: 100vh;
        }
        
        .sidebar {
            width: 250px;
            background: #161b22;
            border-right: 1px solid #30363d;
            padding: 20px;
            overflow-y: auto;
        }
        
        .sidebar h3 {
            color: #58a6ff;
            margin-bottom: 15px;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .run-list {
            list-style: none;
        }
        
        .run-item {
            padding: 10px;
            margin-bottom: 8px;
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            transition: all 0.2s;
        }
        
        .run-item:hover {
            background: #1c2128;
            border-color: #58a6ff;
        }
        
        .run-item.active {
            background: #1f6feb;
            border-color: #58a6ff;
            color: white;
        }
        
        .run-status {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 6px;
            vertical-align: middle;
        }
        
        .status-completed { background: #3fb950; }
        .status-failed { background: #f85149; }
        .status-pending { background: #d29922; }
        .status-unknown { background: #6e40aa; }
        
        .main {
            flex: 1;
            overflow-y: auto;
            padding: 30px;
        }
        
        .header {
            margin-bottom: 30px;
            border-bottom: 2px solid #30363d;
            padding-bottom: 20px;
        }
        
        .header h1 {
            color: #58a6ff;
            font-size: 28px;
            margin-bottom: 10px;
        }
        
        .run-meta {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        
        .meta-item {
            background: #161b22;
            padding: 12px;
            border-radius: 6px;
            border-left: 3px solid #58a6ff;
        }
        
        .meta-label {
            font-size: 12px;
            color: #8b949e;
            text-transform: uppercase;
            margin-bottom: 5px;
        }
        
        .meta-value {
            font-size: 16px;
            color: #c9d1d9;
            font-weight: 500;
        }
        
        .section {
            margin-bottom: 40px;
        }
        
        .section h2 {
            color: #58a6ff;
            font-size: 18px;
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
            border-bottom: 1px solid #30363d;
            padding-bottom: 10px;
        }
        
        .step {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 15px;
            margin-bottom: 12px;
            border-left: 4px solid #6e40aa;
        }
        
        .step.completed {
            border-left-color: #3fb950;
            background: #0d3817;
        }
        
        .step.failed {
            border-left-color: #f85149;
            background: #3d0f0a;
        }
        
        .step.pending {
            border-left-color: #d29922;
            background: #3d2d0a;
        }
        
        .step-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        
        .step-name {
            font-size: 14px;
            font-weight: 600;
            color: #c9d1d9;
        }
        
        .step-status {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .step-status.completed {
            background: #238636;
            color: white;
        }
        
        .step-status.failed {
            background: #da3633;
            color: white;
        }
        
        .step-status.pending {
            background: #9e6a03;
            color: white;
        }
        
        .step-time {
            font-size: 11px;
            color: #8b949e;
        }
        
        .step-content {
            font-size: 12px;
            color: #8b949e;
            line-height: 1.6;
        }
        
        .step-output {
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 4px;
            padding: 10px;
            margin-top: 10px;
            font-family: 'Courier New', monospace;
            font-size: 11px;
            white-space: pre-wrap;
            word-wrap: break-word;
            max-height: 150px;
            overflow-y: auto;
        }
        
        .decision {
            background: #1f6feb;
            border-left: 4px solid #58a6ff;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 12px;
        }
        
        .decision-header {
            font-weight: 600;
            margin-bottom: 8px;
            color: white;
        }
        
        .decision-action {
            display: inline-block;
            background: #0d1117;
            color: #58a6ff;
            padding: 4px 12px;
            border-radius: 4px;
            font-family: monospace;
            font-size: 12px;
            margin-right: 10px;
        }
        
        .decision-reasoning {
            font-size: 12px;
            color: #e6edf3;
            margin-top: 8px;
        }
        
        .loading {
            text-align: center;
            color: #8b949e;
            padding: 40px;
        }
        
        .refresh-btn {
            background: #238636;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            transition: background 0.2s;
        }
        
        .refresh-btn:hover {
            background: #2ea043;
        }
        
        .auto-refresh {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 20px;
            padding: 10px;
            background: #161b22;
            border-radius: 6px;
            border: 1px solid #30363d;
        }
        
        .auto-refresh input[type="checkbox"] {
            cursor: pointer;
        }
        
        .auto-refresh label {
            font-size: 12px;
            cursor: pointer;
        }
        
        .mode-toggle {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-left: auto;
        }
        
        .mode-btn {
            background: #21262d;
            color: #8b949e;
            border: 1px solid #30363d;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 11px;
            font-weight: 500;
            transition: all 0.2s;
        }
        
        .mode-btn:hover {
            background: #30363d;
        }
        
        .mode-btn.active {
            background: #1f6feb;
            color: white;
            border-color: #58a6ff;
        }
        
        .mode-indicator {
            font-size: 10px;
            padding: 4px 8px;
            border-radius: 4px;
            background: #238636;
            color: white;
            display: none;
        }
        
        .mode-indicator.visible {
            display: inline-block;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Sidebar -->
        <div class="sidebar">
            <h3>Recent Runs</h3>
            <ul class="run-list" id="runList"></ul>
        </div>
        
        <!-- Main Dashboard -->
        <div class="main">
            <div class="header">
                <h1 id="pageTitle">Asset Agent Debug Visualizer</h1>
                <div id="runInfo"></div>
            </div>
            
            <div class="auto-refresh">
                <input type="checkbox" id="autoRefresh" checked>
                <label for="autoRefresh">Auto-refresh (1s)</label>
                <button class="refresh-btn" onclick="manualRefresh()">↻ Refresh</button>
                
                <div class="mode-toggle">
                    <span style="font-size: 11px; color: #8b949e;">Mode:</span>
                    <button class="mode-btn active" id="btnFollowLatest" onclick="setMode('latest')">[LATEST] Follow Latest</button>
                    <button class="mode-btn" id="btnMonitorRun" onclick="setMode('monitor')">[MONITOR] Monitor Run</button>
                </div>
                
                <span class="mode-indicator visible" id="modeIndicator">[FOLLOWING] Following latest run</span>
            </div>
            
            <!-- Steps Section -->
            <div class="section">
                <h2>Execution Steps</h2>
                <div id="stepsContainer" class="loading">Loading...</div>
            </div>
            
            <!-- Decisions Section -->
            <div class="section">
                <h2>LLM Decisions</h2>
                <div id="decisionsContainer" class="loading">Loading...</div>
            </div>
        </div>
    </div>
    
    <script>
        let autoRefreshInterval = null;
        let currentMode = 'latest'; // 'latest' or 'monitor'
        let monitoredRunId = null;
        
        function setMode(mode) {
            currentMode = mode;
            
            const btnLatest = document.getElementById('btnFollowLatest');
            const btnMonitor = document.getElementById('btnMonitorRun');
            const indicator = document.getElementById('modeIndicator');
            
            if (mode === 'latest') {
                btnLatest.classList.add('active');
                btnMonitor.classList.remove('active');
                indicator.textContent = '📡 Following latest run';
                indicator.style.background = '#238636';
                
                // If we were monitoring a specific run, switch to latest
                if (monitoredRunId) {
                    monitoredRunId = null;
                    loadCurrentRun();
                }
            } else {
                btnMonitor.classList.add('active');
                btnLatest.classList.remove('active');
                
                // If no run selected yet, use current
                if (!monitoredRunId || !currentRunId) {
                    monitoredRunId = currentRunId;
                }
                
                indicator.textContent = `👁️ Monitoring: ${monitoredRunId}`;
                indicator.style.background = '#1f6feb';
            }
            
            indicator.classList.add('visible');
        }
        
        async function loadRuns() {
            try {
                const response = await fetch('/api/runs');
                const data = await response.json();
                
                const runList = document.getElementById('runList');
                runList.innerHTML = '';
                
                data.runs.forEach(run => {
                    const item = document.createElement('li');
                    item.className = 'run-item';
                    
                    // Highlight active run based on mode
                    if (currentMode === 'latest' && run.run_id === currentRunId) {
                        item.classList.add('active');
                    } else if (currentMode === 'monitor' && run.run_id === monitoredRunId) {
                        item.classList.add('active');
                    }
                    
                    const statusClass = `status-${(run.status || 'unknown').toLowerCase()}`;
                    item.innerHTML = `
                        <span class="run-status ${statusClass}"></span>
                        <strong>${run.run_id.substring(0, 15)}</strong><br>
                        <small>${run.status}</small>
                    `;
                    item.onclick = () => {
                        if (currentMode === 'latest') {
                            // In latest mode, just view the run without switching modes
                            loadRun(run.run_id);
                        } else {
                            // In monitor mode, switch to monitoring this run
                            monitoredRunId = run.run_id;
                            setMode('monitor');
                            indicator.textContent = `👁️ Monitoring: ${monitoredRunId}`;
                        }
                    };
                    runList.appendChild(item);
                });
            } catch (error) {
                console.error('Error loading runs:', error);
            }
        }
        
        let currentRunId = null;
        
        async function loadRun(runId) {
            currentRunId = runId;
            
            try {
                const response = await fetch(`/api/run/${runId}`);
                const data = await response.json();
                
                if (data.error) {
                    document.getElementById('pageTitle').textContent = 'No data available';
                    return;
                }
                
                // Update header
                document.getElementById('pageTitle').textContent = `Run: ${data.run_id}`;
                
                const runMeta = data.run_info;
                const metaHtml = `
                    <div class="run-meta">
                        <div class="meta-item">
                            <div class="meta-label">Status</div>
                            <div class="meta-value">${runMeta.status || 'UNKNOWN'}</div>
                        </div>
                        <div class="meta-item">
                            <div class="meta-label">Steps Completed</div>
                            <div class="meta-value">${data.steps.filter(s => s.status === 'COMPLETED').length}/${data.steps.length}</div>
                        </div>
                        <div class="meta-item">
                            <div class="meta-label">Created</div>
                            <div class="meta-value">${new Date(runMeta.created_at).toLocaleTimeString()}</div>
                        </div>
                    </div>
                `;
                document.getElementById('runInfo').innerHTML = metaHtml;
                
                // Render steps
                const stepsContainer = document.getElementById('stepsContainer');
                if (data.steps.length === 0) {
                    stepsContainer.innerHTML = '<div class="loading">No steps recorded yet</div>';
                } else {
                    stepsContainer.innerHTML = data.steps.map(step => `
                        <div class="step ${(step.status || 'pending').toLowerCase()}">
                            <div class="step-header">
                                <div>
                                    <div class="step-name">${step.step_name}</div>
                                    <div class="step-time">${new Date(step.created_at).toLocaleTimeString()}</div>
                                </div>
                                <div class="step-status ${(step.status || 'pending').toLowerCase()}">
                                    ${step.status || 'PENDING'}
                                </div>
                            </div>
                            <div class="step-content">
                                ${step.error ? `<strong>Error:</strong> ${step.error}` : ''}
                                ${step.output_data ? `<strong>Output:</strong><br><pre>${JSON.stringify(step.output_data, null, 2)}</pre>` : ''}
                            </div>
                        </div>
                    `).join('');
                }
                
                // Render decisions
                const decisionsContainer = document.getElementById('decisionsContainer');
                if (data.decisions.length === 0) {
                    decisionsContainer.innerHTML = '<div class="loading">No decisions recorded yet</div>';
                } else {
                    decisionsContainer.innerHTML = data.decisions.map(decision => `
                        <div class="decision">
                            <div class="decision-header">Iteration ${decision.step_name.split('_').pop()}</div>
                            <div>
                                <span class="decision-action">${decision.next_action}</span>
                                <span class="step-time">${new Date(decision.created_at).toLocaleTimeString()}</span>
                            </div>
                            ${decision.reasoning ? `<div class="decision-reasoning"><strong>Reasoning:</strong> ${decision.reasoning}</div>` : ''}
                        </div>
                    `).join('');
                }
                
                loadRuns();
            } catch (error) {
                console.error('Error loading run:', error);
                document.getElementById('stepsContainer').innerHTML = `<div class="loading">Error: ${error}</div>`;
            }
        }
        
        async function loadCurrentRun() {
            try {
                const response = await fetch('/api/current');
                const data = await response.json();
                
                if (data.run_id) {
                    // Only auto-switch to latest run in 'latest' mode
                    if (currentMode === 'latest') {
                        loadRun(data.run_id);
                    } else {
                        // In monitor mode, just update the monitored run
                        if (monitoredRunId && data.run_id !== monitoredRunId) {
                            loadRun(monitoredRunId);
                        }
                    }
                }
            } catch (error) {
                console.error('Error loading current run:', error);
            }
        }
        
        async function manualRefresh() {
            if (currentMode === 'latest') {
                await loadCurrentRun();
            } else {
                await loadRun(monitoredRunId);
            }
        }
        
        // Initial load - start in latest mode
        loadCurrentRun();
        
        // Auto-refresh handler
        document.getElementById('autoRefresh').addEventListener('change', (e) => {
            if (e.target.checked) {
                if (!autoRefreshInterval) {
                    autoRefreshInterval = setInterval(() => {
                        if (currentMode === 'latest') {
                            loadCurrentRun();
                        } else {
                            // In monitor mode, refresh the monitored run
                            if (monitoredRunId) {
                                loadRun(monitoredRunId);
                            }
                        }
                    }, 1000);
                }
            } else {
                if (autoRefreshInterval) {
                    clearInterval(autoRefreshInterval);
                    autoRefreshInterval = null;
                }
            }
        });
        
        // Start auto-refresh in latest mode by default
        autoRefreshInterval = setInterval(loadCurrentRun, 1000);
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    print("\n" + "="*60)
    print("  Asset Agent Debug Visualizer")
    print("="*60)
    print("\n✓ Starting server on http://localhost:5000")
    print("✓ Open this URL in your browser to view the dashboard")
    print("✓ Auto-refreshes every 1 second\n")
    print("  Database path:", DB_PATH)
    print("  (Make sure agent_state.db exists in the project root)\n")
    print("="*60 + "\n")
    
    app.run(debug=False, host="localhost", port=5000)
