import json
import time
import subprocess
import sys
import urllib.request
from pathlib import Path

def http_get_json(url, timeout=5):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))

# Start the visualizer in background
proc = subprocess.Popen([sys.executable, "debug_visualizer/server.py"], 
                       cwd="F:\\coding_projects\\resilient-asset-agent",
                       stdout=subprocess.PIPE, 
                       stderr=subprocess.PIPE)

# Give it time to start
time.sleep(3)

try:
    # Test the API
    data = http_get_json("http://localhost:5000/api/debug", timeout=5)
    print("[OK] Database API Response:")
    print(data)
    
    data = http_get_json("http://localhost:5000/api/current", timeout=5)
    print(f"\n[OK] Current Run: {data.get('run_id')}")
    print(f"  Status: {data.get('run_info', {}).get('status')}")
    print(f"  Steps: {len(data.get('steps', []))}")
    print(f"  Decisions: {len(data.get('decisions', []))}")
    
except Exception as e:
    print(f"[ERROR] Error: {e}")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    print("\n[OK] Server stopped")
