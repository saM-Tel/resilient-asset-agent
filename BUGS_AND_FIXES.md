# Bugs and Fixes - Resilient Asset Agent

This document details all bugs encountered during development and the solutions implemented to resolve them.

---

## 1. JSON Parsing Errors with LLM Responses

### Bug Description
The agent failed to parse JSON responses from the local LLM when the response included markdown code block formatting.

### Symptoms
```
json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
Error parsing LLM response
```

### Root Causes
1. **Code block language identifiers**: LLM would wrap JSON in markdown code blocks with language identifiers (e.g., ` ```json `, ` ```python `)
2. **Newlines in code blocks**: Extracted JSON would include leading newlines after the language identifier
3. **No fallback handling**: Parser would crash on unexpected format instead of providing sensible default

### Solution Implemented
Updated `parse_llm_response()` in [agent/runner.py](agent/runner.py) to:

```python
# Try to extract JSON from response (handle markdown code blocks)
if "```" in content:
    # Extract JSON from code block (handles ```json, ```python, etc.)
    start = content.find("```") + 3
    # Skip language identifier (e.g., "json", "python")
    first_line_end = content.find("\n", start)
    if first_line_end != -1:
        start = first_line_end + 1
    
    end = content.rfind("```")
    content = content[start:end].strip()

# Try to parse JSON with fallback
try:
    return json.loads(content)
except json.JSONDecodeError as e:
    # Fallback to fetch_location on parse failure
    return {
        "action": "fetch_location",
        "reasoning": f"Failed to parse LLM response: {str(e)}",
        "parameters": {"asset_id": "asset_001"}
    }
```

### Key Changes
- **Detects and strips markdown code block delimiters** (```` ``` ````)
- **Skips language identifier lines** (e.g., "json", "python")
- **Provides fallback action** instead of crashing
- **Logs parse errors** for debugging

### Files Modified
- [agent/runner.py](agent/runner.py#L175-L217) - `parse_llm_response()` method

---

## 2. Empty LLM Responses

### Bug Description
The LLM would sometimes return empty responses, causing the agent to freeze or crash.

### Symptoms
```
LLM Response: (empty or whitespace only)
json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
Agent stuck in iteration loop
```

### Root Causes
1. **LLM thinking mode**: Local Qwen model would sometimes enter extended thinking without returning content
2. **No timeout**: Requests could hang indefinitely waiting for response
3. **No fallback logic**: Agent had no recovery mechanism for empty responses
4. **No response counter**: Couldn't detect patterns of repeated empty responses

### Solution Implemented
Multiple fixes applied in [agent/runner.py](agent/runner.py):

#### 1. Simplified System Prompt
Changed from verbose prompt to direct, action-oriented prompt:
```python
system_prompt = """You are an agent synchronizing asset state. Workflow:
1. fetch_location - get location data
2. validate_consistency - check if matches target  
3. write_db_correction - write to database
4. update_cache - update cache

RULES:
- Never repeat completed steps
- Return ONLY valid JSON: {"action": "...", "reasoning": "...", "parameters": {...}}
- Use "DONE" when all steps complete
- Be brief and respond immediately
- If unsure, choose fetch_location"""
```

#### 2. Shorter Max Tokens
Reduced `max_tokens` from default to 200:
```python
response = self.client.chat.completions.create(
    model="qwen3.6-35b",
    messages=messages,
    temperature=0.1,
    max_tokens=200,  # Shorter responses minimize thinking mode
    timeout=10       # Prevent hangs from extended thinking
)
```

#### 3. Request Timeout
Added `timeout=10` to prevent indefinite hangs.

#### 4. Empty Response Tracking
Implemented counter to detect consecutive empty responses:
```python
empty_responses = 0  # Track consecutive empty responses

# In loop:
if response_content:
    empty_responses = 0  # Reset counter on valid response
else:
    empty_responses += 1
    print("[WARN] LLM returned empty response\n")
    
    # If too many empty responses, force progress with a default action
    if empty_responses >= 2:
        print("[WARN] Forcing progress after empty responses...")
        # Determine sensible next step based on what's completed
        if not context["completed_steps"]:
            response_content = '{"action": "fetch_location", ...}'
        elif not any(s["step_name"] == "validate_consistency" ...):
            response_content = '{"action": "validate_consistency", ...}'
        # ... etc
```

#### 5. Auto-Complete Detection
Added logic to detect when all steps are completed and auto-complete the workflow:
```python
# Check if all required steps are completed - auto-complete if so
completed_step_names = set(s["step_name"] for s in context["completed_steps"])
required_steps = {"fetch_location", "validate_consistency", "write_db_correction", "update_cache"}

if required_steps.issubset(completed_step_names):
    print("[OK] All required steps completed! Auto-completing workflow.")
    self.checkpointer.complete_run(self.run_id)
    return {
        "status": "COMPLETED",
        "iterations": iteration,
        "summary": "Asset synchronization completed (auto-detected)"
    }
```

### Files Modified
- [agent/runner.py](agent/runner.py#L143-L170) - Simplified prompt in `build_llm_prompt()`
- [agent/runner.py](agent/runner.py#L310-L360) - Empty response handling and force-progress logic in `run()`
- [agent/runner.py](agent/runner.py#L295-L307) - Auto-complete detection

---

## 3. Windows Terminal Encoding Issues

### Bug Description
Terminal output with emoji characters would fail on Windows with Unicode encoding errors.

### Symptoms
```
UnicodeEncodeError: 'utf-8' codec can't encode character '\U0001f6a8' in position X: 
surrogates not allowed
```

Output: `❌ Failed to connect to LLM server...`
Terminal unable to render emoji, crash on print.

### Root Cause
Windows PowerShell terminal (even with UTF-8 support) has limitations with certain emoji characters. The specific emoji used (`❌`, `✅`) are not properly supported in all Windows terminal configurations.

### Solution Implemented
Replaced emoji characters with plain text status markers in [main.py](main.py):

**Before:**
```python
print(f"❌ Failed to connect to LLM server at {args.llm_url}: {e}")
```

**After:**
```python
print(f"[FAIL] Failed to connect to LLM server at {args.llm_url}: {e}")
```

Also replaced in tool output markers across the codebase:
- `❌` → `[FAIL]`
- `✅` → `[OK]`
- `⏭️` → `[SKIP]`
- `⚙️` → `[EXECUTE]`
- `🚨` → `[WARN]`

This provides clear, visible status indicators while maintaining terminal compatibility across all platforms.

### Files Modified
- [main.py](main.py#L124) - Connection error message
- [agent/tools.py](agent/tools.py) - All status markers in tool execution output
- [agent/runner.py](agent/runner.py) - All status markers in iteration output

---

## 4. Module Import Errors (Virtual Environment)

### Bug Description
When running the agent, `ModuleNotFoundError: No module named 'openai'` would occur.

### Symptoms
```
ModuleNotFoundError: No module named 'openai'
Traceback (most recent call last):
  File "main.py", line X, in <module>
    from openai import OpenAI
```

### Root Cause
Python virtual environment (`venv/`) was not activated, causing the interpreter to use system Python without required dependencies.

### Solution Implemented
Two approaches:

1. **Activate virtual environment explicitly**:
   ```powershell
   # On Windows PowerShell
   .\venv\Scripts\Activate.ps1
   python main.py --run-id test-001
   ```

2. **Use fully-qualified venv Python**:
   ```powershell
   .\venv\Scripts\python.exe main.py --run-id test-001
   ```

Updated documentation in [README.md](README.md) and comments in [main.py](main.py) to clarify this requirement.

### Files Modified
- [README.md](README.md#L40-L60) - Setup and run instructions
- [main.py](main.py#L1-L20) - Comments explaining venv requirement

---

## 5. Idempotency and Step Skipping

### Bug Description
Initial implementation didn't properly skip completed steps, risking duplicate execution and side effects.

### Symptoms
- Second run with same `run_id` would execute all steps again
- Could cause duplicate database writes
- Cache could be updated multiple times with redundant operations

### Root Cause
Tool wrappers in [agent/tools.py](agent/tools.py) didn't check checkpoints before execution.

### Solution Implemented
Each tool wrapper now implements the idempotency guard pattern:

**Example: `execute_fetch_location()`**
```python
def execute_fetch_location(checkpointer: Checkpointer, run_id: str, asset_id: str) -> ToolResult:
    """Fetch location with idempotency check."""
    
    # Check if already completed
    completed_steps = checkpointer.get_completed_steps(run_id)
    for step in completed_steps:
        if step["step_name"] == "fetch_location":
            print(f"[SKIP] fetch_location: Already completed, using cached result")
            return ToolResult(
                success=True,
                step_name="fetch_location",
                output_data=step["output_data"]
            )
    
    # Execute if not completed
    print(f"[EXECUTE] fetch_location: asset_id={asset_id}")
    try:
        result = LocationService.fetch_location(asset_id)
        # Save to checkpoint on success
        checkpointer.save_step_execution(
            run_id=run_id,
            step_name="fetch_location",
            status="COMPLETED",
            output_data=result
        )
        return ToolResult(success=True, step_name="fetch_location", output_data=result)
    except Exception as e:
        # Log failure
        checkpointer.save_step_execution(
            run_id=run_id,
            step_name="fetch_location",
            status="FAILED",
            error=str(e)
        )
        return ToolResult(success=False, step_name="fetch_location", error=str(e))
```

### Key Features
- **Pre-execution check**: Queries checkpoint for completion status
- **Cached result return**: Returns stored output without re-execution
- **Atomic persistence**: Updates checkpoint only after successful execution
- **Failure tracking**: Records failures for audit trail
- **Clear logging**: `[SKIP]`, `[EXECUTE]`, `[OK]`, `[FAIL]` markers show what's happening

### Files Modified
- [agent/tools.py](agent/tools.py) - All tool wrapper functions
- [agent/checkpointer.py](agent/checkpointer.py) - Query and persistence methods

---

## 6. LLM Connection Timeout Issues

### Bug Description
Agent would hang indefinitely when the local LLM server was slow or unresponsive.

### Symptoms
```
Agent frozen at LLM call
No output for several minutes
Process must be manually killed
```

### Root Cause
OpenAI API client had no timeout configured, and the agent loop didn't have time limits.

### Solution Implemented
Added timeout to LLM API call in [agent/runner.py](agent/runner.py#L320-L328):

```python
try:
    response = self.client.chat.completions.create(
        model="qwen3.6-35b",
        messages=messages,
        temperature=0.1,
        max_tokens=200,  # Shorter responses minimize thinking mode
        timeout=10  # Prevent hangs from extended thinking
    )
```

Also added iteration limits to prevent infinite loops:
```python
MAX_ITERATIONS = 10
iteration = 0

while iteration < MAX_ITERATIONS:
    iteration += 1
    # ... execute iteration
    
    if iteration >= MAX_ITERATIONS - 1:
        print("[WARN] Approaching max iterations - marking run as FAILED")
```

### Files Modified
- [agent/runner.py](agent/runner.py#L320-L330) - Added timeout and max iteration logic

---

## Summary of Fixes

| Bug | Root Cause | Solution | Impact |
|-----|-----------|----------|--------|
| JSON Parse Errors | Markdown code blocks in LLM response | Strip code blocks, add fallback | Agent resilient to LLM response format variations |
| Empty LLM Responses | Extended thinking mode | Simplified prompt, timeout, force-progress | Prevents hanging, auto-completes workflow |
| Windows Encoding | Emoji incompatibility | Replace emojis with text markers | Cross-platform compatibility |
| Import Errors | Missing venv activation | Document venv requirement | Clear setup instructions |
| Duplicate Execution | No idempotency check | Add pre-execution checkpoint check | Guarantees idempotent execution |
| Connection Hangs | No timeout configured | Add request timeout and iteration limits | Prevents indefinite hangs |

---

## Testing the Fixes

### Scenario 1: Normal Workflow (No Failures)
```bash
python main.py --run-id test-001
```
**Expected**: All 4 steps complete successfully in 5-10 iterations.

### Scenario 2: Failure Recovery
```bash
# First run - inject cache timeout
python main.py --run-id demo-fail --fail-at cache_update

# Second run - same run-id, still failing
python main.py --run-id demo-fail --fail-at cache_update

# Third run - same run-id, remove failure
python main.py --run-id demo-fail
```

**Expected**:
- Run 1: `[EXECUTE]` fetch, validate, write_db; `[FAIL]` update_cache → Status: FAILED
- Run 2: `[SKIP]` fetch, validate, write_db; `[FAIL]` update_cache → Status: FAILED
- Run 3: `[SKIP]` fetch, validate, write_db; `[EXECUTE]` update_cache → Status: COMPLETED

This demonstrates:
1. Idempotency (steps skipped on re-run with same run-id)
2. Recovery from partial failure (only failed step retried)
3. Successful completion when transient failure is removed

---

## Lessons Learned

1. **LLM Response Robustness**: Never assume JSON will be formatted a particular way. Always include fallback parsing logic.
2. **Empty Response Handling**: LLMs may think for a long time or return nothing. Implement timeouts and forced progress mechanisms.
3. **Platform Compatibility**: Emoji and special characters can cause encoding issues on Windows. Use plain text for status indicators.
4. **Idempotency First**: Always check state before executing operations. Persist state atomically after execution.
5. **Timeout Everything**: Any external service call should have a timeout to prevent indefinite hangs.
6. **Clear Logging**: Status markers (`[SKIP]`, `[EXECUTE]`, `[OK]`, `[FAIL]`) make debugging and demo videos much clearer.

