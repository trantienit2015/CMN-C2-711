"""AgentCore Platform v1.0 - CMN-C2-711 OutputValidateNode (outer post_process slot).

Step 7: S-3 deterministic output gate. Automation run logs
frequently embed connection strings, Bearer tokens, and webhook secrets in
error/config fields - this node regex-redacts any credential-shaped pattern
carried over into the digest, drops (not just masks) any line that still
matches after substitution, and non-suppressibly re-checks its own output
field via `_extra_security_gate_output` (S-3 self-consistency rule).
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.service import detect_credential_patterns, redact_credentials


class OutputValidateNode(FunctionNode):
    """Redact credential-shaped patterns from the digest before it is returned."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # S-4: emit before the first validation guard so every path
        # (including the early-return reject below) is traced, not just success.
        emit_trace_event(
            "output_validate_invoked",
            {"correlation_id": state.get("correlation_id")},
            state,
        )

        digest = state.get("digest_markdown", "")
        if not digest or not str(digest).strip():
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["OutputValidateNode: digest_markdown is empty - nothing to return"],
            }

        redacted, dropped_any_line = redact_credentials(digest)

        emit_trace_event(
            "digest_output_validated",
            {
                "correlation_id": state.get("correlation_id"),
                "digest_length": len(redacted),
                "dropped_any_line": dropped_any_line,
            },
            state,
        )

        # Echo digest_markdown in this node's own output so the S-3
        # hook re-checks the field this node actually produced, not an
        # upstream state field.
        # AgentBaseGraph.get_output() only surfaces state["result"] (or
        # state["formatted_output"]) as the top-level invoke() "output" - set
        # "result" here too so the caller receives the S-3-REDACTED digest,
        # never a pre-redaction value from an earlier node.
        return {
            "digest_markdown": redacted,
            "result": redacted,
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """Non-suppressible re-check on this node's own output field."""
        digest = state.get("digest_markdown", "")
        leftover = detect_credential_patterns(digest)
        if leftover:
            emit_trace_event(
                "output_redaction_recheck_blocked",
                {"pattern_count": len(leftover)},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["OutputValidateNode: S-3 re-check found an unredacted credential pattern in output"],
            }
        return state
