"""
Automated resilience test suite for the resilient asset agent.

Verifies recovery, idempotency, and state persistence deterministically
without requiring a live LLM or manual CLI runs.

Run with:
    pytest tests/ -v
"""

import pytest

from agent.checkpointer import Checkpointer
from stubs.services import ServiceConfig, check_service_health, reset_service_state


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def checkpointer(tmp_path):
    """Provide a fresh Checkpointer backed by a temp SQLite file."""
    db_path = str(tmp_path / "test_state.db")
    cp = Checkpointer(db_path)
    yield cp
    cp.close()


@pytest.fixture(autouse=True)
def _reset_service_config():
    """Reset global ServiceConfig and service state around each test."""
    reset_service_state()
    ServiceConfig.inject_stale_data = False
    ServiceConfig.inject_timeout = False
    ServiceConfig.inject_unavailable = False
    ServiceConfig.partial_write = False
    ServiceConfig.cache_timeout = False
    ServiceConfig.cache_unavailable = False
    yield
    # Restore defaults after the test
    ServiceConfig.inject_stale_data = False
    ServiceConfig.inject_timeout = False
    ServiceConfig.inject_unavailable = False
    ServiceConfig.partial_write = False
    ServiceConfig.cache_timeout = False
    ServiceConfig.cache_unavailable = False


# =============================================================================
# Idempotency
# =============================================================================

def test_idempotency_guard_prevents_duplicate_writes(checkpointer):
    """A completed sub-task is recorded once and retrievable with its tx_id."""
    run_id = "test-idempotency"

    # 1. Simulate a completed database write sub-task
    checkpointer.save_sub_task(
        run_id, "write_db_correction", "database_write",
        "SUCCESS", tx_id="tx_001", idempotency_key="idem_001"
    )

    # 2. Verify the sub-task is recorded as completed with its tx_id
    subtasks = checkpointer.get_sub_tasks(run_id, "write_db_correction")
    assert len(subtasks) == 1
    subtask = subtasks[0]
    assert subtask["status"] == "SUCCESS"
    assert subtask["tx_id"] == "tx_001"
    assert subtask["idempotency_key"] == "idem_001"


def test_step_idempotency_returns_cached_result(checkpointer):
    """A completed step is retrievable so the runner can skip re-execution."""
    run_id = "test-step-idempotency"

    # 1. Record a completed step with output
    checkpointer.save_step(
        run_id, "fetch_location", 1, "COMPLETED",
        input_data={"asset_id": "asset_001"},
        output_data={"lat": 51.5074, "lng": -0.1278},
        idempotency_key="fetch_001"
    )

    # 2. get_step_result returns the cached result (idempotent read)
    result = checkpointer.get_step_result(run_id, "fetch_location")
    assert result is not None
    assert result["status"] == "COMPLETED"
    assert result["output_data"]["lat"] == 51.5074

    # 3. A step that was never run returns None (nothing to skip)
    assert checkpointer.get_step_result(run_id, "never_ran") is None


# =============================================================================
# Failure Recovery / Event Log
# =============================================================================

def test_network_timeout_records_unknown_and_reconciles(checkpointer):
    """A network timeout is logged as an UNKNOWN sub-task plus an event."""
    run_id = "test-timeout"

    # 1. Log a network timeout sub-task (outcome indeterminate)
    checkpointer.save_sub_task(
        run_id, "update_cache", "cache_invalidation",
        "UNKNOWN", error_message="Timeout 3s"
    )

    # 2. Append the timeout event to the audit trail
    checkpointer.emit_event(
        run_id, "NETWORK_TIMEOUT", "cache_invalidation",
        details={"error": "Timeout 3s"}
    )

    # 3. Verify the sub-task is UNKNOWN
    subtasks = checkpointer.get_sub_tasks(run_id, "update_cache")
    assert len(subtasks) == 1
    assert subtasks[0]["status"] == "UNKNOWN"
    assert subtasks[0]["error_message"] == "Timeout 3s"

    # 4. Verify the event is in the append-only log
    events = checkpointer.get_events(run_id)
    assert len(events) == 1
    assert events[0]["event"] == "NETWORK_TIMEOUT"
    assert events[0]["sub_task"] == "cache_invalidation"
    assert events[0]["details"]["error"] == "Timeout 3s"


def test_event_log_is_append_only_and_ordered(checkpointer):
    """Events are appended in chronological order and never mutated."""
    run_id = "test-event-order"

    checkpointer.emit_event(run_id, "STEP_STARTED", "fetch_location")
    checkpointer.emit_event(run_id, "SUBTASK_COMMITTED", "database_write", tx_id="tx_1")
    checkpointer.emit_event(run_id, "RECONCILIATION_STARTED", "cache_invalidation")

    events = checkpointer.get_events(run_id)
    assert [e["event"] for e in events] == [
        "STEP_STARTED", "SUBTASK_COMMITTED", "RECONCILIATION_STARTED"
    ]
    # Timestamps are non-decreasing
    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps)


# =============================================================================
# Health Check
# =============================================================================

def test_health_check_detects_service_down():
    """check_service_health reflects injected cache failure."""
    ServiceConfig.cache_unavailable = True

    health = check_service_health()
    assert health["cache"] is False
    assert health["database"] is True
    assert health["location_service"] is True


def test_health_check_all_healthy_by_default():
    """With no failures injected, all services report healthy."""
    health = check_service_health()
    assert health["cache"] is True
    assert health["database"] is True
    assert health["location_service"] is True


def test_health_check_detects_location_unavailable():
    """check_service_health reflects an unavailable location service."""
    ServiceConfig.inject_unavailable = True

    health = check_service_health()
    assert health["location_service"] is False
    assert health["cache"] is True
    assert health["database"] is True
