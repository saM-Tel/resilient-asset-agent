# Resilient Asset Agent - Implementation Plan

## Project Status: CORE BUILD COMPLETE ✅

All core modules are implemented and committed to GitHub. Now debugging runtime issues and refining the agent loop.

---

## Completed Modules

### ✅ Phase 1: Foundation (DONE)
- [x] `stubs/services.py` - Mock distributed services with failure injection
- [x] `agent/checkpointer.py` - SQLite persistence layer with idempotency
- [x] `agent/tools.py` - Idempotent tool wrappers
- [x] `agent/runner.py` - LLM-driven agent loop
- [x] `main.py` - CLI entry point with failure injection flags
- [x] `.github/copilot-instructions.md` - Project guidelines for Copilot
- [x] `README.md` - Complete documentation

### ✅ Phase 2: Basic Testing (DONE)
- [x] LLM connection test
- [x] Mock service execution
- [x] Checkpoint persistence

---

## Current Work: Debug & Refine

### 🐛 Issue: JSON Parsing Error
**Problem**: Parser fails when LLM returns empty response or JSON with markdown code block language identifier (`\`\`\`json`)

**Current Output**:
```
LLM Response: (empty or wrapped in ```json)
❌ Error: Expecting value: line 1 column 1 (char 0)
```

**Root Cause**: `parse_llm_response()` in `runner.py` doesn't handle:
1. Empty/whitespace-only responses
2. Code blocks with language specifiers (`\`\`\`json` instead of just ` ``` `)

**Fix Required**: Update `parse_llm_response()` to:
- Detect and skip language identifiers
- Handle empty responses gracefully
- Add fallback error message for debugging

---

## Remaining Work

### Phase 3: Fix Runtime Issues
- [ ] Fix JSON parsing in `runner.py` to handle code block variants
- [ ] Add robust error handling for empty LLM responses
- [ ] Test with actual llama-server responses
- [ ] Verify idempotency on second run

### Phase 4: Testing & Validation
- [ ] Run demo scenario: First run fails at cache → Second run recovers
- [ ] Verify `[SKIP]`, `[EXECUTE]`, `[OK]`, `[FAIL]` markers in output
- [ ] Create screen recording for assessment submission
- [ ] Validate checkpoint state across runs

### Phase 5: Polish & Documentation
- [ ] Add `TESTING.md` with test scenarios and expected output
- [ ] Create quick-start guide for LLM server setup
- [ ] Document failure injection modes
- [ ] Add inline code comments for complex logic

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│           Asset Sync Agent (runner.py)              │
│  Dynamic workflow driven by LLM decisions            │
└──────────────────────┬──────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
    ┌────────┐  ┌────────────┐  ┌──────────┐
    │ Tools  │  │ Checkpoint │  │   LLM    │
    │ (tools)│  │ Store (db) │  │ (OpenAI) │
    └────────┘  └────────────┘  └──────────┘
        │              │
        └──────────┬───┘
                   ▼
        ┌──────────────────────┐
        │  Mock Services       │
        │  (Location, DB, Cache)
        └──────────────────────┘
```

---

## Failure Scenarios to Test

| Scenario | Command | Expected Behavior |
|----------|---------|-------------------|
| Normal sync | `python main.py --run-id test-001` | All steps complete, asset synced |
| Cache timeout | `python main.py --run-id demo-fail --fail-at cache_update` | Fails at step 4 (cache) |
| Recovery | `python main.py --run-id demo-recovery --fail-at cache_update` | Skips steps 1-3, retries cache only |
| Stale data | `python main.py --run-id test-stale --inject-stale` | Detects stale location, still syncs |
| Partial write | `python main.py --run-id test-partial --partial-write` | DB returns incomplete response |

---

## Success Criteria

- ✅ Agent successfully fetches location
- ✅ Agent validates consistency against expected state
- ✅ Agent writes corrections to DB
- ✅ Agent updates cache (or handles failure)
- ✅ Second run detects completed steps and skips them
- ✅ Output clearly shows `[SKIP]`, `[EXECUTE]`, `[OK]`, `[FAIL]` markers
- ✅ Checkpoint state persists across runs
- ✅ LLM decisions logged for audit trail

---

## Notes for Implementation

### Key Decisions Made
1. **No Heavy Frameworks**: Plain Python + SQLite + OpenAI SDK (not CrewAI/LangChain)
2. **Dynamic Workflow**: LLM decides next step, not hardcoded sequence
3. **Idempotency First**: Always check checkpoint before re-executing
4. **Minimal State**: Only track what's needed (run_id, steps, decisions)

### What Could Be Improved (Future)
- Distributed locking for multi-agent scenarios
- Saga pattern with compensation/rollback
- Exponential backoff on retries
- Health check dashboard
- Configuration profiles for complex scenarios

---

## Timeline

| Phase | Status | Deadline |
|-------|--------|----------|
| Core Build | ✅ DONE | - |
| Runtime Debugging | 🔧 IN PROGRESS | Today |
| Testing & Validation | ⏳ TODO | Tomorrow |
| Polish & Submit | ⏳ TODO | End of week |
