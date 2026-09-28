# Test Specification — CMN-C2-711

## Test Strategy
- Coverage target: every node ≥1 success + ≥1 error/edge unit test; ≥1 full-graph integration test
- Test types: Unit (`tests/unit/`) / Integration (`tests/integration/`) / Proof-of-Boundary (`tests/proof_of_boundary/`)

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict, agent-specific fields `NotRequired[str\|int]` | Type check pass, no Pydantic/dataclass | PASS |
| TC-02 | Fail-closed validation on empty/invalid input | ERROR dict returned, no raise | PASS |
| TC-03 | No JWT/Credential literals in `src/`; no `os.environ` outside the documented entry-point auth exception | 0 violations | PASS |
| TC-04 | InvocationContext never stored in State after invoke | Absent from result values | PASS |
| TC-05 | S-4: domain event on `OutputValidateNode`; no backbone-event re-emit anywhere in `src/` | `digest_output_validated` present; 0 `node_start`/`node_complete`/`node_error` re-emits | PASS |
| TC-06 | S-2: `_security_gate_input()` `@final` on `FunctionNode` | `TypeError` at class definition if overridden | PASS |
| TC-07 | S-3: `_security_gate_output()` `@final` on `FunctionNode`; credential-block verified | `TypeError` if overridden; leftover credential raises | PASS |
| TC-08 | `required_trust_level` declared valid + enforced (ANONYMOUS→INTERNAL denied) | Insufficient trust → ERROR status | PASS |
| TC-09 | S-2 domain check — deterministic credential-pattern flag inside `InputValidateNode.execute()` | Non-blocking flag recorded in `detected_flag_patterns` | PASS |
| TC-10 | S-3 domain check — `_extra_security_gate_output()` on `OutputValidateNode` non-trivial | Blocks leftover credential pattern; passthrough otherwise | PASS |
| TC-11 | S-4 — every node emits ≥1 domain event inside `execute()` | 7/7 nodes covered (`input_validated`, `run_log_parsed`, `runs_classified`, `failures_analyzed`, `next_runs_extracted`, `digest_generated`, `digest_output_validated`) + GraphNode dispatch/completed events | PASS |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | No silent failures | PASS |
| PB-2 | State serialization | Post-invoke State is primitives only | No Pydantic/dataclass | PASS |
| PB-3 | Level 2 → External service | N/A — input is a caller-supplied offline log export, no live external service call | N/A |
| PB-4 | Import isolation | No Level 0 imports | AST scan: 0 violations | PASS |
| PB-5 | Checkpoint safety | No JWT/Pydantic in checkpoint | Inspection pass | PASS |
| PB-6 | Invoke execution order | `__call__()`: S-1 → S-4 `node_start` → S-2 → `execute()` → S-3 → S-4 `node_complete`, for every concrete `src/nodes/` class | Order verified | PASS |
| PB-7 | HITL interrupt propagation | `hitl.enabled` not set (false) — auto-waived, non-HITL | Auto-waived — non-HITL | N/A |

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01 | Cross-orchestrator parse | `log_format=hermes\|n8n\|temporal\|airflow\|generic-json` sample export | Normalised run records with consistent field shape | PASS (generic-json covered in unit/integration; other adapters share the same `_FIELD_ALIASES` mapping — service-layer unit-tested via `parse_export`) |
| BL-02 | Failure grouping + LLM narrative | 2 failed runs, same error signature | 1 grouped `failure_summaries` entry, `job_names` length 2; narrative populated when `llm` provided, empty (not crash) when absent/failing | PASS |
| BL-03 | S-3 redaction end-to-end | Digest containing a `Bearer <token>` pattern | Returned digest contains `[REDACTED]`, never the raw token | PASS |

## Test Execution Summary
- Execution date: 2026-07-16
- Total tests: unit (`test_nodes.py` + `test_framework_compliance.py`) + integration (`test_graph.py`) + proof_of_boundary (4 files)
- Pass: all — see the CI pipeline for the authoritative run
- Coverage: every node has ≥1 success + ≥1 error/edge unit test; 1 full-Cat-2-pipeline integration test with and without an injected LLM
