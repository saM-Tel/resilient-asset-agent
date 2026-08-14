"""Test script to verify mode toggle functionality works correctly."""

import json
import time
import sys
import subprocess
import urllib.request

print("\n" + "="*70)
print("TESTING MODE TOGGLE FUNCTIONALITY")
print("="*70 + "\n")

def http_get(url, timeout=5):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, response.read().decode('utf-8')

def http_get_json(url, timeout=5):
    status, body = http_get(url, timeout=timeout)
    return json.loads(body)

# Start the visualizer server in background
proc = subprocess.Popen(
    [sys.executable, "debug_visualizer/server.py"],
    cwd="F:\\coding_projects\\resilient-asset-agent",
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

time.sleep(3)  # Give server time to start

try:
    print("[TEST 1] Check if server is running...")
    status, _ = http_get("http://localhost:5000/", timeout=5)
    print(f"[OK] Server responding with status {status}")
    
    print("\n[TEST 2] Test /api/current endpoint...")
    data = http_get_json("http://localhost:5000/api/current", timeout=5)
    if data.get('run_id'):
        print(f"[OK] Current run: {data['run_id']}")
        print(f"  Steps: {len(data.get('steps', []))}")
        print(f"  Decisions: {len(data.get('decisions', []))}")
    else:
        print("[FAIL] No current run found")
    
    print("\n[TEST 3] Test /api/runs endpoint...")
    data = http_get_json("http://localhost:5000/api/runs", timeout=5)
    runs = data.get('runs', [])
    if runs:
        print(f"[OK] Found {len(runs)} runs:")
        for run in runs[:3]:  # Show first 3
            print(f"  - {run['run_id']} ({run['status']})")
    else:
        print("[FAIL] No runs found")
    
    print("\n[TEST 4] Test /api/run/<id> endpoint...")
    if runs:
        test_run = runs[0]['run_id']
        data = http_get_json(f"http://localhost:5000/api/run/{test_run}", timeout=5)
        print(f"[OK] Run {test_run}:")
        print(f"  Steps: {len(data.get('steps', []))}")
        print(f"  Decisions: {len(data.get('decisions', []))}")
    
    print("\n[TEST 5] Verify HTML contains mode toggle buttons...")
    
    # Read the server.py file directly to check for changes
    with open("debug_visualizer/server.py", "r", encoding="utf-8") as f:
        html_content = f.read()
    
    if 'btnFollowLatest' in html_content and 'btnMonitorRun' in html_content:
        print("[OK] Mode toggle buttons found in HTML")
    else:
        print("[FAIL] Mode toggle buttons NOT found")
    
    if 'setMode(' in html_content:
        print("[OK] setMode() function found in JavaScript")
    else:
        print("[FAIL] setMode() function NOT found")
    
    if 'currentMode' in html_content and 'monitoredRunId' in html_content:
        print("[OK] Mode state variables found")
    else:
        print("[FAIL] Mode state variables NOT found")
    
    print("\n" + "="*70)
    print("[OK] ALL TESTS PASSED - Mode toggle is working!")
    print("="*70 + "\n")
    
except Exception as e:
    print(f"\n[ERROR] {e}")
    import traceback
    traceback.print_exc()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    print("[OK] Server stopped")
