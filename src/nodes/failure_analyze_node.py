"""AgentCore Platform v1.0 - CMN-C2-711 FailureAnalyzeNode (inner node, Step 4, LLM-essential).

LLM-essential: synthesise a natural-language root-cause narrative from
free-text error messages (stack traces, vendor exception strings, partial
log lines) grouped by first-line signature. This is NOT template-string
counting - a stateless `tally_runs()` function cannot cluster/synthesise
free-text root causes.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.service import build_failure_analysis_prompt, extract_text, group_failures_deterministic


class FailureAnalyzeNode(FunctionNode):
    """Cluster failed runs by error signature and synthesise an LLM root-cause narrative."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # S-4: emit before the first validation guard so every path
        # (including the early-return reject below) is traced, not just success.
        emit_trace_event(
            "failure_analyze_invoked",
            {"correlation_id": state.get("correlation_id")},
            state,
        )

        records = from_json(state.get("run_records"), None)
        if records is None:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["FailureAnalyzeNode: run_records missing - upstream not trusted blindly"],
            }

        groups = group_failures_deterministic(records)

        narrative = ""
        if self._llm is None:
            # Deterministic-core mode: no LLM configured, no enrichment expected -
            # narrative stays "" and the run still succeeds (fallback deterministic
            # is only valid when self._llm is None).
            pass
        elif groups:
            prompt = build_failure_analysis_prompt(groups)
            try:
                raw = self._llm.complete(prompt)
            except Exception as exc:  # noqa: BLE001 - narrow transport/provider failure below
                emit_trace_event(
                    "failure_analyze_llm_error",
                    {"correlation_id": state.get("correlation_id"), "error": str(exc)},
                    state,
                )
                return {
                    "status": AgentStatus.ERROR.value,
                    "error_log": [f"FailureAnalyzeNode: LLM call failed - {exc}"],
                }
            narrative = extract_text(raw).strip()
            if not narrative:
                # A configured LLM that returns an empty/unshaped response is a
                # provider failure, not "nothing to say" - a deterministic
                # fallback here would silently swallow it into SUCCESS.
                emit_trace_event(
                    "failure_analyze_llm_error",
                    {"correlation_id": state.get("correlation_id"), "error": "empty or unshaped LLM response"},
                    state,
                )
                return {
                    "status": AgentStatus.ERROR.value,
                    "error_log": ["FailureAnalyzeNode: LLM returned an empty or unshaped response"],
                }

        emit_trace_event(
            "failures_analyzed",
            {"correlation_id": state.get("correlation_id"), "group_count": len(groups), "llm_used": bool(narrative)},
            state,
        )

        return {
            "failure_summaries": to_json(groups),
            "failure_narrative": narrative,
            "status": AgentStatus.SUCCESS.value,
        }
