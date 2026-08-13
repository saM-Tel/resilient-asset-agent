import requests
import time
import subprocess
import sys
from pathlib import Path

# Start the visualizer in background
proc = subprocess.Popen([sys.executable, "debug_visualizer/server.py"], 
                       cwd="F:\\coding_projects\\resilient-asset-agent",
                       stdout=subprocess.PIPE, 
                       stderr=subprocess.PIPE)

# Give it time to start
time.sleep(3)

try:
    # Test the API
    resp = requests.get("http://localhost:5000/api/debug", timeout=5)
    print("✓ Database API Response:")
    print(resp.json())
    
    resp = requests.get("http://localhost:5000/api/current", timeout=5)
    data = resp.json()
    print(f"\n✓ Current Run: {data.get('run_id')}")
    print(f"  Status: {data.get('run_info', {}).get('status')}")
    print(f"  Steps: {len(data.get('steps', []))}")
    print(f"  Decisions: {len(data.get('decisions', []))}")
    
except Exception as e:
    print(f"✗ Error: {e}")
finally:
    proc.terminate()
    proc.wait()
    print("\n✓ Server stopped")
