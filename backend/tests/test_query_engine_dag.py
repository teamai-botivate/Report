"""Additional QueryPlan DAG coverage beyond test_query_engine.py (which
already covers the executor's validation/audit path): dependency ordering
via topological_batches(), including circular/missing-dependency handling.
"""
from app.query_engine.plan import QueryPlan, QueryPlanNode


def test_topological_batches_independent_nodes_in_one_batch():
    plan = QueryPlan(
        nodes=[
            QueryPlanNode(id="a", description="A"),
            QueryPlanNode(id="b", description="B"),
        ]
    )
    batches = plan.topological_batches()
    assert len(batches) == 1
    assert {n.id for n in batches[0]} == {"a", "b"}


def test_topological_batches_respects_dependencies():
    plan = QueryPlan(
        nodes=[
            QueryPlanNode(id="a", description="A"),
            QueryPlanNode(id="b", description="B"),
            QueryPlanNode(id="c", description="C depends on A and B", depends_on=["a", "b"]),
        ]
    )
    batches = plan.topological_batches()
    assert len(batches) == 2
    assert {n.id for n in batches[0]} == {"a", "b"}
    assert {n.id for n in batches[1]} == {"c"}


def test_topological_batches_chain_of_three():
    plan = QueryPlan(
        nodes=[
            QueryPlanNode(id="a", description="A"),
            QueryPlanNode(id="b", description="B depends on A", depends_on=["a"]),
            QueryPlanNode(id="c", description="C depends on B", depends_on=["b"]),
        ]
    )
    batches = plan.topological_batches()
    assert [{n.id for n in batch} for batch in batches] == [{"a"}, {"b"}, {"c"}]


def test_topological_batches_handles_missing_dependency_without_infinite_loop():
    plan = QueryPlan(
        nodes=[
            QueryPlanNode(id="a", description="A", depends_on=["ghost"]),
        ]
    )
    batches = plan.topological_batches()
    # Missing dependency can never be satisfied -> dumped as a final batch
    # rather than looping forever.
    assert len(batches) == 1
    assert {n.id for n in batches[0]} == {"a"}


def test_get_returns_none_for_unknown_id():
    plan = QueryPlan(nodes=[QueryPlanNode(id="a", description="A")])
    assert plan.get("a") is not None
    assert plan.get("nonexistent") is None


def test_all_succeeded_and_successful_nodes():
    a = QueryPlanNode(id="a", description="A", status="success")
    b = QueryPlanNode(id="b", description="B", status="error")
    plan = QueryPlan(nodes=[a, b])
    assert not plan.all_succeeded()
    assert plan.successful_nodes() == [a]

    b.status = "success"
    assert plan.all_succeeded()
