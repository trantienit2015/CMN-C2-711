"""AgentCore Platform v1.0 - CMN-C2-711 InputParseNode (inner node, Step 2).

Deterministic parse by log_format (hermes|n8n|temporal|airflow|generic-json)
into normalised run records. Inner subgraph only sees `user_input` (the
GraphNode subgraph boundary); the outer
InputValidateNode re-encodes {log_format, raw_export, time_range_hours} as a
JSON envelope so this node can recover all three.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.service import parse_export


class InputParseNode(FunctionNode):
    """Parse the validated export envelope into normalised run records."""

    # S-1: inner subgraph node - trust authenticated once at the outer backbone
    # (InputValidateNode, required_trust_level: INTERNAL).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # S-4: emit before the first validation guard so every path
        # (including the early-return rejects below) is traced, not just success.
        emit_trace_event(
            "input_parse_invoked",
            {"correlation_id": state.get("correlation_id")},
            state,
        )

        envelope = from_json(state.get("user_input"), None)
        if not isinstance(envelope, dict):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["InputParseNode: envelope missing or malformed - upstream not trusted blindly"],
            }

        log_format = envelope.get("log_format", "generic-json")
        raw_export = envelope.get("raw_export")
        records = parse_export(raw_export, log_format)

        if not records:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["InputParseNode: no run records parsed from export"],
            }

        emit_trace_event(
            "run_log_parsed",
            {"correlation_id": state.get("correlation_id"), "record_count": len(records), "log_format": log_format},
            state,
        )

        return {
            "run_records": to_json(records),
            "log_format": log_format,
            "time_range_hours": envelope.get("time_range_hours", 24),
            "status": AgentStatus.SUCCESS.value,
        }
