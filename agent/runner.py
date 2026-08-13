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

RULES:
- Never repeat completed steps
- Return ONLY valid JSON: {"action": "...", "reasoning": "...", "parameters": {...}}
- Use "DONE" when all steps complete
- Be brief and respond immediately
- If unsure, choose fetch_location"""
        
        # Build execution history summary (brief format)
        completed_names = [s["step_name"] for s in context["completed_steps"]]
        failed_names = [s["step_name"] for s in context["failed_steps"]]
        
        user_message = f"""Completed: {completed_names}
Failed: {failed_names}

Decide next action. Return JSON only."""
        
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
    
    def parse_llm_response(self, response_content: str) -> dict:
        """
        Parse the LLM's JSON response into a decision.
        
        Args:
            response_content: Raw text from LLM response
            
        Returns:
            Dictionary with action, reasoning, and parameters
        """
        # Clean up the response
        content = response_content.strip()
        
        # Handle empty response
        if not content:
            print("[WARN] LLM returned empty response, requesting asset fetch")
            return {
                "action": "fetch_location",
                "reasoning": "Empty response from LLM, starting with location fetch",
                "parameters": {"asset_id": "asset_001"}
            }
        
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
        
        # Try to parse JSON
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"[WARN] Failed to parse JSON: {e}")
            print(f"[WARN] Response content: {content[:100]}...")
            # Fallback to fetch_location on parse failure
            return {
                "action": "fetch_location",
                "reasoning": f"Failed to parse LLM response: {str(e)}",
                "parameters": {"asset_id": "asset_001"}
            }
    
    def execute_action(self, action: str, parameters: dict = None) -> tuple[bool, dict]:
        """
        Execute the LLM's chosen action through the appropriate tool.
        
        Args:
            action: Tool name to execute
            parameters: Parameters for the tool call
            
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
        
        else:
            return False, {"error": f"Unknown action: {action}"}
    
    def run(self):
        """
        Main execution loop - runs until all steps complete or max iterations reached.
        
        Returns:
            Dictionary with final execution summary
        """
        MAX_ITERATIONS = 10
        iteration = 0
        empty_responses = 0  # Track consecutive empty responses
        
        print(f"\n{'='*60}")
        print(f"Starting Asset Sync Agent - Run ID: {self.run_id}")
        print(f"{'='*60}\n")
        
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
                
                # Parse decision
                decision = self.parse_llm_response(response_content)
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
                
                success, result = self.execute_action(action, parameters)
                
                if not success:
                    print(f"[WARN] Action failed: {result.get('error', 'Unknown error')}")
                    
                    # If we keep failing the same action, try recovery
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
