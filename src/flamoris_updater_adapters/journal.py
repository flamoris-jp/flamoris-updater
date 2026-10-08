"""Compatibility import for the shared MCP-independent durable journal."""

from flamoris_update_core.journal import (
    Journal,
    durable_write,
    exclusive,
    inspect_journal,
    protected_dir,
)

__all__ = ["Journal", "inspect_journal", "durable_write", "exclusive", "protected_dir"]
