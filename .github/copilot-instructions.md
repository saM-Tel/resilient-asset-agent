# Resilient Asset Agent - Copilot Instructions

## Project Overview
This is a fault-tolerant AI agent that synchronizes asset state across distributed services with intelligent failure recovery. Built for LEC AI Engineering Intern assessment.

## Architecture Principles
- **State Machine Pattern**: Agent follows dynamic workflow, not fixed sequence
- **Idempotency First**: Never re-execute completed steps; always check checkpoint before tool execution
- **Minimal Dependencies**: Plain Python + SQLite + OpenAI SDK (no heavy frameworks like CrewAI)
- **Transparent State Management**: All state tracked in SQLite with full audit trail

## Code Style Guidelines

### Python Standards
- Use type hints for all function signatures and class attributes
- Follow PEP 8 naming conventions (snake_case for functions/variables, PascalCase for classes)
- Keep functions focused: max 50 lines per function when possible
- Use docstrings for all public methods and modules

### Error Handling
- Always catch specific exceptions before generic ones
- Log errors with context (step name, run_id, error message)
- Never silently swallow exceptions - always log or re-raise

### State Management
- All state changes must be persisted to checkpoint store before returning success
- Use `Checkpointer` class for all database operations
- Always validate checkpoint data before using it in decisions

## Module Responsibilities

### `stubs/services.py`
Mock distributed services with configurable failure injection. Each service should:
- Accept configuration via `ServiceConfig` class
- Simulate realistic latency (0.1-2 seconds)
- Support failure modes: timeout, stale data, partial writes, unavailability

### `agent/checkpointer.py`
SQLite persistence layer. Must provide:
- Idempotent step execution tracking
- Full execution trace for audit/debugging
- Clean separation between runs via `run_id`

### `agent/tools.py`
Idempotent tool wrappers. Each wrapper must:
1. Check checkpoint before executing service call
2. Return cached result if step already completed
3. Save result to checkpoint after successful execution
4. Log failures with error details

### `agent/runner.py`
Agent control loop. Must implement:
- Dynamic decision-making via LLM (not hardcoded sequence)
- Max iteration limits to prevent infinite loops
- Clean recovery from partial failures
- Full audit trail of all decisions and reasoning

## Testing Expectations
- All failure scenarios must be reproducible via command-line flags
- Demo video should show: first run fails mid-workflow, second run recovers without duplicating work
- Terminal output should clearly show [SKIP], [EXECUTE], [OK], [FAIL] markers for easy video capture

## LLM Integration
- Use OpenAI-compatible API (connects to local llama-server on port 8000)
- Keep prompts concise and focused on current execution state
- Parse JSON responses robustly (handle markdown code blocks)
- Always log LLM reasoning for audit trail

## What NOT to Do
- Don't use CrewAI, LangChain, or other heavy agent frameworks
- Don't build web UIs - clean CLI with colored terminal output is preferred
- Don't hardcode workflow sequences - let LLM decide dynamically
- Don't skip checkpoint updates before returning success
