"""AgentCore Platform v1.0 - CMN-C2-711 inner domain workflow graph.

Cat 2 inner graph: parse -> classify -> LLM failure-analyze -> next-run
extract -> LLM digest-generate. Instantiated by
ScheduledAutomationDigestGraphNode.get_subgraph() in graph.py.

Pipeline (linear, fail-fast on ERROR):
    START -> input_parse -> status_classify -> failure_analyze
          -> next_run_extract -> digest_generate -> END
"""

from typing import Any
from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

from src.nodes.digest_generate_node import DigestGenerateNode
from src.nodes.failure_analyze_node import FailureAnalyzeNode
from src.nodes.input_parse_node import InputParseNode
from src.nodes.next_run_extract_node import NextRunExtractNode
from src.nodes.status_classify_node import StatusClassifyNode
from src.schemas.state import State


class ScheduledAutomationWorkflowGraph(BaseGraph):
    """Inner graph for the CMN-C2-711 scheduled-automation health-digest workflow."""

    @property
    def name(self) -> str:
        return "scheduled-automation-workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        # No mandatory config - llm/failure_alert_threshold are both optional.
        pass

    def register_nodes(self) -> None:
        # No super() - BaseGraph.register_nodes() is abstract.
        llm = self.config.get("llm") if hasattr(self, "config") else None
        threshold = self.config.get("failure_alert_threshold", 1) if hasattr(self, "config") else 1

        self._nodes["input_parse"] = InputParseNode()
        self._nodes["status_classify"] = StatusClassifyNode()
        self._nodes["failure_analyze"] = FailureAnalyzeNode(llm=llm)
        self._nodes["next_run_extract"] = NextRunExtractNode()
        self._nodes["digest_generate"] = DigestGenerateNode(llm=llm, failure_alert_threshold=threshold)

    def add_edges(self) -> None:
        self._sg.add_edge(START, "input_parse")
        self._sg.add_conditional_edges(
            "input_parse",
            lambda s: END if self._is_error(s) else "status_classify",
            {"status_classify": "status_classify", END: END},
        )
        self._sg.add_conditional_edges(
            "status_classify",
            lambda s: END if self._is_error(s) else "failure_analyze",
            {"failure_analyze": "failure_analyze", END: END},
        )
        self._sg.add_conditional_edges(
            "failure_analyze",
            lambda s: END if self._is_error(s) else "next_run_extract",
            {"next_run_extract": "next_run_extract", END: END},
        )
        self._sg.add_conditional_edges(
            "next_run_extract",
            lambda s: END if self._is_error(s) else "digest_generate",
            {"digest_generate": "digest_generate", END: END},
        )
        self._sg.add_edge("digest_generate", END)

    @staticmethod
    def _is_error(state: AgentState) -> bool:
        return state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value)

    def route(self, state: AgentState) -> str:  # required by ABC (linear pipeline -> not called)
        return END if self._is_error(state) else "status_classify"

    def get_output(self, state: AgentState) -> dict[str, Any]:
        return {
            "run_records": state.get("run_records"),
            "status_counts": state.get("status_counts"),
            "failure_summaries": state.get("failure_summaries"),
            "next_scheduled_runs": state.get("next_scheduled_runs"),
            "digest_markdown": state.get("digest_markdown"),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
