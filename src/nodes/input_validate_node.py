"""AgentCore Platform v1.0 - CMN-C2-711 InputValidateNode (outer pre_process slot).

Step 1: S-1 trust gate (this node's required_trust_level
matches config/agent.yaml - IT-ops/DevOps callers only) + S-2 deterministic
input scan: validate the export payload shape / declared log_format, and
flag (not yet redact - that is Step 7 / OutputValidateNode) any
credential-shaped pattern already present in the raw export so downstream
steps do not blindly forward it. A domain input-validation reject returns an
ERROR dict directly (S-2) - the framework's own
SecurityViolationError is reserved for the S-1 trust-authorization gate.
"""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.service import detect_credential_patterns, normalize_log_format


class InputValidateNode(FunctionNode):
    """Validate the run-log export request before it enters the inner workflow."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # S-4: emit before the first validation guard so every path
        # (including the early-return rejects below) is traced, not just success.
        emit_trace_event(
            "input_validate_invoked",
            {"correlation_id": state.get("correlation_id")},
            state,
        )

        user_input = state.get("user_input", "")
        if not user_input or not str(user_input).strip():
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["InputValidateNode: user_input is empty or missing"],
            }

        try:
            payload = json.loads(user_input) if isinstance(user_input, str) else user_input
        except (TypeError, ValueError):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["InputValidateNode: payload is not valid JSON"],
            }

        if not isinstance(payload, dict):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["InputValidateNode: payload must be a JSON object"],
            }

        log_format, error = normalize_log_format(payload.get("log_format"))
        if error:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"InputValidateNode: {error}"],
            }

        raw_export = payload.get("raw_export")
        if raw_export is None or (isinstance(raw_export, (str, list)) and len(raw_export) == 0):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["InputValidateNode: raw_export is empty or missing"],
            }

        try:
            time_range_hours = int(payload.get("time_range_hours", 24))
        except (TypeError, ValueError):
            time_range_hours = 24

        raw_export_text = raw_export if isinstance(raw_export, str) else json.dumps(raw_export, ensure_ascii=False)
        detected = detect_credential_patterns(raw_export_text)
        if detected:
            emit_trace_event(
                "credential_pattern_detected_in_input",
                {"correlation_id": state.get("correlation_id"), "pattern_count": len(detected)},
                state,
            )

        validated_envelope = json.dumps(
            {"log_format": log_format, "raw_export": raw_export, "time_range_hours": time_range_hours},
            ensure_ascii=False,
        )

        emit_trace_event(
            "input_validated",
            {"correlation_id": state.get("correlation_id"), "log_format": log_format},
            state,
        )

        return {
            "validated_input": validated_envelope,
            "log_format": log_format,
            "time_range_hours": time_range_hours,
            "detected_flag_patterns": json.dumps(detected),
            "status": AgentStatus.SUCCESS.value,
        }
