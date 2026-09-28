"""AgentCore Platform v1.0 - CMN-C2-711 outer graph (Cat 2).

Cat 2: outer AgentBaseGraph with the fixed 5-node backbone. Domain
complexity (parse -> classify -> LLM failure-analyze -> next-run-extract
-> LLM digest-generate) is encapsulated in ScheduledAutomationDigestGraphNode
(the `main` slot), which wraps the inner
ScheduledAutomationWorkflowGraph. Do NOT override add_edges().

Backbone: initialize -> pre_process(InputValidate) -> main(GraphNode)
          -> post_process(OutputValidate) -> finalize

ScheduledAutomationDigestGraphNode lives here (not under src/nodes/) - the
PB-6 invoke-order test only discovers BaseNode subclasses under src/nodes/,
and a GraphNode's __call__ intentionally skips the standard
S-2/S-4/S-3 lifecycle (gating is delegated to the inner subgraph).
"""

from typing import Any, ClassVar, cast

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.input_validate_node import InputValidateNode
from src.nodes.output_validate_node import OutputValidateNode
from src.schemas.state import State

DEFAULT_FAILURE_ALERT_THRESHOLD = 1


class ScheduledAutomationDigestGraphNode(GraphNode):
    """Wraps the inner scheduled-automation health-digest workflow (Cat 2 composition)."""

    # S-1: outer main-slot wrapper - first node in the outer backbone
    # to receive caller input. Matches config/agent.yaml required_trust_level and
    # the sibling outer nodes (InputValidateNode / OutputValidateNode).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL
    # "propagate": re-raise inner errors as SubgraphError (fail fast - default).
    error_strategy: ClassVar[str] = "propagate"
    # No HITL in this template.
    propagate_hitl: ClassVar[bool] = False

    def __init__(self, llm: Any = None, failure_alert_threshold: int = DEFAULT_FAILURE_ALERT_THRESHOLD):
        super().__init__()
        self._llm = llm
        self._failure_alert_threshold = failure_alert_threshold

    def get_subgraph(self) -> Any:
        from src.graph.domain_workflow_graph import ScheduledAutomationWorkflowGraph

        sg = ScheduledAutomationWorkflowGraph(config=self._parent_config())
        sg.compile()
        return sg

    def extract_input(self, state: AgentState) -> str:
        # S-4: runs inside GraphNode.execute() - audit the dispatch into the inner subgraph.
        emit_trace_event(
            "scheduled_automation_workflow_dispatched",
            {"correlation_id": state.get("correlation_id", "")},
            state,
        )
        # AgentBaseGraph wires pre_process -> main as an UNCONDITIONAL edge (routing
        # only happens after `main`, via route(state) reading the post-main status) -
        # so InputValidateNode returning ERROR does NOT stop this GraphNode from
        # being invoked. Without this guard, extract_input() would fall back to the
        # caller's raw (unvalidated) user_input and the inner subgraph could still
        # succeed on stale/rejected data. Dispatch "" instead so InputParseNode's
        # envelope parse fails closed, matching the outer InputValidateNode verdict.
        if state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value):
            return ""
        return cast(str, state.get("validated_input", state.get("user_input", "")))

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        # S-4: runs inside GraphNode.execute() - audit the subgraph outcome merged back out.
        emit_trace_event(
            "scheduled_automation_workflow_completed",
            {"correlation_id": state.get("correlation_id", ""), "status": str(sub_result.get("status"))},
            state,
        )
        return {
            "run_records": sub_result.get("run_records"),
            "status_counts": sub_result.get("status_counts"),
            "failure_summaries": sub_result.get("failure_summaries"),
            "next_scheduled_runs": sub_result.get("next_scheduled_runs"),
            "digest_markdown": sub_result.get("digest_markdown"),
            "status": sub_result.get("status"),
        }

    def _parent_config(self) -> dict[str, Any]:
        return {"llm": self._llm, "failure_alert_threshold": self._failure_alert_threshold}


class CMNScheduledAutomationStatusReportAgent(AgentBaseGraph):
    """CMN-C2-711 - Enterprise Scheduled Agent Automation Status Report Agent (Cat 2)."""

    @property
    def name(self) -> str:
        return "cmn-c2-711"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects initialize + finalize

        llm = self.config.get("llm") if hasattr(self, "config") else None
        threshold = (
            self.config.get("failure_alert_threshold", DEFAULT_FAILURE_ALERT_THRESHOLD)
            if hasattr(self, "config")
            else DEFAULT_FAILURE_ALERT_THRESHOLD
        )

        self._nodes["pre_process"] = InputValidateNode()
        self._nodes["main"] = ScheduledAutomationDigestGraphNode(llm=llm, failure_alert_threshold=threshold)
        self._nodes["post_process"] = OutputValidateNode()

    # add_edges() is NOT overridden - backbone wiring belongs to the framework.


# Alias for agent.yaml module:"src.graph" resolution (AgentRegistry / api/server.py).
Graph = CMNScheduledAutomationStatusReportAgent
