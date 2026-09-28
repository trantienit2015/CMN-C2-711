# Template Design Specification — CMN-C2-711

## Position in AgentCore Architecture

- **Agent Class**: `CMNScheduledAutomationStatusReportAgent`
- **L1 Base**: AgentBaseGraph (outer, Cat 2) — `main` slot wraps `ScheduledAutomationDigestGraphNode`
  (`GraphNode`) around an inner `BaseGraph` (`ScheduledAutomationWorkflowGraph`)
- **Three-Layer Separation**:
  - State: flat TypedDict composition (`src/schemas/state.py`, agent-specific fields `NotRequired[...]`,
    compound payloads JSON-string-encoded — msgpack incompatible with Pydantic/dataclass)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (outer `register_nodes()` for the 3 pipeline slots; inner
    `register_nodes()`/`add_edges()` for the 5-step domain workflow)

## Architecture Overview

### Node Configuration

| Node | Layer | Responsibility | Input State | Output State | Inherits/Overrides |
|------|-------|----------------|--------------|--------------|---------------------|
| initialize | outer | schema_version, session_id, trust_level | — | — | InitializeNode (default) |
| pre_process → `InputValidateNode` | outer | S-1 (INTERNAL) + S-2 deterministic scan; validate `log_format`/`raw_export`, flag credential patterns | `user_input` | `validated_input`, `log_format`, `time_range_hours`, `detected_flag_patterns` | `FunctionNode` |
| main → `ScheduledAutomationDigestGraphNode` | outer | `GraphNode` wrapping the inner 5-step workflow | `validated_input` | `run_records`, `status_counts`, `failure_summaries`, `next_scheduled_runs`, `digest_markdown` | `GraphNode` |
| — `input_parse` | inner | deterministic parse by `log_format` → normalised run records | `user_input` (envelope) | `run_records`, `log_format`, `time_range_hours` | `FunctionNode` |
| — `status_classify` | inner | deterministic status mapping + tally | `run_records` | `run_records` (+status), `status_counts` | `FunctionNode` |
| — `failure_analyze` | inner | **LLM-essential**: cluster + synthesise free-text root-cause narrative | `run_records` | `failure_summaries`, `failure_narrative` | `FunctionNode` |
| — `next_run_extract` | inner | deterministic extraction of upcoming scheduled windows | `run_records` | `next_scheduled_runs` | `FunctionNode` |
| — `digest_generate` | inner | **LLM-essential**: narrative Markdown digest (Summary/Failures/Next Scheduled Runs/Notes) | `status_counts`, `failure_summaries`, `next_scheduled_runs`, `failure_narrative` | `digest_markdown` | `FunctionNode` |
| post_process → `OutputValidateNode` | outer | S-3 deterministic credential redaction (regex → `[REDACTED]`, drop-line on unredactable) | `digest_markdown` | `digest_markdown` (redacted) | `FunctionNode` |
| finalize | outer | response_metadata, total_time_ms | — | — | FinalizeNode (default) |

### Data Flow

```
OUTER: START → initialize → pre_process(InputValidate) → main(GraphNode) → post_process(OutputValidate) → finalize → END
                                                              │ extract_input() = validated_input (JSON envelope)
                                                              ▼
INNER: START → input_parse → status_classify → failure_analyze → next_run_extract → digest_generate → END
```

### `FailureAnalyze` — optional LLM root-cause narrative

`FailureAnalyzeNode` clusters failed runs deterministically by first-line error signature
(testable baseline), then — when an `llm` is provided — calls `llm.complete()` to synthesise a
human-readable root-cause narrative from the free-text `error_text` values (stack traces, vendor
exception strings). `DigestGenerateNode` layers a second LLM call on top for narrative severity
framing across the whole digest. When `llm` is `None` both calls are skipped and the digest is built
from the deterministic counts and groupings; when a configured `llm` raises or returns an empty
reply, the node returns `status: error`.

### Digest output schema

Markdown, required sections: `## Summary` (total/success/failure/scheduled/pending counts —
always) · `## Failures` (grouped root-cause summaries + affected job names — only when
`failure count >= failure_alert_threshold`, default 1) · `## Next Scheduled Runs` (job_name + next
window — always) · `## Notes` (optional — LLM narrative, when present).

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `log_format` | `NotRequired[str]` | `hermes\|n8n\|temporal\|airflow\|generic-json` | No (default `generic-json`) |
| `time_range_hours` | `NotRequired[int]` | caller-supplied filter window | No (default 24) |
| `detected_flag_patterns` | `NotRequired[str]` | JSON list — S-2 detected pattern names (informational) | No |
| `run_records` | `NotRequired[str]` | JSON list[dict] normalised run records | No |
| `status_counts` | `NotRequired[str]` | JSON dict `{success,failure,scheduled,pending}` | No |
| `failure_summaries` | `NotRequired[str]` | JSON list[dict] `{root_cause, job_names}` | No |
| `failure_narrative` | `NotRequired[str]` | LLM-synthesised root-cause narrative | No |
| `next_scheduled_runs` | `NotRequired[str]` | JSON list[dict] `{job_name, next_scheduled_at}` | No |
| `digest_markdown` | `NotRequired[str]` | final S-3-redacted Markdown digest | No |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types) — all agent-specific fields `NotRequired[...]`
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `config["configurable"]` only (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, caller_trust_level)
- [ ] ConnectionPolicy (retry/timeout strategy) — default `max_retry`/`timeout_seconds` only
- [ ] SecurityViolationError — not raised directly; domain rejects return ERROR dicts (S-1 gate itself
      raises this for trust denial)
- [x] S-2: `_extra_security_gate_input()` — not overridden; deterministic credential-pattern
      detection is performed inside `InputValidateNode.execute()` itself (flag-only, non-blocking),
      not as an S-2 hook, since it must run before the JSON/log_format validation logic.
- [x] S-3: `_extra_security_gate_output()` — implemented on `OutputValidateNode`: non-suppressible
      re-check that the node's own `digest_markdown` output contains no leftover credential-shaped
      pattern after the deterministic redaction in `execute()`.
- [x] S-4: `emit_trace_event()` — every node (outer + inner) emits >=1 domain event inside
      `execute()`: `input_validated`, `run_log_parsed`, `runs_classified`, `failures_analyzed`,
      `next_runs_extracted`, `digest_generated`, `digest_output_validated`. The outer `GraphNode`
      also emits `scheduled_automation_workflow_dispatched`/`_completed` inside
      `extract_input()`/`merge_output()` (both run inside `GraphNode.execute()`).

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` / `RemoteAgentNode` → deliberate no-op (upstream or remote node's gate already applied)
> - Custom `BaseNode` subclass → must implement `_security_gate_input()` and
>   `_security_gate_output()` directly (`@abstractmethod` — omission raises `TypeError` at instantiation)

### Composition Pattern

- **Pattern**: `GraphNode` (subgraph) — outer `AgentBaseGraph` backbone wraps an inner `BaseGraph`
  domain workflow in the `main` slot (Cat 2 mandatory pattern per review-criteria feedback 2026-06-17).
- **Composition target**: `src/graph/domain_workflow_graph.py` — `ScheduledAutomationWorkflowGraph`
- **Error propagation strategy**: `propagate` (fail fast — inner `ERROR` status short-circuits to `END`
  via conditional edges; `GraphNode.error_strategy = "propagate"` re-raises inner exceptions as
  `SubgraphError`)

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: `framework/` and `shared/` only (no `agents/base/` required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | **AgentBaseGraph** | Cat 2 fixed multi-step workflow, no autonomous think-act loop needed |
| Composition pattern | Flat 3-slot (Cat 1 style) | `GraphNode` + inner subgraph | **GraphNode + inner subgraph** | Cat 2 mandatory pattern; 5 domain steps cannot be flattened into one `main` node without violating `gate-composition` |
| Credential detection point | S-2 hook only | Deterministic check inside `InputValidateNode.execute()` (flag) + `OutputValidateNode` S-3 redaction (block) | **Both — flag at input, redact+block at output** | Detection at input is informational (raw export may legitimately reference credential-shaped test fixtures); the binding control is the S-3 output gate before the digest is ever returned to the caller |
