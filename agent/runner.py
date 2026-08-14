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
        
        # Define available tools and their descriptions for the LLM
        self.tools = {
            "fetch_location": {
                "name": "fetch_location",
                "description": "Fetch current asset location from the location service. Returns coordinates, status, and staleness info.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "asset_id": {
                            "type": "string",
                            "description": "The asset identifier to query"
                        }
                    },
                    "required": ["asset_id"]
                }
            },
            "validate_consistency": {
                "name": "validate_consistency",
                "description": "Validate data consistency between current asset state and expected target. Returns discrepancies if any.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "asset_data": {
                            "type": "object",
                            "description": "Current asset location data from fetch_location"
                        }
                    },
                    "required": ["asset_data"]
                }
            },
            "write_db_correction": {
                "name": "write_db_correction",
                "description": "Write corrections to the asset database. Use when discrepancies are found that need fixing.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "correction_data": {
                            "type": "object",
                            "description": "Data to write: lat, lng, status"
                        }
                    },
                    "required": ["correction_data"]
                }
            },
            "update_cache": {
                "name": "update_cache",
                "description": "Update the distributed cache with latest asset state. Should be called after successful DB write.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cache_data": {
                            "type": "object",
                            "description": "Data to cache"
                        }
                    },
                    "required": ["cache_data"]
                }
            },
            "check_system_health": {
                "name": "check_system_health",
                "description": "Check health status of all distributed services (location, database, cache). Use this when a step fails to diagnose which service is down before deciding next action.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        }
    
    def get_execution_context(self) -> dict:
        """
        Build the current execution context from checkpoint store.
        
        Returns:
            Dictionary with run status, completed steps, failed steps, and pending steps
        """
        run_status = self.checkpointer.get_run_status(self.run_id)
        completed_steps = self.checkpointer.get_completed_steps(self.run_id)
        failed_steps = self.checkpointer.get_failed_steps(self.run_id)
        execution_trace = self.checkpointer.get_execution_trace(self.run_id)
        
        return {
            "run_id": self.run_id,
            "status": run_status["status"] if run_status else "UNKNOWN",
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
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

RULES:
- Never repeat completed steps
- Return ONLY valid JSON: {"action": "...", "reasoning": "...", "parameters": {...}}
- Use "DONE" when all steps complete
- Be brief and respond immediately"""
        
        # Build execution history summary (brief format)
        completed_names = [s["step_name"] for s in context["completed_steps"]]
        failed_names = [s["step_name"] for s in context["failed_steps"]]
        
        user_message = f"""Completed: {completed_names}
Failed: {failed_names}

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
            "reasoning": f"Failed to parse LLM response: {str(e) if 'e' in dir() else 'unknown'}",
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
            location_data = None
            for step in completed:
                if step["step_name"] == "fetch_location" and step["output_data"]:
                    location_data = step["output_data"]
                    break
            
            if not location_data:
                return False, {"error": "No location data available - must fetch first"}
            
            result = execute_validate_consistency(self.checkpointer, self.run_id, location_data)
            return result.success, result.to_dict()
        
        elif action == "write_db_correction":
            # Get location and validation data
            completed = self.checkpointer.get_completed_steps(self.run_id)
            location_data = None
            validation_data = None
            
            for step in completed:
                if step["step_name"] == "fetch_location" and step["output_data"]:
                    location_data = step["output_data"]
                elif step["step_name"] == "validate_consistency" and step["output_data"]:
                    validation_data = step["output_data"]
            
            if not location_data or not validation_data:
                return False, {"error": "Need location and validation data first"}
            
            # Check if already synced
            if validation_data.get("is_synced"):
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
            # Get latest data for caching
            completed = self.checkpointer.get_completed_steps(self.run_id)
            location_data = None
            
            for step in completed:
                if step["step_name"] == "fetch_location" and step["output_data"]:
                    location_data = step["output_data"]
                    break
            
            cache_data = location_data or {"status": "synced"}
            
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
        
        while iteration < MAX_ITERATIONS:
            iteration += 1
            print(f"\n--- Iteration {iteration} ---\n")
            
            # Get current state
            context = self.get_execution_context()
            
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
            
            # INTELLIGENT RECOVERY: If a step just failed, force check_system_health
            if self._force_health_check:
                print("[INFO] Step failed - forcing intelligent recovery via health check\n")
                
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
                    self.checkpointer.complete_run(self.run_id)
                    return {
                        "status": "COMPLETED",  # Intelligently halted, not failed
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
                    model="qwen3.6-35b",
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
                    print("[OK] All steps completed successfully!")
                    self.checkpointer.complete_run(self.run_id)
                    
                    return {
                        "status": "COMPLETED",
                        "iterations": iteration,
                        "summary": "Asset synchronization completed"
                    }
                
                success, result = self.execute_action(action, parameters, reasoning)
                
                if not success:
                    print(f"[FAIL] {action}: {result.get('error', 'Unknown error')}")
                    
                    # Track the failed action for intelligent recovery
                    last_failed_action = action
                    
                    # Force check_system_health on next iteration instead of blind retry
                    self._force_health_check = True
                    
                    # If we keep failing the same action after health check, mark as FAILED
                    if iteration >= MAX_ITERATIONS - 1:
                        print("[WARN] Approaching max iterations - marking run as FAILED")
                        self.checkpointer.fail_run(self.run_id, "Max iterations reached")
                        return {
                            "status": "FAILED",
                            "iterations": iteration,
                            "summary": f"Failed after {iteration} iterations"
                        }
                
            except Exception as e:
                print(f"[ERROR] Error in execution loop: {e}")
                self.checkpointer.fail_run(self.run_id, str(e))
                return {
                    "status": "ERROR",
                    "iterations": iteration,
                    "summary": f"Error: {str(e)}"
                }
        
        # Max iterations reached
        print(f"\n[WARN] Reached max iterations ({MAX_ITERATIONS})")
        self.checkpointer.fail_run(self.run_id, "Max iterations exceeded")
        return {
            "status": "FAILED",
            "iterations": iteration,
            "summary": f"Failed after {iteration} iterations"
        }
