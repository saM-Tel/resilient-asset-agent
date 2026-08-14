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
                idempotency_key TEXT,
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
        
        # Sub-tasks table - tracks granular sub-task status within a step (Upgrade 1)
        # A step like write_db_correction can have sub-tasks (database_write,
        # cache_invalidation) each with their own SUCCESS/FAILED/UNKNOWN status.
        # UNKNOWN means the outcome is indeterminate (e.g. network timeout after
        # the write may have committed server-side).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sub_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                step_name TEXT NOT NULL,
                sub_task_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                tx_id TEXT,
                idempotency_key TEXT,
                error_message TEXT,
                timestamp REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
        """)
        
        # Events table - append-only audit trail / mission log (Upgrade 2)
        # Every meaningful transition (step start, sub-task commit, network
        # timeout, reconciliation) is appended here as an immutable record.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                event TEXT NOT NULL,
                sub_task TEXT,
                tx_id TEXT,
                details TEXT,
                timestamp REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
        """)
        
        # Indexes for fast per-run lookups (audit trail is read-mostly)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_steps_run ON steps(run_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subtasks_run ON sub_tasks(run_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id)")
        
        # Migration: add idempotency_key column to steps if missing (Upgrade 3)
        # CREATE TABLE IF NOT EXISTS won't add columns to an existing table,
        # so we check and ALTER if needed.
        cursor.execute("PRAGMA table_info(steps)")
        columns = [row[1] for row in cursor.fetchall()]
        if "idempotency_key" not in columns:
            cursor.execute("ALTER TABLE steps ADD COLUMN idempotency_key TEXT")
        
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
        
        # Delete all sub-tasks for this run (Upgrade 1)
        cursor.execute("DELETE FROM sub_tasks WHERE run_id = ?", (run_id,))
        
        # Delete all events for this run (Upgrade 2)
        cursor.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
        
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
                  error_message: str = None, idempotency_key: str = None) -> int:
        """
        Save the result of a step execution.
        
        Args:
            run_id: Execution run identifier
            step_name: Name of the step (e.g., 'fetch_location')
            step_order: Order number for sequencing
            status: 'COMPLETED', 'FAILED', 'PARTIAL_FAILURE', or 'PENDING'
            input_data: Input passed to the step
            output_data: Output from successful execution
            error_message: Error description if failed
            idempotency_key: Key for mutation deduplication (Upgrade 3)
            
        Returns:
            Step ID for reference
        """
        cursor = self.conn.cursor()
        now = time.time()
        
        cursor.execute("""
            INSERT INTO steps (run_id, step_name, step_order, status, 
                             input_data, output_data, error_message, idempotency_key,
                             started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, step_name, step_order, status,
            json.dumps(input_data) if input_data else None,
            json.dumps(output_data) if output_data else None,
            error_message,
            idempotency_key,
            now,
            now if status in ('COMPLETED', 'FAILED', 'PARTIAL_FAILURE') else None
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
    
    def get_partial_steps(self, run_id: str) -> list[dict]:
        """
        Get all steps in PARTIAL_FAILURE state for a run.
        
        A partial failure means the mutation likely succeeded server-side but
        the response was incomplete (e.g. DB write committed but the ack was
        dropped). These steps should NOT be retried - the agent should proceed
        to the next step, since re-executing would be a duplicate write.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT step_name, input_data, output_data, error_message, completed_at
            FROM steps 
            WHERE run_id = ? AND status = 'PARTIAL_FAILURE'
            ORDER BY step_order
        """, (run_id,))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'step_name': row[0],
                'input_data': json.loads(row[1]) if row[1] else None,
                'output_data': json.loads(row[2]) if row[2] else None,
                'error_message': row[3],
                'completed_at': row[4]
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
        """Get the full execution trace for a run, including sub-task status."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT step_name, step_order, status, input_data, output_data, 
                   error_message, idempotency_key, started_at, completed_at
            FROM steps 
            WHERE run_id = ?
            ORDER BY step_order
        """, (run_id,))
        
        # Load sub-tasks grouped by step for granular status (Upgrade 1)
        sub_tasks_by_step = self._load_sub_tasks_by_step(run_id)
        
        results = []
        for row in cursor.fetchall():
            entry = {
                'step_name': row[0],
                'step_order': row[1],
                'status': row[2],
                'started_at': row[7],
                'completed_at': row[8]
            }
            if row[3]:
                entry['input_data'] = json.loads(row[3])
            if row[4]:
                entry['output_data'] = json.loads(row[4])
            if row[5]:
                entry['error_message'] = row[5]
            if row[6]:
                entry['idempotency_key'] = row[6]
            # Attach granular sub-task status (Upgrade 1)
            if row[0] in sub_tasks_by_step:
                entry['sub_tasks'] = sub_tasks_by_step[row[0]]
            results.append(entry)
        return results
    
    def _load_sub_tasks_by_step(self, run_id: str) -> dict[str, dict]:
        """Load sub-task status grouped by step name for a run."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT step_name, sub_task_name, status, tx_id, error_message
            FROM sub_tasks
            WHERE run_id = ?
            ORDER BY id
        """, (run_id,))
        
        grouped: dict[str, dict] = {}
        for row in cursor.fetchall():
            step_name, sub_task_name, status, tx_id, error = row
            grouped.setdefault(step_name, {})[sub_task_name] = {
                'status': status,
                'tx_id': tx_id,
                'error': error
            }
        return grouped
    
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
    
    # =========================================================================
    # Upgrade 1: Sub-Task Granularity
    # =========================================================================
    
    def save_sub_task(self, run_id: str, step_name: str, sub_task_name: str,
                      status: str, tx_id: str = None, idempotency_key: str = None,
                      error_message: str = None) -> int:
        """
        Record the status of a granular sub-task within a step.
        
        Sub-tasks allow a step to report PARTIAL_FAILURE with per-component
        status. For example, a cache timeout marks cache_invalidation as
        UNKNOWN (the write may have committed server-side) rather than FAILED.
        
        Args:
            run_id: Execution run identifier
            step_name: Parent step name
            sub_task_name: Name of the sub-task (e.g., 'database_write')
            status: 'SUCCESS', 'FAILED', 'UNKNOWN', or 'PENDING'
            tx_id: Transaction ID if the sub-task committed
            idempotency_key: Key for mutation deduplication (Upgrade 3)
            error_message: Error description if failed/unknown
            
        Returns:
            Sub-task ID for reference
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO sub_tasks (run_id, step_name, sub_task_name, status,
                                  tx_id, idempotency_key, error_message, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, step_name, sub_task_name, status,
            tx_id, idempotency_key, error_message, time.time()
        ))
        self.conn.commit()
        return cursor.lastrowid
    
    def get_sub_tasks(self, run_id: str, step_name: str = None) -> list[dict]:
        """Get sub-task records for a run, optionally filtered by step name."""
        cursor = self.conn.cursor()
        if step_name:
            cursor.execute("""
                SELECT step_name, sub_task_name, status, tx_id, idempotency_key,
                       error_message, timestamp
                FROM sub_tasks
                WHERE run_id = ? AND step_name = ?
                ORDER BY id
            """, (run_id, step_name))
        else:
            cursor.execute("""
                SELECT step_name, sub_task_name, status, tx_id, idempotency_key,
                       error_message, timestamp
                FROM sub_tasks
                WHERE run_id = ?
                ORDER BY id
            """, (run_id,))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'step_name': row[0],
                'sub_task_name': row[1],
                'status': row[2],
                'tx_id': row[3],
                'idempotency_key': row[4],
                'error_message': row[5],
                'timestamp': row[6]
            })
        return results
    
    # =========================================================================
    # Upgrade 2: Append-Only Event Log (Audit Trail)
    # =========================================================================
    
    def emit_event(self, run_id: str, event: str, sub_task: str = None,
                   tx_id: str = None, details: dict = None) -> int:
        """
        Append an immutable event to the audit trail / mission log.
        
        This is the append-only event stream that records every meaningful
        transition: step starts, sub-task commits, network timeouts, and
        reconciliation actions. Events are never updated or deleted (except
        when a run is explicitly cleared for re-execution).
        
        Args:
            run_id: Execution run identifier
            event: Event type (e.g., 'STEP_STARTED', 'SUBTASK_COMMITTED',
                   'NETWORK_TIMEOUT', 'RECONCILIATION_STARTED')
            sub_task: Sub-task the event relates to (optional)
            tx_id: Transaction ID if applicable (optional)
            details: Arbitrary structured payload (optional)
            
        Returns:
            Event ID for reference
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO events (run_id, event, sub_task, tx_id, details, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            run_id, event, sub_task, tx_id,
            json.dumps(details) if details else None,
            time.time()
        ))
        self.conn.commit()
        return cursor.lastrowid
    
    def get_events(self, run_id: str) -> list[dict]:
        """Get the full append-only event log for a run, in chronological order."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT event, sub_task, tx_id, details, timestamp
            FROM events
            WHERE run_id = ?
            ORDER BY id
        """, (run_id,))
        
        results = []
        for row in cursor.fetchall():
            entry = {
                'event': row[0],
                'sub_task': row[1],
                'tx_id': row[2],
                'timestamp': row[4]
            }
            if row[3]:
                entry['details'] = json.loads(row[3])
            results.append(entry)
        return results
    
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
