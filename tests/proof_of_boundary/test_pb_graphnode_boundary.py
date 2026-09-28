"""GraphNode boundary test (CMN-C2-711) — outer ``main`` slot.

PB-6 (``test_pb_invoke_order.py``) only discovers ``BaseNode`` subclasses under
``src/nodes/`` and excludes ``GraphNode`` there. The Cat 2
``ScheduledAutomationDigestGraphNode`` wrapper is registered on the outer
graph's ``main`` slot in ``src/graph/graph.py`` (scaffold-canonical placement,
avoids a single-node probe pulling in the whole inner subgraph) — but that
placement does not exempt it from boundary testing. This file is the required
boundary probe for that gap.
"""
from __future__ import annotations

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import ScheduledAutomationDigestGraphNode
from src.nodes.input_parse_node import InputParseNode


def test_s1_trust_gate_denies_low_trust_before_subgraph_runs():
    """S-1: BaseNode.__call__() reads caller_trust_level from state and denies
    before execute()/get_subgraph() runs — no inner subgraph invocation happens."""
    node = ScheduledAutomationDigestGraphNode()
    state = {"caller_trust_level": TrustLevel.ANONYMOUS.value, "user_input": "{}"}
    result = node(state)
    assert result["status"] == AgentStatus.ERROR.value
    assert any("S-1 trust gate denied" in msg for msg in result["error_log"])


def test_extract_input_only_reads_validated_input_contract_fields():
    """Boundary mapping: extract_input() reads only validated_input (falling
    back to user_input) — no other outer-state field leaks into the inner
    graph's single string input (framework graph_node.py contract)."""
    node = ScheduledAutomationDigestGraphNode()
    state = {
        "validated_input": '{"log_format": "generic-json", "raw_export": []}',
        "user_input": "should-not-be-used",
        "some_unrelated_secret": "must-not-leak",
        "status": AgentStatus.SUCCESS.value,
    }
    result = node.extract_input(state)
    assert result == '{"log_format": "generic-json", "raw_export": []}'
    assert "must-not-leak" not in result


def test_extract_input_dispatches_empty_string_when_outer_validation_failed():
    """AgentBaseGraph wires pre_process -> main as an UNCONDITIONAL edge, so a
    pre_process ERROR does not stop this GraphNode from being invoked.
    extract_input() must fail closed (dispatch "") instead of falling back to
    the caller's raw, unvalidated user_input."""
    node = ScheduledAutomationDigestGraphNode()
    state = {
        "status": AgentStatus.ERROR.value,
        "user_input": '{"log_format": "generic-json", "raw_export": ["malicious"]}',
    }
    result = node.extract_input(state)
    assert result == ""


def test_merge_output_maps_fields_explicitly_no_raw_passthrough():
    """Boundary mapping: merge_output() maps a fixed, named set of fields —
    an unexpected key in sub_result must NOT leak into the outer state
    (criterion #9 — no raw pass-through of the subgraph result dict)."""
    node = ScheduledAutomationDigestGraphNode()
    sub_result = {
        "run_records": "[]",
        "status_counts": "{}",
        "failure_summaries": "[]",
        "next_scheduled_runs": "[]",
        "digest_markdown": "# digest",
        "status": AgentStatus.SUCCESS.value,
        "unexpected_internal_field": "must-not-leak",
    }
    merged = node.merge_output({}, sub_result)
    assert "unexpected_internal_field" not in merged
    assert merged["digest_markdown"] == "# digest"
    assert merged["status"] == AgentStatus.SUCCESS.value


def test_inner_entry_node_carries_its_own_s1_s2_gates():
    """Delegation is intentional, not a gap: GraphNode.__call__() runs its own
    S-1 gate (see test above) and delegates content gating to the inner
    subgraph's own entry node (framework/nodes/graph_node.py contract) — the
    inner entry node (InputParseNode) still declares its own trust level
    explicitly rather than relying on an implicit default."""
    assert InputParseNode.required_trust_level == TrustLevel.ANONYMOUS
