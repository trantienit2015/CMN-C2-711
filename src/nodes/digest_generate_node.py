"""AgentCore Platform v1.0 - CMN-C2-711 DigestGenerateNode (inner node, Step 6, LLM-essential).

LLM-essential: generate the narrative health-digest commentary (cross-
platform correlation, severity framing, recommended attention) layered on
top of the fixed-schema Markdown digest (Summary / Failures / Next
Scheduled Runs / Notes - locked in docs/02_design.md).
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json
from src.services.service import build_digest_prompt, extract_text, render_digest_markdown

DEFAULT_FAILURE_ALERT_THRESHOLD = 1


class DigestGenerateNode(FunctionNode):
    """Render the narrative Markdown health digest from the pipeline's analysis fields."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(self, llm: Any = None, failure_alert_threshold: int = DEFAULT_FAILURE_ALERT_THRESHOLD):
        self._llm = llm
        self._failure_alert_threshold = failure_alert_threshold

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # S-4: emit before the first validation guard so every path
        # (including the early-return rejects below) is traced, not just success.
        emit_trace_event(
            "digest_generate_invoked",
            {"correlation_id": state.get("correlation_id")},
            state,
        )

        counts = from_json(state.get("status_counts"), None)
        if counts is None:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["DigestGenerateNode: status_counts missing - upstream not trusted blindly"],
            }

        failure_summaries = from_json(state.get("failure_summaries"), [])
        next_runs = from_json(state.get("next_scheduled_runs"), [])
        narrative = state.get("failure_narrative", "") or ""

        if self._llm is None:
            # Deterministic-core mode: no LLM configured, no enrichment expected -
            # narrative keeps the upstream FailureAnalyzeNode value as-is (fallback
            # deterministic is only valid when self._llm is None).
            pass
        else:
            prompt = build_digest_prompt(counts, failure_summaries, next_runs, narrative)
            try:
                raw = self._llm.complete(prompt)
            except Exception as exc:  # noqa: BLE001 - narrow transport/provider failure below
                emit_trace_event(
                    "digest_generate_llm_error",
                    {"correlation_id": state.get("correlation_id"), "error": str(exc)},
                    state,
                )
                return {
                    "status": AgentStatus.ERROR.value,
                    "error_log": [f"DigestGenerateNode: LLM call failed - {exc}"],
                }
            enriched = extract_text(raw).strip()
            if not enriched:
                # A configured LLM that returns an empty/unshaped response is a
                # provider failure, not "nothing to add" - silently keeping the
                # pre-LLM narrative would mask the failure as SUCCESS.
                emit_trace_event(
                    "digest_generate_llm_error",
                    {"correlation_id": state.get("correlation_id"), "error": "empty or unshaped LLM response"},
                    state,
                )
                return {
                    "status": AgentStatus.ERROR.value,
                    "error_log": ["DigestGenerateNode: LLM returned an empty or unshaped response"],
                }
            narrative = enriched

        digest = render_digest_markdown(counts, failure_summaries, next_runs, narrative, self._failure_alert_threshold)

        emit_trace_event(
            "digest_generated",
            {"correlation_id": state.get("correlation_id"), "digest_length": len(digest)},
            state,
        )

        return {
            "digest_markdown": digest,
            "status": AgentStatus.SUCCESS.value,
        }
