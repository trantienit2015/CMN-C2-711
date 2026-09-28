"""AgentCore Platform v1.0 - CMN-C2-711 NextRunExtractNode (inner node, Step 5).

Deterministic extraction of upcoming scheduled run windows from
next_scheduled_at, within the caller's time-range filter.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.service import extract_next_runs


class NextRunExtractNode(FunctionNode):
    """Extract upcoming scheduled run windows from the classified run records."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # S-4: emit before the first validation guard so every path
        # (including the early-return reject below) is traced, not just success.
        emit_trace_event(
            "next_run_extract_invoked",
            {"correlation_id": state.get("correlation_id")},
            state,
        )

        records = from_json(state.get("run_records"), None)
        if records is None:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["NextRunExtractNode: run_records missing - upstream not trusted blindly"],
            }

        time_range_hours = state.get("time_range_hours", 24)
        next_runs = extract_next_runs(records, time_range_hours)

        emit_trace_event(
            "next_runs_extracted",
            {"correlation_id": state.get("correlation_id"), "next_run_count": len(next_runs)},
            state,
        )

        return {
            "next_scheduled_runs": to_json(next_runs),
            "status": AgentStatus.SUCCESS.value,
        }
