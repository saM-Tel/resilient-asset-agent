"""
Agent package for the Resilient Asset Agent.

Contains:
- checkpointer.py: SQLite-based state persistence with idempotency guarantees
- tools.py: Idempotent tool wrappers around mock services
- runner.py: LLM-driven agent control loop with dynamic decision-making
"""

from agent.checkpointer import Checkpointer

__all__ = ["Checkpointer"]


def __getattr__(name):
    """Lazy-load AssetSyncAgent only when actually imported (avoids openai requirement in test env)."""
    if name == "AssetSyncAgent":
        from agent.runner import AssetSyncAgent
        return AssetSyncAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
