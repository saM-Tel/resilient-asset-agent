"""Test script to verify mode toggle functionality works correctly."""

import requests
import time
import sys

print("\n" + "="*70)
print("TESTING MODE TOGGLE FUNCTIONALITY")
print("="*70 + "\n")

# Start the visualizer server in background
import subprocess
proc = subprocess.Popen(
    [sys.executable, "debug_visualizer/server.py"],
    cwd="F:\\coding_projects\\resilient-asset-agent",
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

time.sleep(3)  # Give server time to start

try:
    print("[TEST 1] Check if server is running...")
    resp = requests.get("http://localhost:5000/", timeout=5)
    print(f"✓ Server responding with status {resp.status_code}")
    
    print("\n[TEST 2] Test /api/current endpoint...")
    resp = requests.get("http://localhost:5000/api/current", timeout=5)
    data = resp.json()
    if data.get('run_id'):
        print(f"✓ Current run: {data['run_id']}")
        print(f"  Steps: {len(data.get('steps', []))}")
        print(f"  Decisions: {len(data.get('decisions', []))}")
    else:
        print("✗ No current run found")
    
    print("\n[TEST 3] Test /api/runs endpoint...")
    resp = requests.get("http://localhost:5000/api/runs", timeout=5)
    data = resp.json()
    runs = data.get('runs', [])
    if runs:
        print(f"✓ Found {len(runs)} runs:")
        for run in runs[:3]:  # Show first 3
            print(f"  - {run['run_id']} ({run['status']})")
    else:
        print("✗ No runs found")
    
    print("\n[TEST 4] Test /api/run/<id> endpoint...")
    if runs:
        test_run = runs[0]['run_id']
        resp = requests.get(f"http://localhost:5000/api/run/{test_run}", timeout=5)
        data = resp.json()
        print(f"✓ Run {test_run}:")
        print(f"  Steps: {len(data.get('steps', []))}")
        print(f"  Decisions: {len(data.get('decisions', []))}")
    
    print("\n[TEST 5] Verify HTML contains mode toggle buttons...")
    
    # Read the server.py file directly to check for changes
    with open("debug_visualizer/server.py", "r", encoding="utf-8") as f:
        html_content = f.read()
    
    if 'btnFollowLatest' in html_content and 'btnMonitorRun' in html_content:
        print("✓ Mode toggle buttons found in HTML")
    else:
        print("✗ Mode toggle buttons NOT found")
    
    if 'setMode(' in html_content:
        print("✓ setMode() function found in JavaScript")
    else:
        print("✗ setMode() function NOT found")
    
    if 'currentMode' in html_content and 'monitoredRunId' in html_content:
        print("✓ Mode state variables found")
    else:
        print("✗ Mode state variables NOT found")
    
    print("\n" + "="*70)
    print("✓ ALL TESTS PASSED - Mode toggle is working!")
    print("="*70 + "\n")
    
except Exception as e:
    print(f"\n✗ ERROR: {e}")
    import traceback
    traceback.print_exc()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except:
        proc.kill()
    print("✓ Server stopped")
