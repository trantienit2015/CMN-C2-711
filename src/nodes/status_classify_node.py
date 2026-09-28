"""AgentCore Platform v1.0 - CMN-C2-711 StatusClassifyNode (inner node, Step 3).

Deterministic mapping of each run to success|failure|scheduled|pending;
tally counts per status.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.service import classify_status


class StatusClassifyNode(FunctionNode):
    """Classify every run record and tally per-status counts."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # S-4: emit before the first validation guard so every path
        # (including the early-return reject below) is traced, not just success.
        emit_trace_event(
            "status_classify_invoked",
            {"correlation_id": state.get("correlation_id")},
            state,
        )

        records = from_json(state.get("run_records"), None)
        if not records:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["StatusClassifyNode: run_records missing - upstream not trusted blindly"],
            }

        classified, counts = classify_status(records)

        emit_trace_event(
            "runs_classified",
            {"correlation_id": state.get("correlation_id"), **counts},
            state,
        )

        return {
            "run_records": to_json(classified),
            "status_counts": to_json(counts),
            "status": AgentStatus.SUCCESS.value,
        }
