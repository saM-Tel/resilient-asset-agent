# Resilient Asset Agent — Architecture & Interconnections

> **Temporary reference** — not tracked by Git. Explains how every module, class, and function links together.

---

## 1. High-Level Flow

```
main.py ──creates──▶ OpenAI client (local LLM)
       │
       ├─▶ Checkpointer(db_path)          ← SQLite persistence layer
       │        │
       │        └─ set_checkpointer(cp)   ← registers cp globally in stubs/services.py
       │
       └─▶ AssetSyncAgent(client, cp, run_id)  ← the "brain"
                │
                ├─ get_execution_context()  reads from Checkpointer
                ├─ build_llm_prompt(ctx)    → LLM API call
                ├─ parse_llm_response(resp) → decision dict {action, reasoning, parameters}
                └─ execute_action(action, params)
                         │
                         ├─ tools.py wrappers (idempotent)
                         │        │
                         │        └─ stubs/services.py (mock distributed services)
                         │
                         └─ Checkpointer saves every outcome
```

**One execution run = one `run_id`.** Every step, decision, sub-task, and audit event is tagged with it.

---

## 2. File-by-File Breakdown

### `main.py` — Entry Point & CLI

| Function / Class | Purpose | Calls / Depends On |
|---|---|---|
| `create_client(base_url)` | Creates an `OpenAI` client pointing at a local llama-server (port 8000). | `openai.OpenAI` |
| `configure_failure_injection(args)` | Sets global knobs on `ServiceConfig` based on CLI flags (`--fail-at`, `--inject-stale`, `--partial-write`). `--fail-at llm_connection` is special: it does not touch `ServiceConfig` — the LLM outage is injected directly in the agent's LLM call (see `runner.py`). | `stubs.services.ServiceConfig` |
| `print_audit_trail(checkpointer, run_id)` | Renders the append-only event log as JSON lines. | `checkpointer.get_events(run_id)` |
| `main()` | Orchestrates everything: parses args → creates client → configures failures → instantiates Checkpointer & Agent → runs agent → prints summary + audit trail. | All modules |

**Startup sequence in `main()`:**
1. Parse CLI arguments (`argparse`)
2. Call `configure_failure_injection(args)` to set failure knobs
3. Create LLM client via `create_client()`
4. Instantiate `Checkpointer()` → creates SQLite DB at `data/agent_state.db`
5. Register checkpointer globally: `set_checkpointer(cp)` + `reset_service_state(cp)`
6. Create `AssetSyncAgent(client, cp, run_id)` and call `agent.run()`
7. Print summary + audit trail, then `checkpointer.close()`

---

### `agent/checkpointer.py` — SQLite Persistence Layer

| Class / Method | Purpose | Called By |
|---|---|---|
| `Checkpointer.__init__(db_path)` | Opens SQLite connection, enables WAL mode, creates all tables. | `main()`, tests |
| `_create_tables()` | Creates 5 tables: `runs`, `steps`, `decisions`, `sub_tasks`, `events`, plus `service_state`. Also runs a migration to add `idempotency_key` column if missing. | `__init__` |
| `clear_run(run_id)` | Deletes all steps, decisions, sub-tasks, events for a run; resets status to `IN_PROGRESS`. | Tests (re-run scenarios) |
| `create_run(run_id)` | Inserts a new row into `runs` table with status `IN_PROGRESS`. | `AssetSyncAgent.run()` |
| `complete_run(run_id)` | Sets run status to `COMPLETED` and records `completed_at`. | Agent on success / halt |
| `fail_run(run_id, error)` | Sets run status to `FAILED`, attaches error message to last step. | Agent on unrecoverable failure |
| `halt_run(run_id, reason, down_services)` | Sets run status to `HALTED` when services are DOWN — distinct from COMPLETED (all done) or FAILED (unrecoverable). Emits `WORKFLOW_HALTED` audit event with the list of down services. | Agent's health check loop in `run()` |
| `get_run_status(run_id)` | Returns dict with run status, created/completed timestamps. | Agent's `get_execution_context()` |
| `save_step(...)` | Persists a step execution (input, output, status, idempotency key). Returns row ID. | All tool wrappers + agent |
| `promote_step(run_id, step_name, output_data)` | Promotes an existing `PARTIAL_FAILURE` row to `COMPLETED` in place after probe verification. | `runner.execute_action("verify_db_transaction")` |
| `get_completed_steps(run_id)` | Returns list of completed steps ordered by `step_order`. | Agent's `get_execution_context()`, tools |
| `get_failed_steps(run_id)` | Returns failed steps **excluding** those later retried successfully. | Agent's `get_execution_context()` |
| `get_partial_steps(run_id)` | Returns steps with status `PARTIAL_FAILURE` (write committed but response incomplete). | Agent's `get_execution_context()` |
| `get_step_result(run_id, step_name)` | Returns the latest result for a specific step by name (used by tool wrappers for idempotency checks). | Tool wrappers (`execute_fetch_location`, etc.) |
| `save_sub_task(...)` | Records a granular sub-task outcome (`SUCCESS`, `FAILED`, `UNKNOWN`). | Tool wrappers for write_db / update_cache |
| `get_sub_tasks(run_id, step_name)` | Retrieves all sub-tasks for a given step. | — |
| `emit_event(...)` | Appends an immutable audit event (STEP_STARTED, SUBTASK_COMMITTED, NETWORK_TIMEOUT, etc.). | Tool wrappers |
| `get_events(run_id)` | Returns all audit events for a run (used by `print_audit_trail`). | `main.py`'s `print_audit_trail()` |
| `get_execution_trace(run_id)` | Returns the full ordered history of steps + decisions for LLM context. | Agent's `get_execution_context()` |
| `set_service_state(key, value)` / `get_service_state(key)` | CRUD on the `service_state` table — replaces in-memory `_DEFAULT_STATE`. | `stubs/services.py` via `_save_state()` / `_load_state()` |
| `close()` | Closes SQLite connection. | `main()` finally block |

**Tables at a glance:**

| Table | Purpose |
|---|---|
| `runs` | One row per execution run; tracks overall status (`IN_PROGRESS`, `COMPLETED`, `HALTED`, `FAILED`) — `HALTED` distinguishes intentional pauses from successful completion or unrecoverable errors |
| `steps` | Each workflow step (fetch_location, validate_consistency, write_db_correction, update_cache) |
| `decisions` | LLM reasoning: what action was chosen and why |
| `sub_tasks` | Granular outcomes within a step (e.g., `database_write`, `cache_invalidation`) — supports UNKNOWN status for timeouts |
| `events` | Append-only audit trail / mission log |
| `service_state` | Durable mock service data + idempotency registry |

---

### `agent/runner.py` — The Agent "Brain"

| Class / Method | Purpose | Calls / Depends On |
|---|---|---|
| `AssetSyncAgent.__init__(client, checkpointer, run_id, fail_at=None)` | Initializes agent with LLM client, checkpoint store, run ID, and optional failure-injection knob. Sets `_force_health_check = False`, `_last_health_results = None`. `fail_at="llm_connection"` triggers a simulated LLM server outage on the first LLM call. | — |
| `_get_latest_step_output(completed_steps, step_name)` | Finds the most recent completed step by name and returns its `output_data`. | Used internally by `execute_action()` |
| `_get_correction_data(completed_steps)` | Extracts corrected coordinates from a `write_db_correction` step's `input_data.correction_data`. | Used by `execute_action("update_cache")` |
| `get_execution_context()` | Builds the full execution state: run status, completed/failed/partial steps, execution trace. | Called at top of every `run()` iteration |
| `build_llm_prompt(context)` | Constructs a system + user message pair for the LLM. Encodes failure-handling rules (health check on failure, halt on DOWN services, skip partial steps). Injects `_force_health_check` flag and previous health results when relevant. | Agent's `run()` loop → calls LLM API |
| `parse_llm_response(response_content, context)` | Extracts JSON from the LLM response. Handles markdown code blocks, embedded JSON objects, and multiple fallback strategies (context-aware defaults → absolute default of `fetch_location`). | Called after every LLM call in `run()` |
| `execute_action(action, parameters, reasoning)` | Dispatches to the correct tool wrapper based on the LLM's chosen action. Handles special actions (`DONE`, `halt`/`stop`) and data dependencies between steps. | Tool wrappers + `stubs.services.check_service_health` |
| `run()` | **The main control loop.** Iterates up to `max_iterations` (default 15): get context → build prompt → call LLM → parse response → execute action → save decision → check completion. Sets `_force_health_check = True` after any failure, forcing a health check on the next iteration. Returns final result dict. **LLM outage injection:** immediately before `client.chat.completions.create(...)`, if `self.fail_at == "llm_connection"` the agent prints a `[FAIL]` marker, emits an `LLM_SERVER_UNREACHABLE` audit event (subtask `reasoning_engine`), calls `fail_run()`, and returns `"status": "FAILED"` — simulating a connection refusal to the local LLM server without touching any workflow step. | Everything — orchestrates one full agent execution |

**The `run()` loop logic:**
```
for each iteration:
    context = get_execution_context()          # read from SQLite
    prompt  = build_llm_prompt(context)        # construct messages
    resp    = client.chat.completions.create(prompt)  # LLM call
    decision= parse_llm_response(resp, context)       # extract JSON action
    success, result = execute_action(decision.action, ...)  # run tool
    checkpointer.save_decision(...)             # log reasoning
    if not success:
        _force_health_check = True              # force health check next iter
    if done or halt: break
```

**`execute_action()` dispatch table:**

| Action | What it does | Dependencies |
|---|---|---|
| `DONE` | Returns immediately — all steps complete. | — |
| `fetch_location` | Calls `tools.execute_fetch_location(cp, run_id, asset_id)`. | None (first step) |
| `validate_consistency` | Reads latest `fetch_location` output → calls `tools.execute_validate_consistency()`. | Requires fetch_location completed |
| `write_db_correction` | Reads location + validation data. If already synced, marks COMPLETED without calling service. Otherwise builds correction from discrepancies and calls `tools.execute_write_db()`. | Requires fetch_location + validate_consistency |
| `update_cache` | Reads latest location data (prefers corrected coords if write_db_correction ran). Calls `tools.execute_update_cache()`. | Requires fetch_location |
| `verify_db_transaction` | Actively probes whether a partial DB transaction committed; on success promotes `write_db_correction` to `COMPLETED`. | `stubs.services.verify_db_transaction()`, `checkpointer.promote_step()` |
| `check_system_health` | Calls `stubs.services.check_service_health()` → stores results in `_last_health_results` for next iteration. | None |
| `halt` / `stop` | Marks run as completed (intelligent halt), prints reasoning. | — |

**Halt path in `run()` loop:** When health check detects DOWN services, the agent calls `self.checkpointer.halt_run(run_id=self.run_id, reason="service_unavailable", down_services=down_services)` and returns `"status": "HALTED"` instead of `"COMPLETED"`. The same applies when the LLM itself chooses the `halt` action: `execute_action("halt")` calls `halt_run()` (deriving `down_services` from `_last_health_results`) and the loop returns `"status": "HALTED"` — so LLM-driven halts are recorded as `HALTED`, never overwritten by the max-iterations `FAILED` path.

---

### `agent/tools.py` — Idempotent Tool Wrappers

Each wrapper follows the same pattern: **check checkpoint → skip if done → execute service → save result**.

| Function | Purpose | Service Called | Special Behavior |
|---|---|---|---|
| `ToolResult(success, data, error)` | Simple result container with `.to_dict()` method. | — | Used by all wrappers |
| `execute_fetch_location(cp, run_id, asset_id)` | Fetches asset location with idempotency guard. Skips if step already COMPLETED. | `stubs.services.fetch_asset_location()` | Saves to checkpoint; logs [SKIP]/[EXECUTE]/[OK]/[FAIL] |
| `execute_validate_consistency(cp, run_id, asset_data)` | Validates data consistency with idempotency guard. | `stubs.services.validate_consistency()` | Compares fetched coords against expected state |
| `execute_write_db(cp, run_id, correction_data)` | Writes corrections to DB with sub-task tracking + idempotency keys. Handles partial responses and timeouts as `PARTIAL_FAILURE` (UNKNOWN). **Active Read Verification Probe** (Refinement 2): On PARTIAL_FAILURE recovery, calls `verify_db_transaction(tx_id)` to confirm the write actually committed before skipping — emits `[PROBE]` marker and `VERIFICATION_PROBE_SUCCESS` event. | `stubs.services.write_db_correction()` | Generates idempotency key `{run_id}:write_db_correction:database_write`; emits audit events; distinguishes SUCCESS/FAILED/UNKNOWN sub-task outcomes |
| `execute_update_cache(cp, run_id, cache_data)` | Updates distributed cache with sub-task tracking + idempotency keys. Most failure-prone step. | `stubs.services.update_cache()` | Generates idempotency key `{run_id}:update_cache:cache_invalidation`; handles TimeoutError as UNKNOWN; skips only when `COMPLETED` (re-executes after `PARTIAL_FAILURE` to finish synchronization) |

**Idempotency pattern in write_db / update_cache:**
```
1. write_db: skip on COMPLETED or PARTIAL_FAILURE (probe before skip)
2. update_cache: skip only on COMPLETED
3. Generate idempotency_key = f"{run_id}:{step_name}:{sub_task}"
4. Emit STEP_STARTED event
5. Call service with idempotency_key
6. Service checks its own registry (Upgrade 3) — replays original result if key seen
7. Save sub-task outcome (SUCCESS/FAILED/UNKNOWN)
8. Emit appropriate event (SUBTASK_COMMITTED / SUBTASK_FAILED / NETWORK_TIMEOUT)
9. Save step with status COMPLETED / PARTIAL_FAILURE / FAILED
```

---

### `stubs/services.py` — Mock Distributed Services

| Class / Function | Purpose | Called By |
|---|---|---|
| `ServiceConfig` | Global failure-injection knobs: `inject_stale_data`, `inject_timeout`, `partial_write`, `cache_timeout`, `enable_latency`, etc. | `main.py` (configure_failure_injection), all service functions |
| `reset_service_state(checkpointer)` | Resets `_DEFAULT_STATE` dict and persists to SQLite via checkpointer. Called at start of each run. | `main()` |
| `set_checkpointer(cp)` / `_get_checkpointer()` | Sets/retrieves the global checkpointer reference so services can persist state. | `main()`, internal |
| `_load_state(key, default)` / `_save_state(key, value)` | Reads/writes from SQLite (via checkpointer) or falls back to in-memory `_DEFAULT_STATE`. | All service functions |
| `fetch_asset_location(asset_id)` | Returns current asset location. Simulates latency; can inject stale data, timeout, or unavailability. | `tools.execute_fetch_location()` |
| `validate_consistency(asset_data, expected_state)` | Compares fetched coords against expected target. Returns `is_synced` boolean + list of discrepancies (lat/lng diffs). | `tools.execute_validate_consistency()` |
| `write_db_correction(asset_id, correction_data, idempotency_key)` | Writes corrections to DB. Checks idempotency registry first; supports partial write simulation; updates `_DEFAULT_STATE.asset_location`. | `tools.execute_write_db()` |
| `update_cache(asset_id, cache_data, idempotency_key)` | Updates distributed cache. Most failure-prone — can timeout or be unavailable. Checks idempotency registry. Raises `CacheSyncFailure` (subclass of `TimeoutError`). | `tools.execute_update_cache()` |
| `verify_db_transaction(tx_id)` | Active verification probe: queries persisted asset state to confirm a transaction committed. Used during PARTIAL_FAILURE recovery to distinguish UNKNOWN from FAILED. Returns True if tx appears committed, False otherwise. | `tools.execute_write_db()` and `runner.execute_action("verify_db_transaction")` |
| `check_service_health()` | Returns a dict like `{"location": True, "database": True, "cache": True}` indicating which services are healthy. | Agent's `execute_action("check_system_health")` |

**Service exceptions:**

| Exception | Base Class | Meaning |
|---|---|---|
| `LocationServiceError` | `Exception` | Location service failure (timeout, unavailable) |
| `CacheSyncFailure` | `TimeoutError` | Cache write failed — outcome UNKNOWN (write may have committed server-side) |
| `StaleDataWarning` | `UserWarning` | Warning when stale data is detected |

---

### `debug_visualizer/server.py` — Web Dashboard

| Function / Component | Purpose | Reads From |
|---|---|---|
| `app` (Flask) | Web server providing a dashboard UI. | — |
| `get_db_connection()` | Creates SQLite connection to `data/agent_state.db`. | Same DB as Checkpointer |
| `get_run_data(run_id)` | Fetches all data for a run: run info, steps (with parsed JSON), decisions, sub-tasks, events, and lists all runs. | SQLite tables via raw queries |

**How it connects:** The visualizer reads directly from the same SQLite database (`data/agent_state.db`) that `Checkpointer` writes to. No API coupling — just shared file storage. Run the agent → open the visualizer → see real-time state.

---

## 3. Data Flow Diagram

```
┌─────────────┐     run_id      ┌──────────────────┐
│   main.py   │────────────────▶│  Checkpointer    │
│             │                  │  (SQLite)        │
│  CLI args   │◀────────────────│                  │
│  failure    │  summary +       │ runs table       │
│  injection  │  audit trail     │ steps table      │
└──────┬──────┘                  │ decisions table  │
       │                         │ sub_tasks table  │
       │                         │ events table     │
       │                         │ service_state    │
       │                         └────────┬─────────┘
       │                                  │
       │  checkpointer reference          │ shared DB file
       ▼                                  ▼
┌──────────────────┐            ┌──────────────────┐
│ AssetSyncAgent   │◀──────────▶│ debug_visualizer │
│ (runner.py)      │  set_      │ server.py        │
│                  │  check-    │ (Flask web UI)   │
│ get_execution_   │  pointer() │                  │
│ build_llm_prompt │           └──────────────────┘
│ parse_response   │
│ execute_action   │
└────────┬─────────┘
         │ calls
         ▼
┌──────────────────┐     idempotency_key    ┌──────────────────┐
│  tools.py        │◀──────────────────────▶│ services.py      │
│                  │                        │                  │
│ execute_fetch_   │   registry lookup      │ fetch_asset_     │
│ execute_valid-   │   (Upgrade 3)          │ location()       │
│ ate_consistency  │                        │ validate_        │
│ execute_write_db │                        │ consistency()    │
│ execute_update_  │                        │ write_db_        │
│ cache            │                        │ correction()     │
└──────────────────┘                        │ update_cache()   │
                                            │ check_service_   │
                                            │ health()         │
                                            └──────────────────┘
```

---

## 4. The Four Workflow Steps (in order)

| Step | Order | Tool Function | Service Function | Sub-Task | Idempotency Key Pattern |
|---|---|---|---|---|---|
| 1. `fetch_location` | 1 | `execute_fetch_location()` | `fetch_asset_location()` | — (single step) | N/A (read-only) |
| 2. `validate_consistency` | 2 | `execute_validate_consistency()` | `validate_consistency()` | — (single step) | N/A (read-only) |
| 3. `write_db_correction` | 3 | `execute_write_db()` | `write_db_correction()` | `database_write` | `{run_id}:write_db_correction:database_write` |
| 4. `update_cache` | 4 | `execute_update_cache()` | `update_cache()` | `cache_invalidation` | `{run_id}:update_cache:cache_invalidation` |

---

## 5. Failure States & Recovery Logic

### Step Statuses

| Status | Meaning | Recovery Behavior |
|---|---|---|
| `COMPLETED` | Step finished successfully | Skip on retry (idempotent) |
| `FAILED` | Step threw an exception | Agent forces health check, then may retry after all services healthy |
| `PARTIAL_FAILURE` | Write may have committed server-side but response incomplete/timeout | `write_db_correction`: probe + promote/skip; `update_cache`: retry until COMPLETED (with health-check gating) |
| `PENDING` | Not yet executed | Execute normally |

### Sub-Task Statuses (for write_db / update_cache)

| Status | When Set | Meaning |
|---|---|---|
| `SUCCESS` | Service returned normal response | Operation completed fully |
| `FAILED` | Service threw a non-timeout exception | Operation definitely did not happen |
| `UNKNOWN` | TimeoutError occurred | Write may have succeeded — reconciliation needed |

### Agent Failure Handling Rules (encoded in LLM prompt)

1. **Any step fails** → Next action MUST be `check_system_health`
2. **Health check shows a service DOWN** → Action MUST be `halt` (do NOT retry, do NOT call health again)
3. **All services HEALTHY after failure** → Agent may retry the failed step
4. **PARTIAL_FAILURE step in context** → Do NOT retry by default, except `update_cache` which must be retried until `COMPLETED`

---

## 6. Upgrade Features Summary

| Upgrade | Feature | Where Implemented |
|---|---|---|
| 1 | Sub-task granularity (SUCCESS/FAILED/UNKNOWN) | `checkpointer.save_sub_task()`, tool wrappers for write_db/update_cache |
| 2 | Append-only audit trail / mission log | `checkpointer.emit_event()`, `main.py`'s `print_audit_trail()` |
| 3 | Idempotency keys (mutation deduplication) | Tool wrappers generate keys; services check registry before re-executing |
| 4 | Service state in SQLite (durable mock data) | `checkpointer.service_state` table, `_load_state()`/`_save_state()` in services.py |

---

## Refinements

### Refinement 1: Accurate Run Status (HALTED vs COMPLETED)

**Problem:** When the cache failed and the agent stopped, the summary printed `Status: COMPLETED` — misleading because the workflow was intentionally paused, not successfully completed.

**Solution:** Added a distinct `HALTED` status that clearly differentiates between:
- **COMPLETED**: All steps finished successfully (green in visualizer)
- **HALTED**: Intentional pause due to service unavailability (yellow/red in visualizer)
- **FAILED**: Unrecoverable error

**Implementation:**
- Added `halt_run(run_id, reason, down_services)` to `Checkpointer` — sets status to `'HALTED'`, records `completed_at`, and emits a `WORKFLOW_HALTED` audit event with the list of down services
- In `runner.py`, when health check detects DOWN services: calls `self.checkpointer.halt_run()` instead of `complete_run()`, returns `"status": "HALTED"` in result dict

**Terminal output:**
```
[INFO] Services DOWN: cache
[INFO] Workflow halted by agent - service recovery required
Status: HALTED | Summary: Workflow halted - services unavailable: cache
```

### Refinement 2: Active Read-Verification Probe on Partial Writes

**Problem:** When `write_db_correction` returned a `PARTIAL_FAILURE`, the agent assumed it succeeded and skipped re-execution — but there was no verification that the transaction actually committed.

**Solution:** Added an active **Verification Probe** that queries the database to confirm the transaction before skipping. This distinguishes between:
- **UNKNOWN**: Timeout occurred, write may have succeeded (needs verification)
- **FAILED**: Write definitely did not happen (should retry)

**Implementation:**
- Added `verify_db_transaction(tx_id)` in `stubs/services.py` — queries persisted asset state to confirm a transaction committed
- In `runner.py`, LLM can explicitly choose `verify_db_transaction`; on success, `checkpointer.promote_step(...)` updates `write_db_correction` from `PARTIAL_FAILURE` to `COMPLETED`
- In `execute_write_db()` tool wrapper, retained probe-assisted skip logic for recovery paths that re-enter the tool wrapper directly

**Terminal output during recovery:**
```
[PROBE] write_db_correction: Verified tx tx_1786740286359 exists on database. Skipping write.
[EXECUTE] update_cache: Updating distributed cache...
[OK] update_cache: Cache updated successfully
```

**Audit trail entry:**
```json
{"timestamp": "...", "event": "VERIFICATION_PROBE_SUCCESS", "subtask": "database_write", "tx_id": "tx_1786740286359"}
```

---

## 7. Key Design Patterns

### Idempotency Guard Pattern
```python
# In every tool wrapper:
existing = checkpointer.get_step_result(run_id, step_name)
if existing and existing["status"] == "COMPLETED":
    return ToolResult(success=True, data=existing["output_data"])  # [SKIP]
```

### Service Idempotency Registry (Upgrade 3)
```python
# In services.py write_db_correction / update_cache:
registry = _load_state("idempotency_registry", {})
if idempotency_key in registry:
    return registry[idempotency_key]  # Replay original result
# ... execute operation ...
registry[idempotency_key] = result
_save_state("idempotency_registry", registry)
```

### Dynamic Decision Loop (not hardcoded sequence)
The agent does **NOT** follow a fixed `fetch → validate → write → cache` pipeline. Instead:
1. LLM receives current state context
2. LLM decides next action via JSON response
3. Agent executes chosen action
4. Repeat until DONE or halt

This allows the agent to skip steps, retry failures intelligently, and adapt to unexpected conditions.

---

## 8. Quick Reference: Import Graph

```
main.py
├── openai.OpenAI                    → LLM client
├── stubs.services.ServiceConfig     → failure injection knobs
├── stubs.services.set_checkpointer()→ register cp globally
├── stubs.services.reset_service_state()→ reset mock state
├── agent.checkpointer.Checkpointer  → SQLite persistence
└── agent.runner.AssetSyncAgent      → control loop

agent/runner.py
├── openai.OpenAI                    → LLM client (from main)
├── agent.checkpointer.Checkpointer  → state reads/writes
└── agent.tools.*                    → tool wrapper imports

agent/tools.py
├── stubs.services.*                 → service function imports
└── agent.checkpointer.Checkpointer  → checkpoint operations

stubs/services.py
├── agent.checkpointer (via set_checkpointer)→ state persistence
└── time, random                     → latency simulation
```

---

## 9. Running the Agent — Quick Commands

```bash
# Normal run (no failures)
python main.py --run-id test-001

# Cache timeout after DB write succeeds
python main.py --run-id test-002 --fail-at cache_update

# Cache service unavailable
python main.py --run-id test-003 --fail-at cache_unavailable

# Location service timeout
python main.py --run-id test-004 --fail-at location_service

# Location service unavailable
python main.py --run-id test-005 --fail-at location_unavailable

# LLM connection drop / server outage (fails before any step executes)
python main.py --run-id test-009 --clear --fail-at llm_connection

# Stale location data injection
python main.py --run-id test-006 --inject-stale

# Partial database write simulation
python main.py --run-id test-007 --partial-write

# Custom LLM server URL
python main.py --run-id test-008 --llm-url http://localhost:8080/v1
```

### Validated Scenario Matrix

CLI-exposed matrix dimensions:
- `--fail-at`: `none`, `cache_update`, `cache_unavailable`, `location_service`, `location_unavailable`, `llm_connection`
- `--inject-stale`: `0|1`
- `--partial-write`: `0|1`

Total initial-run combinations: $6 \times 2 \times 2 = 24$.

Observed initial outcomes:
- `fail_at=none` combinations: `COMPLETED`
- `fail_at=cache_update` combinations: `HALTED`
- `fail_at=cache_unavailable` combinations: `HALTED`
- `fail_at=location_service` combinations: `HALTED`
- `fail_at=location_unavailable` combinations: `HALTED`
- `fail_at=llm_connection` combinations: `FAILED` (LLM server unreachable — fails before any workflow step executes, so the other injection flags have no effect)

Observed resume outcomes (same `run_id`, no failure flags):
- All halted combinations resumed to `COMPLETED`.
- `llm_connection` combinations resume to `COMPLETED` once the LLM server is reachable again (no steps were executed, so the full workflow runs fresh from the checkpoint).

---

## 10. File Locations Summary

| Path | Role |
|---|---|
| `main.py` | CLI entry point, orchestrates startup |
| `agent/__init__.py` | Package marker |
| `agent/checkpointer.py` | SQLite persistence layer (6 tables) |
| `agent/runner.py` | Agent control loop with LLM decision-making |
| `agent/tools.py` | Idempotent wrappers around service calls |
| `stubs/__init__.py` | Package marker |
| `stubs/services.py` | Mock distributed services with failure injection |
| `data/agent_state.db` | SQLite database (created at runtime) |
| `debug_visualizer/server.py` | Flask web dashboard for inspecting runs |

---

*Generated as a living reference — update when code changes.*