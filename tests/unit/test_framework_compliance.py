# CMN-C2-711 - Framework compliance tests TC-01..TC-08, written for
# this template's real architecture (Cat 2: outer pre/post InputValidate/OutputValidate +
# GraphNode-wrapped inner 5-node workflow).

import json
import os
import re
import typing

import pytest
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.nodes import input_validate_node, output_validate_node
from src.schemas.state import State

_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "src")
TRUST = TrustLevel.INTERNAL.value

SAMPLE_EXPORT = [
    {"job_name": "nightly-sync", "status_raw": "success", "next_scheduled_at": "2026-07-17T02:00:00Z"},
    {"job_name": "backup-job", "status_raw": "failed", "error_text": "ConnectionError: timeout", "next_scheduled_at": "2026-07-17T03:00:00Z"},
]


class FakeLLM:
    def complete(self, prompt: str) -> str:
        return "Deterministic test narrative."


def _src_files():
    for root, _d, files in os.walk(_SRC):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


# TC-01 - State is a flat TypedDict extending AgentState; agent-specific fields are
# primitives (or NotRequired[primitive] - compound payloads are JSON-string-encoded).
class TestTC01StateContract:
    def test_state_is_typeddict_extending_agent_state(self):
        assert hasattr(State, "__annotations__")
        assert "user_input" in State.__annotations__
        assert set(AgentState.__annotations__).issubset(set(State.__annotations__))

    def test_added_fields_are_primitives_or_json_str(self):
        added = [k for k in State.__annotations__ if k not in AgentState.__annotations__]
        assert added, "State must declare agent-specific fields"
        allowed = {"str", "int", "bool", "float"}
        for name in added:
            ann = State.__annotations__[name]
            # Unwrap NotRequired[...] (SSOT: every agent-specific field bows to NotRequired).
            if typing.get_origin(ann) is typing.NotRequired or getattr(ann, "__name__", "") == "NotRequired":
                args = typing.get_args(ann)
                ann = args[0] if args else ann
            ann_str = getattr(ann, "__name__", str(ann))
            assert ann_str in allowed, f"{name}: {ann_str} - compound fields must be JSON-string-encoded"


# TC-02 - Empty/missing input yields a fail-closed ERROR outcome, no raise.
class TestTC02Validation:
    def test_empty_input_no_raise(self):
        node = input_validate_node.InputValidateNode()
        out = node.execute({"user_input": ""})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]

    def test_malformed_json_no_raise(self):
        node = input_validate_node.InputValidateNode()
        out = node.execute({"user_input": "not json"})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]

    def test_empty_digest_no_raise(self):
        node = output_validate_node.OutputValidateNode()
        out = node.execute({"digest_markdown": ""})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]


# TC-03 - No JWT / API keys / secrets in src/; no direct os.environ reads for secrets
# (api/server.py's INVOKE_AUTH_TOKEN read is the documented entry-point auth exception).
class TestTC03NoCredentials:
    def test_no_credential_literals(self):
        pat = re.compile(r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")
        offenders = []
        for fp in _src_files():
            with open(fp, encoding="utf-8") as f:
                if pat.search(f.read()):
                    offenders.append(fp)
        assert offenders == []

    def test_no_os_environ_secret_reads_outside_entrypoint(self):
        offenders = []
        for fp in _src_files():
            if fp.endswith(os.path.join("api", "server.py")):
                continue  # documented entry-point caller-auth token exception
            with open(fp, encoding="utf-8") as f:
                if "os.environ" in f.read():
                    offenders.append(fp)
        assert offenders == []


# TC-04 - InvocationContext is never stored in State after invoke.
class TestTC04ContextIsolation:
    def test_no_invocationcontext_in_state_after_invoke(self):
        from src.graph.graph import Graph

        agent = Graph(config={"max_retry": 1, "llm": FakeLLM()})
        agent.compile()
        ctx = InvocationContext(session_id="tc04", caller_trust_level=TrustLevel.INTERNAL, caller_id="ops-tc04")
        result = agent.invoke(json.dumps({"log_format": "generic-json", "raw_export": SAMPLE_EXPORT}), ctx=ctx)
        for v in result.values():
            assert not isinstance(v, InvocationContext)

    def test_from_state_available(self):
        assert hasattr(InvocationContext, "from_state")


# TC-05 - Domain events: OutputValidateNode emits >=1 domain event; no node under
# src/nodes/ ever re-emits a framework backbone lifecycle event.
class TestTC05Audit:
    def test_output_node_emits_domain_event(self, monkeypatch):
        events = []
        monkeypatch.setattr(output_validate_node, "emit_trace_event", lambda e, p, s: events.append(e))
        out = output_validate_node.OutputValidateNode().execute({"digest_markdown": "## Summary\n\n- Total runs: 2"})
        assert out["status"] == AgentStatus.SUCCESS
        assert len(events) >= 1
        assert "digest_output_validated" in events
        assert not ({"node_start", "node_complete", "node_error", "node_skip"} & set(events))

    def test_source_has_no_backbone_events(self):
        pat = re.compile(r'emit_trace_event\(\s*["\'](node_start|node_complete|node_error|node_skip)["\']')
        offenders = []
        for fp in _src_files():
            with open(fp, encoding="utf-8") as f:
                if pat.search(f.read()):
                    offenders.append(fp)
        assert offenders == []


# TC-06 / TC-07 - S-2/S-3 gates are @final on FunctionNode (overriding raises TypeError at class def).
class TestTC0607FinalGates:
    def test_input_gate_is_final(self):
        with pytest.raises(TypeError):

            class BadIn(FunctionNode):  # noqa: N801
                def _security_gate_input(self, state):
                    return state

    def test_output_gate_is_final(self):
        with pytest.raises(TypeError):

            class BadOut(FunctionNode):  # noqa: N801
                def _security_gate_output(self, result):
                    return result

    def test_extra_hook_is_overridable(self):
        assert output_validate_node.OutputValidateNode._extra_security_gate_output is not FunctionNode._extra_security_gate_output

    def test_output_gate_blocks_credentials(self):
        # The @final S-3 credential scan actually fires (not vacuous): a
        # credential-shaped token surviving redaction is blocked, never returned as-is.
        node = output_validate_node.OutputValidateNode()
        with pytest.raises(Exception):
            node._security_gate_output({"digest_markdown": "token AKIAIOSFODNN7EXAMPLE leaked"})


# TC-08 - required_trust_level enforced: insufficient trust -> ERROR state, no raise.
class TestTC08TrustGate:
    def test_declared_trust_levels_valid(self):
        for cls in (input_validate_node.InputValidateNode, output_validate_node.OutputValidateNode):
            assert cls.required_trust_level in (TrustLevel.ANONYMOUS, TrustLevel.VERIFIED_EXTERNAL, TrustLevel.INTERNAL)

    def test_insufficient_trust_returns_error(self):
        node = input_validate_node.InputValidateNode()
        out = node({"caller_trust_level": TrustLevel.ANONYMOUS.value, "user_input": json.dumps({"log_format": "generic-json", "raw_export": SAMPLE_EXPORT})})
        assert str(out.get("status")).lower().endswith("error")

    def test_sufficient_trust_succeeds(self):
        node = input_validate_node.InputValidateNode()
        out = node({"caller_trust_level": TRUST, "user_input": json.dumps({"log_format": "generic-json", "raw_export": SAMPLE_EXPORT})})
        assert out["status"] == AgentStatus.SUCCESS
        assert out["log_format"] == "generic-json"
