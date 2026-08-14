"""
Main entry point for the Resilient Asset Agent.

This script runs the asset synchronization agent with configurable failure injection.
It demonstrates intelligent recovery from partial failures in a distributed system.

Usage:
    # Normal run (no failures)
    python main.py --run-id test-001
    
    # Simulate cache timeout after DB write succeeds
    python main.py --run-id test-002 --fail-at cache_update
    
    # Simulate stale location data
    python main.py --run-id test-003 --inject-stale

The agent will:
1. Execute multi-step workflow (fetch → validate → write_db → update_cache)
2. Handle failures intelligently without re-doing completed work
3. Maintain checkpoint state for recovery across runs
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from openai import OpenAI
from stubs.services import ServiceConfig
from agent.checkpointer import Checkpointer
from agent.runner import AssetSyncAgent


def create_client(base_url: str = "http://localhost:8000/v1") -> OpenAI:
    """Create OpenAI-compatible client for local model server."""
    return OpenAI(
        base_url=base_url,
        api_key="not-needed"  # llama-server doesn't require a real key
    )


def configure_failure_injection(args: argparse.Namespace) -> None:
    """Configure failure injection based on command-line arguments."""
    
    if args.fail_at == "cache_update":
        ServiceConfig.cache_timeout = True
        print("[WARN] FAILURE INJECTION: Cache service will timeout")
    
    elif args.fail_at == "location_service":
        ServiceConfig.inject_timeout = True
        print("[WARN] FAILURE INJECTION: Location service will timeout")
    
    if args.inject_stale:
        ServiceConfig.inject_stale_data = True
        print("[WARN] FAILURE INJECTION: Location service will return stale data")
    
    if args.partial_write:
        ServiceConfig.partial_write = True
        print("[WARN] FAILURE INJECTION: Database will perform partial write")


def print_audit_trail(checkpointer: Checkpointer, run_id: str) -> None:
    """
    Print the append-only event log (mission log) for a run (Upgrade 2).
    
    Renders the audit trail as a chronological stream of JSON events,
    mirroring the format used by distributed orchestration systems.
    """
    events = checkpointer.get_events(run_id)
    if not events:
        return
    
    print(f"\n{'='*60}")
    print("  Audit Trail (Append-Only Event Log)")
    print(f"{'='*60}")
    
    for ev in events:
        ts = datetime.fromtimestamp(ev["timestamp"]).strftime("%Y-%m-%dT%H:%M:%SZ")
        record = {
            "timestamp": ts,
            "run_id": run_id,
            "event": ev["event"],
        }
        if ev.get("sub_task"):
            record["subtask"] = ev["sub_task"]
        if ev.get("tx_id"):
            record["tx_id"] = ev["tx_id"]
        if ev.get("details"):
            record.update(ev["details"])
        print(json.dumps(record))
    
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Resilient Asset Agent - Multi-step workflow with failure recovery"
    )
    
    # Required arguments
    parser.add_argument(
        "--run-id", 
        type=str, 
        default=f"run-{__import__('time').strftime('%Y%m%d-%H%M%S')}",
        help="Unique identifier for this execution run"
    )
    
    # Failure injection flags
    parser.add_argument(
        "--fail-at",
        type=str,
        choices=["cache_update", "location_service"],
        default=None,
        help="Inject failure at specific step (simulates real-world failures)"
    )
    parser.add_argument(
        "--inject-stale",
        action="store_true",
        help="Simulate stale data from location service"
    )
    parser.add_argument(
        "--partial-write",
        action="store_true",
        help="Simulate partial database write"
    )
    
    # Connection settings
    parser.add_argument(
        "--llm-url",
        type=str,
        default="http://localhost:8000/v1",
        help="URL of the local LLM server (OpenAI-compatible API)"
    )
    
    args = parser.parse_args()
    
    # Configure failure injection
    configure_failure_injection(args)
    
    print(f"\n{'='*60}")
    print("  Resilient Asset Agent")
    print(f"  Run ID: {args.run_id}")
    print(f"  LLM Server: {args.llm_url}")
    print(f"{'='*60}\n")
    
    # Initialize components
    try:
        client = create_client(args.llm_url)
    except Exception as e:
        print(f"❌ Failed to connect to LLM server at {args.llm_url}: {e}")
        print("   Make sure llama-server.exe is running on port 8000")
        sys.exit(1)
    
    checkpointer = Checkpointer(db_path="agent_state.db")
    
    try:
        # Create and run the agent
        agent = AssetSyncAgent(client, checkpointer, args.run_id)
        result = agent.run()
        
        # Print summary
        print(f"\n{'='*60}")
        print("  Execution Summary")
        print(f"{'='*60}")
        print(f"  Status: {result['status']}")
        print(f"  Iterations: {result['iterations']}")
        print(f"  Summary: {result['summary']}")
        print(f"{'='*60}\n")
        
        # Print the append-only audit trail (Upgrade 2)
        print_audit_trail(checkpointer, args.run_id)
        
    finally:
        checkpointer.close()


if __name__ == "__main__":
    main()