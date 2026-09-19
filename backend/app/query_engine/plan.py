"""Query Plan DAG data structures.

A user turn may require multiple SQL queries, some independent (run in parallel),
some dependent on an earlier node's result (e.g. "growth vs last month" needs both
months' totals before computing a delta). This module defines the plan shape; the
executor in executor.py walks it respecting dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

NodeStatus = Literal["pending", "running", "success", "error", "skipped"]


@dataclass
class QueryPlanNode:
    id: str
    description: str
    """Plain-English description of what this node computes, e.g. 'September revenue'."""
    depends_on: list[str] = field(default_factory=list)
    sql: str | None = None
    """Filled in by the SQL Generation Agent for this node."""
    status: NodeStatus = "pending"
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    elapsed_ms: float = 0.0
    error: str | None = None
    retry_count: int = 0
    tables_referenced: list[str] = field(default_factory=list)


@dataclass
class QueryPlan:
    nodes: list[QueryPlanNode] = field(default_factory=list)

    def get(self, node_id: str) -> QueryPlanNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def topological_batches(self) -> list[list[QueryPlanNode]]:
        """Group nodes into batches that can run in parallel, respecting dependencies."""
        remaining = {n.id: n for n in self.nodes}
        done: set[str] = set()
        batches: list[list[QueryPlanNode]] = []

        while remaining:
            ready = [n for n in remaining.values() if all(dep in done for dep in n.depends_on)]
            if not ready:
                # Circular or missing dependency — dump the rest as a final batch to
                # surface the error rather than looping forever.
                batches.append(list(remaining.values()))
                break
            batches.append(ready)
            for n in ready:
                done.add(n.id)
                del remaining[n.id]
        return batches

    def all_succeeded(self) -> bool:
        return all(n.status == "success" for n in self.nodes)

    def successful_nodes(self) -> list[QueryPlanNode]:
        return [n for n in self.nodes if n.status == "success"]
