"""
Checkpoint persistence layer for the resilient asset agent.

Provides SQLite-based state tracking with idempotency guarantees:
- Logs every step execution (start, completion, failure)
- Prevents re-execution of completed steps
- Enables intelligent recovery from partial failures
- Maintains full execution trace for audit/debugging

Uses SQLite for durability - survives process crashes and enables
resumption across multiple runs.
"""

import sqlite3
import json
import time
from pathlib import Path
from typing import Any, Optional


class Checkpointer:
    """
    Persistent checkpoint store using SQLite.
    
    Tracks execution state per run_id to enable:
    1. Idempotent step execution (skip if already completed)
    2. Intelligent recovery from failures
    3. Full audit trail of all decisions and outcomes
    """
    
    def __init__(self, db_path: str = "agent_state.db"):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self._create_tables()
    
    def _create_tables(self):
        """Create SQLite tables if they don't exist."""
        cursor = self.conn.cursor()
        
        # Runs table - tracks overall execution status
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
                created_at REAL NOT NULL,
                completed_at REAL
            )
        """)
        
        # Steps table - tracks individual step execution
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                step_name TEXT NOT NULL,
                step_order INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                input_data TEXT,
                output_data TEXT,
                error_message TEXT,
                started_at REAL NOT NULL,
                completed_at REAL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
        """)
        
        # Decisions table - tracks LLM reasoning
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                step_name TEXT NOT NULL,
                reasoning TEXT NOT NULL,
                next_action TEXT NOT NULL,
                timestamp REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
        """)
        
        self.conn.commit()
    
    def clear_run(self, run_id: str) -> None:
        """
        Clear all data for a specific run_id.
        
        Called when re-running with the same ID to give a clean slate.
        Removes steps and decisions but keeps the run record.
        """
        cursor = self.conn.cursor()
        
        # Delete all steps for this run
        cursor.execute("DELETE FROM steps WHERE run_id = ?", (run_id,))
        
        # Delete all decisions for this run
        cursor.execute("DELETE FROM decisions WHERE run_id = ?", (run_id,))
        
        # Reset run status to IN_PROGRESS with new timestamp
        cursor.execute(
            "UPDATE runs SET status = 'IN_PROGRESS', created_at = ?, completed_at = NULL WHERE run_id = ?",
            (time.time(), run_id)
        )
        
        self.conn.commit()
    
    def create_run(self, run_id: str) -> None:
        """Create a new execution run."""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO runs (run_id, status, created_at) VALUES (?, ?, ?)",
            (run_id, 'IN_PROGRESS', time.time())
        )
        self.conn.commit()
    
    def complete_run(self, run_id: str) -> None:
        """Mark a run as completed."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE runs SET status = ?, completed_at = ? WHERE run_id = ?",
            ('COMPLETED', time.time(), run_id)
        )
        self.conn.commit()
    
    def fail_run(self, run_id: str, error: str) -> None:
        """Mark a run as failed."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE runs SET status = ?, completed_at = ? WHERE run_id = ?",
            ('FAILED', time.time(), run_id)
        )
        # Log the error in the last step if possible
        cursor.execute("""
            UPDATE steps SET status = 'FAILED', error_message = ?, 
                completed_at = ? 
            WHERE run_id = ? AND id = (SELECT MAX(id) FROM steps WHERE run_id = ?)
        """, (error, time.time(), run_id, run_id))
        self.conn.commit()
    
    def get_run_status(self, run_id: str) -> Optional[dict]:
        """Get the status of a specific run."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if row:
            return {
                'run_id': row[0],
                'status': row[1],
                'created_at': row[2],
                'completed_at': row[3]
            }
        return None
    
    def save_step(self, run_id: str, step_name: str, step_order: int, 
                  status: str, input_data: dict = None, output_data: dict = None,
                  error_message: str = None) -> int:
        """
        Save the result of a step execution.
        
        Args:
            run_id: Execution run identifier
            step_name: Name of the step (e.g., 'fetch_location')
            step_order: Order number for sequencing
            status: 'COMPLETED', 'FAILED', or 'PENDING'
            input_data: Input passed to the step
            output_data: Output from successful execution
            error_message: Error description if failed
            
        Returns:
            Step ID for reference
        """
        cursor = self.conn.cursor()
        now = time.time()
        
        cursor.execute("""
            INSERT INTO steps (run_id, step_name, step_order, status, 
                             input_data, output_data, error_message, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, step_name, step_order, status,
            json.dumps(input_data) if input_data else None,
            json.dumps(output_data) if output_data else None,
            error_message,
            now,
            now if status in ('COMPLETED', 'FAILED') else None
        ))
        
        self.conn.commit()
        return cursor.lastrowid
    
    def get_completed_steps(self, run_id: str) -> list[dict]:
        """Get all successfully completed steps for a run."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT step_name, input_data, output_data, completed_at
            FROM steps 
            WHERE run_id = ? AND status = 'COMPLETED'
            ORDER BY step_order
        """, (run_id,))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'step_name': row[0],
                'input_data': json.loads(row[1]) if row[1] else None,
                'output_data': json.loads(row[2]) if row[2] else None,
                'completed_at': row[3]
            })
        return results
    
    def get_failed_steps(self, run_id: str) -> list[dict]:
        """Get all failed steps for a run."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT step_name, input_data, error_message, completed_at
            FROM steps 
            WHERE run_id = ? AND status = 'FAILED'
            ORDER BY step_order
        """, (run_id,))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'step_name': row[0],
                'input_data': json.loads(row[1]) if row[1] else None,
                'error_message': row[2],
                'completed_at': row[3]
            })
        return results
    
    def get_pending_steps(self, run_id: str) -> list[dict]:
        """Get all steps that haven't been executed yet."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT step_name, step_order, input_data
            FROM steps 
            WHERE run_id = ? AND status = 'PENDING'
            ORDER BY step_order
        """, (run_id,))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'step_name': row[0],
                'step_order': row[1],
                'input_data': json.loads(row[2]) if row[2] else None
            })
        return results
    
    def get_execution_trace(self, run_id: str) -> list[dict]:
        """Get the full execution trace for a run."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT step_name, step_order, status, input_data, output_data, 
                   error_message, started_at, completed_at
            FROM steps 
            WHERE run_id = ?
            ORDER BY step_order
        """, (run_id,))
        
        results = []
        for row in cursor.fetchall():
            entry = {
                'step_name': row[0],
                'step_order': row[1],
                'status': row[2],
                'started_at': row[6],
                'completed_at': row[7]
            }
            if row[3]:
                entry['input_data'] = json.loads(row[3])
            if row[4]:
                entry['output_data'] = json.loads(row[4])
            if row[5]:
                entry['error_message'] = row[5]
            results.append(entry)
        return results
    
    def get_step_result(self, run_id: str, step_name: str) -> Optional[dict]:
        """Get the result of a specific step by name."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT status, input_data, output_data, error_message
            FROM steps 
            WHERE run_id = ? AND step_name = ?
            ORDER BY completed_at DESC
            LIMIT 1
        """, (run_id, step_name))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        result = {'status': row[0]}
        if row[1]:
            result['input_data'] = json.loads(row[1])
        if row[2]:
            result['output_data'] = json.loads(row[2])
        if row[3]:
            result['error_message'] = row[3]
        
        return result
    
    def save_decision(self, run_id: str, step_name: str, reasoning: str, 
                     next_action: str) -> None:
        """Save an LLM decision for audit trail."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO decisions (run_id, step_name, reasoning, next_action, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (run_id, step_name, reasoning, next_action, time.time()))
        self.conn.commit()
    
    def get_decisions(self, run_id: str) -> list[dict]:
        """Get all LLM decisions for a run."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT step_name, reasoning, next_action, timestamp
            FROM decisions 
            WHERE run_id = ?
            ORDER BY timestamp
        """, (run_id,))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'step_name': row[0],
                'reasoning': row[1],
                'next_action': row[2],
                'timestamp': row[3]
            })
        return results
    
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
    
    def __del__(self):
        """Ensure connection is closed on deletion."""
        try:
            self.close()
        except:
            pass
