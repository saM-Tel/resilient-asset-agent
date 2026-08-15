"""
Agent control loop - The brain of the resilient asset agent.

This module implements the core execution engine that:
1. Reads the current execution state from the checkpoint store
2. Prompts the local LLM to decide the next action based on history
3. Executes tools through idempotent wrappers
4. Updates checkpoints after each step
5. Recovers intelligently from partial failures

The agent uses a dynamic decision loop - it doesn't follow a fixed sequence,
but evaluates tool output and decides what to do next based on the result.
"""

import json
from typing import Any, Optional

from openai import OpenAI

from agent.checkpointer import Checkpointer
from agent.tools import (
    execute_fetch_location,
    execute_validate_consistency,
    execute_write_db,
    execute_update_cache,
)


class AssetSyncAgent:
    """
    LLM-driven agent that synchronizes asset state across distributed services.
    
    The agent maintains an execution trace and uses the local LLM to make
    dynamic decisions about what step to execute next based on current state.
    
    Key features:
    - Dynamic workflow (not fixed sequence)
    - Idempotent step execution
    - Intelligent recovery from partial failures
    - Full audit trail of all decisions
    """
    
    def __init__(self, client: OpenAI, checkpointer: Checkpointer, run_id: str):
        self.client = client
        self.checkpointer = checkpointer
        self.run_id = run_id
        
        # Recovery state tracking (persists across iterations)
        self._force_health_check = False
        self._last_health_results = None
    
    def _get_latest_step_output(self, completed_steps: list[dict], step_name: str) -> Optional[dict]:
        """Get output data of the latest completed step by name."""
        for step in reversed(completed_steps):
            if step.get("step_name") == step_name and step.get("output_data"):
                return step["output_data"]
        return None

    def _get_correction_data(self, completed_steps: list[dict]) -> Optional[dict]:
        """Get corrected coordinates written by write_db_correction, if any.

        The correction is stored in the step's input_data under
        'correction_data'. Returns None when no correction was applied so
        callers can fall back to the original fetch_location values.
        """
        for step in reversed(completed_steps):
            if step.get("step_name") != "write_db_correction":
                continue
            input_data = step.get("input_data") or {}
            correction = input_data.get("correction_data")
            if correction:
                return correction
        return None

    def get_execution_context(self) -> dict:
        """
        Build the current execution context from checkpoint store.
        
        Returns:
            Dictionary with run status, completed steps, failed steps, and pending steps
        """
        run_status = self.checkpointer.get_run_status(self.run_id)
        completed_steps = self.checkpointer.get_completed_steps(self.run_id)
        failed_steps = self.checkpointer.get_failed_steps(self.run_id)
        partial_steps = self.checkpointer.get_partial_steps(self.run_id)
        execution_trace = self.checkpointer.get_execution_trace(self.run_id)
        
        return {
            "run_id": self.run_id,
            "status": run_status["status"] if run_status else "UNKNOWN",
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "partial_steps": partial_steps,
            "execution_trace": execution_trace
        }
    
    def build_llm_prompt(self, context: dict) -> list[dict]:
        """
        Build the prompt for the LLM based on current execution state.
        
        Uses a simplified, action-oriented prompt to minimize thinking time
        and prevent extended thinking mode from causing empty responses.
        
        Args:
            context: Current execution context from get_execution_context()
            
        Returns:
            List of message dictionaries for the LLM API
        """
        # Simplified system prompt - direct and action-oriented
        system_prompt = """You are an agent synchronizing asset state. Workflow:
1. fetch_location - get location data
2. validate_consistency - check if matches target  
3. write_db_correction - write to database
4. update_cache - update cache

ADDITIONAL TOOL:
- check_system_health - diagnose service status when steps fail

FAILURE HANDLING RULES:
- If ANY step fails, DO NOT retry it immediately. Your next action MUST be check_system_health.
- CRITICAL HEALTH CHECK RULE: After calling check_system_health, if the returned health status shows a service is False/DOWN (e.g., {"cache": false}):
  - DO NOT call 'check_system_health' again.
  - DO NOT retry the failed step.
  - You MUST output action "halt" with reasoning explaining: "[Service] service is reported as DOWN by health check. Pausing workflow until service recovers."
- Only retry a failed step after health check confirms ALL services are HEALTHY (True).
- PARTIAL FAILURE RULE: A step listed under "Partial" has ALREADY committed its write server-side (the response was just incomplete). DO NOT retry it - proceed to the NEXT step in the workflow.

RULES:
- Never repeat completed or partial steps
- Return ONLY valid JSON: {"action": "...", "reasoning": "...", "parameters": {...}}
- Use "DONE" when all steps complete
- Be brief and respond immediately"""
        
        # Build execution history summary (brief format)
        completed_names = [s["step_name"] for s in context["completed_steps"]]
        failed_names = [s["step_name"] for s in context["failed_steps"]]
        partial_names = [s["step_name"] for s in context.get("partial_steps", [])]
        
        user_message = f"""Completed: {completed_names}
Failed: {failed_names}
Partial (already committed, do NOT retry): {partial_names}

Decide next action. Return JSON only."""
        
        # If force_health_check is set, add explicit instruction
        if self._force_health_check:
            user_message += "\n\n[IMPORTANT] A step just failed. Your next action MUST be check_system_health to diagnose service status."
        
        # If we have health check results from a previous iteration, inject them so LLM can act on them
        if self._last_health_results is not None:
            health = self._last_health_results
            down_services = [svc for svc, healthy in health.items() if not healthy]
            user_message += f"\n\n[HEALTH CHECK RESULTS] {health}"
            if down_services:
                user_message += f"\n[CRITICAL] Services DOWN: {', '.join(down_services)}. Per failure handling rules, you MUST output action 'halt' - do NOT call check_system_health again."
        
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
    
    def parse_llm_response(self, response_content: str, context: dict = None) -> dict:
        """
        Parse the LLM's JSON response into a decision.
        
        Args:
            response_content: Raw text from LLM response
            context: Optional execution context for smarter fallback
            
        Returns:
            Dictionary with action, reasoning, and parameters
        """
        # Clean up the response
        content = response_content.strip()
        
        # Handle empty response
        if not content:
            print("[WARN] LLM returned empty response")
            return {
                "action": "fetch_location",
                "reasoning": "Empty response from LLM, starting with location fetch",
                "parameters": {"asset_id": "asset_001"}
            }
        
        # Try to extract JSON from markdown code blocks if present
        if content.startswith("```"):
            # Find the closing backticks
            end = content.find("```", 3)
            if end != -1:
                # Extract everything between opening and closing markers
                inner = content[3:end].strip()
                # Skip language identifier line (e.g., "json" or "python")
                first_newline = inner.find("\n")
                if first_newline != -1:
                    content = inner[first_newline + 1:].strip()
                else:
                    content = inner
        
        # Try to parse JSON directly
        try:
            parsed = json.loads(content)
            # Validate it has at least an action field
            if isinstance(parsed, dict) and "action" in parsed:
                return parsed
        except json.JSONDecodeError as e:
            print(f"[WARN] Failed to parse JSON: {e}")
        
        # If parsing failed, try to find a JSON object within the response
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            json_str = content[start:end + 1]
            try:
                parsed = json.loads(json_str)
                if isinstance(parsed, dict) and "action" in parsed:
                    return parsed
            except json.JSONDecodeError as e2:
                print(f"[WARN] Extracted JSON also failed to parse: {e2}")
        
        # Ultimate fallback - pick a better default based on what's already completed
        if context:
            completed_names = [s["step_name"] for s in context.get("completed_steps", [])]
            if "update_cache" not in completed_names and "write_db_correction" not in completed_names:
                return {"action": "fetch_location", "reasoning": "Parse failed, starting fresh", "parameters": {"asset_id": "asset_001"}}
            elif "validate_consistency" not in completed_names:
                return {"action": "validate_consistency", "reasoning": "Parse failed, next step is validation", "parameters": {}}
            elif "write_db_correction" not in completed_names:
                return {"action": "write_db_correction", "reasoning": "Parse failed, next step is DB write", "parameters": {}}
        
        # Absolute fallback
        return {
            "action": "fetch_location",
            "reasoning": "Failed to parse LLM response into valid JSON action",
            "parameters": {"asset_id": "asset_001"}
        }
    
    def execute_action(self, action: str, parameters: dict = None, reasoning: str = "") -> tuple[bool, dict]:
        """
        Execute the LLM's chosen action through the appropriate tool.
        
        Args:
            action: Tool name to execute
            parameters: Parameters for the tool call
            reasoning: Optional reasoning from the LLM (used for halt/stop actions)
            
        Returns:
            Tuple of (success: bool, result: dict)
        """
        parameters = parameters or {}
        
        if action == "DONE":
            return True, {"message": "All steps completed"}
        
        if action == "fetch_location":
            result = execute_fetch_location(
                self.checkpointer, self.run_id,
                parameters.get("asset_id", "asset_001")
            )
            return result.success, result.to_dict()
        
        elif action == "validate_consistency":
            # Get latest location data from completed steps
            completed = self.checkpointer.get_completed_steps(self.run_id)
            location_data = self._get_latest_step_output(completed, "fetch_location")
            
            if not location_data:
                return False, {"error": "No location data available - must fetch first"}
            
            result = execute_validate_consistency(self.checkpointer, self.run_id, location_data)
            return result.success, result.to_dict()
        
        elif action == "write_db_correction":
            # Get location and validation data
            completed = self.checkpointer.get_completed_steps(self.run_id)
            location_data = self._get_latest_step_output(completed, "fetch_location")
            validation_data = self._get_latest_step_output(completed, "validate_consistency")
            
            if not location_data or not validation_data:
                return False, {"error": "Need location and validation data first"}
            
            # Check if already synced
            if validation_data.get("is_synced"):
                # Save checkpoint step so workflow knows this step is satisfied
                self.checkpointer.save_step(
                    run_id=self.run_id,
                    step_name="write_db_correction",
                    step_order=3,
                    status="COMPLETED",
                    input_data={"validation_data": validation_data},
                    output_data={"message": "Asset already synced, no correction needed", "is_synced": True}
                )
                print("  [OK] write_db_correction: Asset already synced, marked completed")
                return True, {"message": "Asset already synced, no correction needed"}
            
            # Build correction from discrepancies (expected values)
            correction_data = {"status": "synced"}
            discrepancies = validation_data.get("discrepancies", [])
            
            for disc in discrepancies:
                if disc.get("field") == "latitude":
                    correction_data["lat"] = disc.get("expected")
                elif disc.get("field") == "longitude":
                    correction_data["lng"] = disc.get("expected")
            
            # Fallback if discrepancies not found
            if "lat" not in correction_data:
                correction_data["lat"] = location_data.get("lat")
            if "lng" not in correction_data:
                correction_data["lng"] = location_data.get("lng")
            
            result = execute_write_db(self.checkpointer, self.run_id, correction_data)
            return result.success, result.to_dict()
        
        elif action == "update_cache":
            # Get latest location data for caching
            completed = self.checkpointer.get_completed_steps(self.run_id)
            location_data = self._get_latest_step_output(completed, "fetch_location")
            
            if not location_data:
                return False, {"error": "No location data available - must fetch first"}
            
            # Prefer corrected coordinates from write_db_correction over the
            # original fetch_location output, so the cache never holds stale
            # values when a correction was applied in step 3.
            cache_data = dict(location_data)
            correction = self._get_correction_data(completed)
            if correction:
                for field in ("lat", "lng"):
                    if correction.get(field) is not None:
                        cache_data[field] = correction[field]
            
            cache_data = parameters.get("cache_data") or cache_data
            
            result = execute_update_cache(self.checkpointer, self.run_id, cache_data)
            return result.success, result.to_dict()
        
        elif action == "check_system_health":
            from stubs.services import check_service_health
            health = check_service_health()
            print(f"  [OK] check_system_health: {health}")
            # Store results in instance variable so LLM sees them next iteration
            self._last_health_results = health
            return True, {"health_status": health}
        
        elif action in ["halt", "stop"]:
            # Agent has decided to halt due to service unavailability
            print(f"[INFO] Workflow halted by agent: {reasoning}")
            self.checkpointer.complete_run(self.run_id)  # Mark as completed (intelligently halted)
            return True, {"message": f"Workflow halted - {reasoning}"}
        
        else:
            return False, {"error": f"Unknown action: {action}"}
    
    def run(self):
        """
        Main execution loop - runs until all steps complete or max iterations reached.
        
        Returns:
            Dictionary with final execution summary
        """
        MAX_ITERATIONS = 15
        iteration = 0
        empty_responses = 0  # Track consecutive empty responses
        last_failed_action = None  # Track the most recent failed action for intelligent recovery
        
        print(f"\n{'='*60}")
        print(f"Starting Asset Sync Agent - Run ID: {self.run_id}")
        print(f"{'='*60}\n")
        
        # Ensure run record exists in the runs table (create it if missing)
        existing_run = self.checkpointer.get_run_status(self.run_id)
        if not existing_run:
            print(f"[INFO] Creating new run '{self.run_id}'")
            self.checkpointer.create_run(self.run_id)
        elif existing_run["status"] != "IN_PROGRESS":
            # Re-running a completed/failed run - clear previous data for clean slate
            print(f"[INFO] Re-running with existing ID '{self.run_id}' - clearing previous data")
            self.checkpointer.clear_run(self.run_id)
        
        # Emit run-started event to the audit trail (Upgrade 2)
        self.checkpointer.emit_event(
            self.run_id, "RUN_STARTED",
            details={"max_iterations": MAX_ITERATIONS}
        )
        
        while iteration < MAX_ITERATIONS:
            iteration += 1
            print(f"\n--- Iteration {iteration} ---\n")
            
            # Get current state
            context = self.get_execution_context()
            
            # Check if all required steps are completed - auto-complete if so.
            # A step in PARTIAL_FAILURE counts as "done" for progression: the
            # mutation likely committed server-side, so re-executing would be a
            # duplicate write. We proceed to the next step instead.
            #
            # IMPORTANT: We only auto-complete when NO failure is pending
            # reconciliation. If a step just failed (e.g. cache timeout ->
            # UNKNOWN), we must run the health check / halt logic first rather
            # than declaring success over an indeterminate state.
            #
            # NOTE ON WHEN THIS FIRES: In this example project, clear_run() wipes
            # all steps at the start of a re-run (main.py line ~170), so
            # auto-complete never actually triggers - there's nothing to complete
            # against on restart. It IS useful in real-world scenarios where state
            # persists across process crashes or long-running agents: if all 4
            # steps finish naturally within a single run, the loop would otherwise
            # still ask the LLM one more time (iteration N+1) before exiting when
            # the LLM returns "DONE". Auto-complete avoids that extra LLM call by
            # detecting completion at the top of the next iteration instead.
            if not self._force_health_check:
                completed_step_names = set(s["step_name"] for s in context["completed_steps"])
                partial_step_names = set(s["step_name"] for s in context["partial_steps"])
                done_step_names = completed_step_names | partial_step_names
                required_steps = {"fetch_location", "validate_consistency", "write_db_correction", "update_cache"}
                
                if required_steps.issubset(done_step_names):
                    print("[OK] All required steps completed! Auto-completing workflow.")
                    self.checkpointer.emit_event(
                        self.run_id, "RUN_COMPLETED",
                        details={"reason": "all_steps_completed"}
                    )
                    self.checkpointer.complete_run(self.run_id)
                    return {
                        "status": "COMPLETED",
                        "iterations": iteration,
                        "summary": "Asset synchronization completed (auto-detected)"
                    }
            
            # INTELLIGENT RECOVERY: If a step just failed, force check_system_health
            if self._force_health_check:
                print("[INFO] Step failed - forcing intelligent recovery via health check\n")
                
                # Emit reconciliation event to the audit trail (Upgrade 2)
                self.checkpointer.emit_event(
                    self.run_id, "RECONCILIATION_STARTED",
                    sub_task=last_failed_action,
                    details={"trigger": "step_failure", "action": "check_system_health"}
                )
                
                # Execute health check directly (no LLM needed)
                from stubs.services import check_service_health
                health = check_service_health()
                print(f"  [OK] check_system_health: {health}")
                
                # Log the decision
                self.checkpointer.save_decision(
                    run_id=self.run_id,
                    step_name=f"iteration_{iteration}",
                    reasoning=f"{last_failed_action} failed. Calling health check to diagnose.",
                    next_action="check_system_health"
                )
                
                # Store health results in instance variable so LLM can see them next iteration
                self._last_health_results = health
                
                # If any service is DOWN, halt immediately - no need for LLM
                down_services = [svc for svc, healthy in health.items() if not healthy]
                if down_services:
                    print(f"[INFO] Services DOWN: {', '.join(down_services)}")
                    print(f"[INFO] Workflow halted by agent - service recovery required\n")
                    
                    # Emit halt event to the audit trail (Upgrade 2)
                    self.checkpointer.emit_event(
                        self.run_id, "WORKFLOW_HALTED",
                        details={"down_services": down_services,
                                 "reason": "service_unavailable"}
                    )
                    self.checkpointer.halt_run(
                        run_id=self.run_id,
                        reason="service_unavailable",
                        down_services=down_services
                    )
                    return {
                        "status": "HALTED",  # Distinct from COMPLETED — services unavailable
                        "iterations": iteration,
                        "summary": f"Workflow halted - services unavailable: {', '.join(down_services)}"
                    }
                
                # All services healthy - clear flag and continue to next iteration
                self._force_health_check = False
                last_failed_action = None
                continue
            
            # Build and send prompt to LLM
            messages = self.build_llm_prompt(context)
            
            try:
                response = self.client.chat.completions.create(
                    model="qwen3.5-35b-thinking-off",
                    messages=messages,
                    temperature=0.1,
                    max_tokens=200,  # Shorter responses minimize thinking mode
                    timeout=10  # Prevent hangs from extended thinking
                )
                
                response_content = response.choices[0].message.content.strip()
                if response_content:
                    empty_responses = 0  # Reset counter on valid response
                    print(f"LLM Response:\n{response_content}\n")
                else:
                    empty_responses += 1
                    print("[WARN] LLM returned empty response\n")
                    
                    # If too many empty responses, force progress with a default action
                    if empty_responses >= 2:
                        print("[WARN] Forcing progress after empty responses...")
                        # Determine sensible next step based on what's completed
                        if not context["completed_steps"]:
                            response_content = '{"action": "fetch_location", "reasoning": "First step: fetch location", "parameters": {"asset_id": "asset_001"}}'
                        elif not any(s["step_name"] == "validate_consistency" for s in context["completed_steps"]):
                            response_content = '{"action": "validate_consistency", "reasoning": "Next: validate consistency", "parameters": {}}'
                        elif not any(s["step_name"] == "write_db_correction" for s in context["completed_steps"]):
                            response_content = '{"action": "write_db_correction", "reasoning": "Next: write corrections", "parameters": {}}'
                        else:
                            response_content = '{"action": "update_cache", "reasoning": "Final step: update cache", "parameters": {}}'
                        empty_responses = 0
                
                # Parse decision - pass context so fallback can pick a better default
                decision = self.parse_llm_response(response_content, context)
                action = decision.get("action", "UNKNOWN")
                reasoning = decision.get("reasoning", "")
                parameters = decision.get("parameters", {})
                
                print(f"Decision: {action}")
                print(f"Reasoning: {reasoning}\n")
                
                # Log the decision
                self.checkpointer.save_decision(
                    run_id=self.run_id,
                    step_name=f"iteration_{iteration}",
                    reasoning=reasoning,
                    next_action=action
                )
                
                # Execute the action
                if action == "DONE":
                    if self._force_health_check:
                        print("[WARN] LLM signaled DONE while recovery health check is pending - continuing to health check")
                    else:
                        print("[OK] All steps completed successfully!")
                        self.checkpointer.emit_event(
                            self.run_id, "RUN_COMPLETED",
                            details={"reason": "llm_signaled_done"}
                        )
                        self.checkpointer.complete_run(self.run_id)
                        
                        return {
                            "status": "COMPLETED",
                            "iterations": iteration,
                            "summary": "Asset synchronization completed"
                        }
                
                success, result = self.execute_action(action, parameters, reasoning)
                
                if not success:
                    print(f"[FAIL] {action}: {result.get('error', 'Unknown error')}")
                    
                    # Surface granular sub-task status (Upgrade 1)
                    # A timeout is not a hard failure - the sub-task may be UNKNOWN
                    # (the write might have committed server-side).
                    sub_tasks = self.checkpointer.get_sub_tasks(self.run_id, action)
                    if sub_tasks:
                        print(f"  [SUBTASKS] {action}:")
                        for st in sub_tasks:
                            marker = {"SUCCESS": "OK", "FAILED": "FAIL",
                                      "UNKNOWN": "UNKNOWN"}.get(st["status"], st["status"])
                            tx = f" (tx={st['tx_id']})" if st.get("tx_id") else ""
                            print(f"    - {st['sub_task_name']}: [{marker}]{tx}")
                    
                    # Track the failed action for intelligent recovery
                    last_failed_action = action
                    
                    # Force check_system_health on next iteration instead of blind retry
                    self._force_health_check = True
                    
                    # If we keep failing the same action after health check, mark as FAILED
                    if iteration >= MAX_ITERATIONS - 1:
                        print("[WARN] Approaching max iterations - marking run as FAILED")
                        self.checkpointer.emit_event(
                            self.run_id, "RUN_FAILED",
                            details={"reason": "max_iterations", "failed_action": action}
                        )
                        self.checkpointer.fail_run(self.run_id, "Max iterations reached")
                        return {
                            "status": "FAILED",
                            "iterations": iteration,
                            "summary": f"Failed after {iteration} iterations"
                        }
                
            except Exception as e:
                print(f"[ERROR] Error in execution loop: {e}")
                self.checkpointer.emit_event(
                    self.run_id, "RUN_FAILED",
                    details={"reason": "exception", "error": str(e)}
                )
                self.checkpointer.fail_run(self.run_id, str(e))
                return {
                    "status": "ERROR",
                    "iterations": iteration,
                    "summary": f"Error: {str(e)}"
                }
        
        # Max iterations reached
        print(f"\n[WARN] Reached max iterations ({MAX_ITERATIONS})")
        self.checkpointer.emit_event(
            self.run_id, "RUN_FAILED",
            details={"reason": "max_iterations_exceeded"}
        )
        self.checkpointer.fail_run(self.run_id, "Max iterations exceeded")
        return {
            "status": "FAILED",
            "iterations": iteration,
            "summary": f"Failed after {iteration} iterations"
        }
