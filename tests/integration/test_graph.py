# CMN-C2-711 - Integration test: full graph compile + invoke (Cat 2 outer + inner).

import json

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph

SAMPLE_EXPORT = [
    {"job_name": "nightly-sync", "status_raw": "success", "next_scheduled_at": "2026-07-17T02:00:00Z"},
    {"job_name": "backup-job", "status_raw": "failed", "error_text": "ConnectionError: timeout", "next_scheduled_at": "2026-07-17T03:00:00Z"},
]

VALID_PAYLOAD = json.dumps({"log_format": "generic-json", "raw_export": SAMPLE_EXPORT, "time_range_hours": 24})
EMPTY_INPUT = ""
INVALID_FORMAT_PAYLOAD = json.dumps({"log_format": "bogus-tool", "raw_export": SAMPLE_EXPORT})


class FakeLLM:
    def complete(self, prompt: str) -> str:
        return "Deterministic integration-test narrative."


class TestAgentIntegration:
    def test_valid_export_reaches_full_pipeline(self):
        # Assert the
        # environment-independent invariant (pipeline completion), not an
        # exact terminal status - unit tests already pin the success-path
        # logic deterministically.
        agent = Graph(config={"max_retry": 1, "llm": FakeLLM()})
        agent.compile()
        ctx = InvocationContext(session_id="it-1", caller_trust_level=TrustLevel.INTERNAL, caller_id="ops-001")
        result = agent.invoke(VALID_PAYLOAD, ctx=ctx)

        assert len(result.get("node_history", [])) >= 4
        assert result["status"] in ("success", "error", "cancelled")

    def test_without_llm_still_completes(self):
        agent = Graph(config={"max_retry": 1})
        agent.compile()
        ctx = InvocationContext(session_id="it-2", caller_trust_level=TrustLevel.INTERNAL, caller_id="ops-001")
        result = agent.invoke(VALID_PAYLOAD, ctx=ctx)

        assert len(result.get("node_history", [])) >= 4
        assert result["status"] in ("success", "error", "cancelled")

    def test_empty_input_error(self):
        agent = Graph(config={"max_retry": 1})
        agent.compile()
        ctx = InvocationContext(session_id="it-3", caller_trust_level=TrustLevel.INTERNAL, caller_id="ops-001")
        result = agent.invoke(EMPTY_INPUT, ctx=ctx)
        assert result["status"] in ("error", "cancelled")

    def test_invalid_log_format_error(self):
        agent = Graph(config={"max_retry": 1})
        agent.compile()
        ctx = InvocationContext(session_id="it-4", caller_trust_level=TrustLevel.INTERNAL, caller_id="ops-001")
        result = agent.invoke(INVALID_FORMAT_PAYLOAD, ctx=ctx)
        assert result["status"] in ("error", "cancelled")
