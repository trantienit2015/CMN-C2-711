# CMN-C2-711 - Unit tests: per-node success + error/edge paths.

import json

from framework.schemas.agent_status import AgentStatus

from src.nodes.digest_generate_node import DigestGenerateNode
from src.nodes.failure_analyze_node import FailureAnalyzeNode
from src.nodes.input_parse_node import InputParseNode
from src.nodes.input_validate_node import InputValidateNode
from src.nodes.next_run_extract_node import NextRunExtractNode
from src.nodes.output_validate_node import OutputValidateNode
from src.nodes.status_classify_node import StatusClassifyNode
from src.schemas.state import from_json, to_json

SAMPLE_EXPORT = [
    {"job_name": "nightly-sync", "status_raw": "success", "next_scheduled_at": "2026-07-17T02:00:00Z"},
    {"job_name": "backup-job", "status_raw": "failed", "error_text": "ConnectionError: timeout connecting to host\nstack trace...", "next_scheduled_at": "2026-07-17T03:00:00Z"},
    {"job_name": "cleanup-job", "status_raw": "failed", "error_text": "ConnectionError: timeout connecting to host\nstack trace...", "next_scheduled_at": None},
]


class FakeLLM:
    def __init__(self, response="Root cause: transient network timeouts across two jobs."):
        self._response = response

    def complete(self, prompt: str) -> str:
        return self._response


class FakeFailingLLM:
    def complete(self, prompt: str) -> str:
        raise RuntimeError("LLM unavailable")


class FakeEmptyLLM:
    """Simulates a provider call that succeeds transport-wise but returns nothing usable."""

    def complete(self, prompt: str) -> str:
        return ""


class FakeDictLLM:
    """Simulates the canonical BaseLLM.complete() contract: {"content": str, ...}."""

    def __init__(self, content="Root cause: transient network timeouts across two jobs."):
        self._content = content

    def complete(self, prompt: str) -> dict:
        return {"content": self._content, "tool_calls": [], "model": "fake-model", "usage": {}}


class TestInputValidateNode:
    def test_success(self):
        state = {"user_input": json.dumps({"log_format": "generic-json", "raw_export": SAMPLE_EXPORT, "time_range_hours": 12})}
        r = InputValidateNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["log_format"] == "generic-json"
        assert r["time_range_hours"] == 12
        envelope = from_json(r["validated_input"], {})
        assert envelope["raw_export"] == SAMPLE_EXPORT

    def test_empty_input_error(self):
        assert InputValidateNode().execute({"user_input": ""})["status"] == AgentStatus.ERROR

    def test_invalid_json_error(self):
        assert InputValidateNode().execute({"user_input": "not json"})["status"] == AgentStatus.ERROR

    def test_invalid_log_format_error(self):
        state = {"user_input": json.dumps({"log_format": "bogus-tool", "raw_export": SAMPLE_EXPORT})}
        assert InputValidateNode().execute(state)["status"] == AgentStatus.ERROR

    def test_missing_raw_export_error(self):
        state = {"user_input": json.dumps({"log_format": "generic-json"})}
        assert InputValidateNode().execute(state)["status"] == AgentStatus.ERROR

    def test_flags_credential_pattern_without_blocking(self):
        leaky_export = [{"job_name": "x", "status_raw": "failed", "error_text": "auth failed: Bearer abc123XYZtoken"}]
        state = {"user_input": json.dumps({"log_format": "generic-json", "raw_export": leaky_export})}
        r = InputValidateNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert from_json(r["detected_flag_patterns"], [])


class TestInputParseNode:
    def test_success(self):
        envelope = {"log_format": "generic-json", "raw_export": SAMPLE_EXPORT, "time_range_hours": 24}
        r = InputParseNode().execute({"user_input": to_json(envelope)})
        assert r["status"] == AgentStatus.SUCCESS
        records = from_json(r["run_records"], [])
        assert len(records) == 3

    def test_malformed_envelope_error(self):
        assert InputParseNode().execute({"user_input": "not json"})["status"] == AgentStatus.ERROR

    def test_empty_export_error(self):
        envelope = {"log_format": "generic-json", "raw_export": []}
        assert InputParseNode().execute({"user_input": to_json(envelope)})["status"] == AgentStatus.ERROR


class TestStatusClassifyNode:
    def test_success(self):
        state = {"run_records": to_json(SAMPLE_EXPORT)}
        r = StatusClassifyNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        counts = from_json(r["status_counts"], {})
        assert counts["success"] == 1
        assert counts["failure"] == 2

    def test_missing_records_error(self):
        assert StatusClassifyNode().execute({"run_records": None})["status"] == AgentStatus.ERROR


class TestFailureAnalyzeNode:
    def test_success_without_llm(self):
        classified = [{**r, "status": "failure" if r["status_raw"] == "failed" else "success"} for r in SAMPLE_EXPORT]
        state = {"run_records": to_json(classified)}
        r = FailureAnalyzeNode(llm=None).execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        groups = from_json(r["failure_summaries"], [])
        assert len(groups) == 1  # same signature clusters both failed jobs
        assert len(groups[0]["job_names"]) == 2
        assert r["failure_narrative"] == ""

    def test_success_with_llm(self):
        classified = [{**r, "status": "failure" if r["status_raw"] == "failed" else "success"} for r in SAMPLE_EXPORT]
        state = {"run_records": to_json(classified)}
        r = FailureAnalyzeNode(llm=FakeLLM()).execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert "transient network timeouts" in r["failure_narrative"]

    def test_success_with_canonical_dict_llm(self):
        # Real BaseLLM.complete() returns {"content": str, ...}, not a bare
        # string - the node must extract it, not discard it.
        classified = [{**r, "status": "failure" if r["status_raw"] == "failed" else "success"} for r in SAMPLE_EXPORT]
        state = {"run_records": to_json(classified)}
        r = FailureAnalyzeNode(llm=FakeDictLLM()).execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert "transient network timeouts" in r["failure_narrative"]

    def test_configured_llm_failure_is_not_swallowed_into_success(self):
        # A configured LLM that errors is a provider failure, not "nothing to
        # say" - falling back to SUCCESS here would hide the failure from the
        # caller. Fallback-to-SUCCESS is
        # only valid when NO llm is configured (see test_success_without_llm).
        classified = [{**r, "status": "failure" if r["status_raw"] == "failed" else "success"} for r in SAMPLE_EXPORT]
        state = {"run_records": to_json(classified)}
        r = FailureAnalyzeNode(llm=FakeFailingLLM()).execute(state)
        assert r["status"] == AgentStatus.ERROR

    def test_configured_llm_empty_response_is_not_swallowed_into_success(self):
        classified = [{**r, "status": "failure" if r["status_raw"] == "failed" else "success"} for r in SAMPLE_EXPORT]
        state = {"run_records": to_json(classified)}
        r = FailureAnalyzeNode(llm=FakeEmptyLLM()).execute(state)
        assert r["status"] == AgentStatus.ERROR

    def test_missing_records_error(self):
        assert FailureAnalyzeNode().execute({"run_records": None})["status"] == AgentStatus.ERROR


class TestNextRunExtractNode:
    def test_success(self):
        state = {"run_records": to_json(SAMPLE_EXPORT), "time_range_hours": 24}
        r = NextRunExtractNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        runs = from_json(r["next_scheduled_runs"], [])
        assert len(runs) == 2  # third record has next_scheduled_at=None

    def test_missing_records_error(self):
        assert NextRunExtractNode().execute({"run_records": None})["status"] == AgentStatus.ERROR


class TestDigestGenerateNode:
    def test_success(self):
        state = {
            "status_counts": to_json({"success": 1, "failure": 2, "scheduled": 0, "pending": 0}),
            "failure_summaries": to_json([{"root_cause": "ConnectionError: timeout", "job_names": ["backup-job", "cleanup-job"]}]),
            "next_scheduled_runs": to_json([{"job_name": "nightly-sync", "next_scheduled_at": "2026-07-17T02:00:00Z"}]),
            "failure_narrative": "",
        }
        r = DigestGenerateNode(llm=None).execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert "## Summary" in r["digest_markdown"]
        assert "## Failures" in r["digest_markdown"]
        assert "## Next Scheduled Runs" in r["digest_markdown"]

    def test_success_with_canonical_dict_llm(self):
        state = {
            "status_counts": to_json({"success": 1, "failure": 2, "scheduled": 0, "pending": 0}),
            "failure_summaries": to_json([{"root_cause": "ConnectionError: timeout", "job_names": ["backup-job", "cleanup-job"]}]),
            "next_scheduled_runs": to_json([{"job_name": "nightly-sync", "next_scheduled_at": "2026-07-17T02:00:00Z"}]),
            "failure_narrative": "",
        }
        r = DigestGenerateNode(llm=FakeDictLLM("Cross-platform correlation: both failures share a network root cause.")).execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert "Cross-platform correlation" in r["digest_markdown"]

    def test_configured_llm_failure_is_not_swallowed_into_success(self):
        state = {
            "status_counts": to_json({"success": 1, "failure": 2, "scheduled": 0, "pending": 0}),
            "failure_summaries": to_json([]),
            "next_scheduled_runs": to_json([]),
            "failure_narrative": "",
        }
        r = DigestGenerateNode(llm=FakeFailingLLM()).execute(state)
        assert r["status"] == AgentStatus.ERROR

    def test_configured_llm_empty_response_is_not_swallowed_into_success(self):
        state = {
            "status_counts": to_json({"success": 1, "failure": 2, "scheduled": 0, "pending": 0}),
            "failure_summaries": to_json([]),
            "next_scheduled_runs": to_json([]),
            "failure_narrative": "",
        }
        r = DigestGenerateNode(llm=FakeEmptyLLM()).execute(state)
        assert r["status"] == AgentStatus.ERROR

    def test_missing_counts_error(self):
        assert DigestGenerateNode().execute({"status_counts": None})["status"] == AgentStatus.ERROR


class TestOutputValidateNode:
    def test_success(self):
        state = {"digest_markdown": "## Summary\n\n- Total runs: 3"}
        r = OutputValidateNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        # AgentBaseGraph.get_output() only surfaces state["result"] as the
        # top-level invoke() output - it must carry the (redacted) digest.
        assert r["result"] == r["digest_markdown"]

    def test_empty_digest_error(self):
        assert OutputValidateNode().execute({"digest_markdown": ""})["status"] == AgentStatus.ERROR

    def test_redacts_credential_pattern(self):
        state = {"digest_markdown": "## Notes\n\nauth: Bearer abc123XYZtoken leaked in log"}
        r = OutputValidateNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert "Bearer abc123XYZtoken" not in r["digest_markdown"]
        assert "[REDACTED]" in r["digest_markdown"]

    def test_extra_gate_blocks_leftover_credential(self):
        bad_state = {"digest_markdown": "token AKIAIOSFODNN7EXAMPLE leaked"}
        out = OutputValidateNode()._extra_security_gate_output(bad_state)
        assert out["status"] == AgentStatus.ERROR

    def test_extra_gate_passthrough_clean_output(self):
        good_state = {"digest_markdown": "## Summary\n\n- Total runs: 1"}
        assert OutputValidateNode()._extra_security_gate_output(good_state) is good_state
