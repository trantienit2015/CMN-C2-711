"""AgentCore Platform v1.0 - CMN-C2-711 state schema.

Enterprise Scheduled Agent Automation Status Report Agent.
Flat TypedDict extension of AgentState (ADR-005). Structured payloads
(list/dict) are JSON-string-encoded before being stored in state fields so
the schema stays msgpack-checkpoint-safe.
"""

import json
from typing import Any, NotRequired

from framework.schemas.agent_state import AgentState


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def from_json(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


# Type-check note: the wheel ships no py.typed, so mypy resolves AgentState to Any
# and reports every NotRequired below as valid-type. The fields are correct (the state
# contract requires NotRequired) -- the report is a packaging artifact, suppressed per field.
# Drop these ignores once the wheel ships py.typed.
class State(AgentState):
    """Agent state for CMN-C2-711.

    log_format: "hermes" | "n8n" | "temporal" | "airflow" | "generic-json".
    time_range_hours: caller-supplied filter window (default 24).
    detected_flag_patterns: JSON list of credential-pattern names detected at S-2 (informational).
    run_records: JSON list[dict] of normalised run records
      {job_name, status_raw, started_at, finished_at, error_text, next_scheduled_at, status}.
    status_counts: JSON dict {success, failure, scheduled, pending}.
    failure_summaries: JSON list[dict] {root_cause, job_names} - deterministic grouping.
    failure_narrative: LLM-synthesised free-text root-cause narrative (Step 4, LLM-essential).
    next_scheduled_runs: JSON list[dict] {job_name, next_scheduled_at}.
    digest_markdown: final Markdown health digest (S-3 redacted before return).
    """

    log_format: NotRequired[str]  # type: ignore[valid-type]
    time_range_hours: NotRequired[int]  # type: ignore[valid-type]
    detected_flag_patterns: NotRequired[str]  # type: ignore[valid-type]
    run_records: NotRequired[str]  # type: ignore[valid-type]
    status_counts: NotRequired[str]  # type: ignore[valid-type]
    failure_summaries: NotRequired[str]  # type: ignore[valid-type]
    failure_narrative: NotRequired[str]  # type: ignore[valid-type]
    next_scheduled_runs: NotRequired[str]  # type: ignore[valid-type]
    digest_markdown: NotRequired[str]  # type: ignore[valid-type]
