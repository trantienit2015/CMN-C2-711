"""AgentCore Platform v1.0 - CMN-C2-711 domain services.

Pure, deterministic helpers - no agenticstar/framework imports here.
log_format adapters, status classification, credential detection/redaction,
next-run extraction, and Markdown digest rendering for the automation
run-log health-digest domain.
"""

from __future__ import annotations

import json
import re
from typing import Any

VALID_LOG_FORMATS = ("hermes", "n8n", "temporal", "airflow", "generic-json")

_SUCCESS_ALIASES = ("success", "succeeded", "completed", "ok", "passed")
_FAILURE_ALIASES = ("failure", "failed", "error", "errored", "fail")
_SCHEDULED_ALIASES = ("scheduled", "waiting", "queued")
_PENDING_ALIASES = ("pending", "running", "in_progress", "started")

# S-2/S-3: deterministic (non-LLM) credential-shaped pattern detection + redaction.
CREDENTIAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Bearer [A-Za-z0-9._-]+"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(r"eyJ[a-zA-Z0-9._-]{10,}"),  # JWT
    re.compile(r"(?:postgres|postgresql|mysql|mongodb|redis|amqp)://[^\s\"']+"),  # connection string
]

# Per-orchestrator field-name aliases -> normalised run-record keys.
_FIELD_ALIASES: dict[str, dict[str, str]] = {
    "hermes": {
        "job_name": "job",
        "status_raw": "state",
        "started_at": "start_time",
        "finished_at": "end_time",
        "error_text": "error",
        "next_scheduled_at": "next_run",
    },
    "n8n": {
        "job_name": "workflowName",
        "status_raw": "status",
        "started_at": "startedAt",
        "finished_at": "stoppedAt",
        "error_text": "errorMessage",
        "next_scheduled_at": "nextRun",
    },
    "temporal": {
        "job_name": "workflowType",
        "status_raw": "status",
        "started_at": "startTime",
        "finished_at": "closeTime",
        "error_text": "failure",
        "next_scheduled_at": "nextRunTime",
    },
    "airflow": {
        "job_name": "dag_id",
        "status_raw": "state",
        "started_at": "start_date",
        "finished_at": "end_date",
        "error_text": "log",
        "next_scheduled_at": "next_dagrun",
    },
    "generic-json": {
        "job_name": "job_name",
        "status_raw": "status_raw",
        "started_at": "started_at",
        "finished_at": "finished_at",
        "error_text": "error_text",
        "next_scheduled_at": "next_scheduled_at",
    },
}


def normalize_log_format(fmt: str | None) -> tuple[str, str | None]:
    normalized = (fmt or "generic-json").strip().lower()
    if normalized not in VALID_LOG_FORMATS:
        return "", f"invalid log_format: {fmt!r} (must be one of {VALID_LOG_FORMATS})"
    return normalized, None


def detect_credential_patterns(text: str) -> list[str]:
    if not text:
        return []
    return [pat.pattern for pat in CREDENTIAL_PATTERNS if pat.search(text)]


def redact_credentials(text: str) -> tuple[str, bool]:
    """Deterministic regex redaction. Returns (redacted_text, dropped_any_line).

    A line is dropped (not just redacted) if a credential-shaped token remains
    after all pattern substitutions - fail-closed rather than leaking a partial
    match (S-3 "drop-line failure mode").
    """
    if not text:
        return text, False
    dropped = False
    out_lines: list[str] = []
    for line in text.split("\n"):
        redacted_line = line
        for pat in CREDENTIAL_PATTERNS:
            redacted_line = pat.sub("[REDACTED]", redacted_line)
        if detect_credential_patterns(redacted_line):
            dropped = True
            continue
        out_lines.append(redacted_line)
    return "\n".join(out_lines), dropped


def parse_export(raw_export: Any, log_format: str) -> list[dict[str, Any]] | None:
    """Parse a run-log export into normalised run records.

    Accepts a JSON array of dicts (or a JSON object wrapping one under
    runs/records/jobs) - all four supported orchestrators export JSON (or
    JSON-convertible CSV) arrays; only field names differ per log_format.
    """
    try:
        payload = json.loads(raw_export) if isinstance(raw_export, str) else raw_export
    except (TypeError, ValueError):
        return None

    if isinstance(payload, dict):
        payload = payload.get("runs") or payload.get("records") or payload.get("jobs") or []
    if not isinstance(payload, list):
        return None

    aliases = _FIELD_ALIASES.get(log_format, _FIELD_ALIASES["generic-json"])
    records: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        record = {
            "job_name": raw.get(aliases["job_name"], raw.get("job_name", "unknown")),
            "status_raw": raw.get(aliases["status_raw"], raw.get("status_raw", "")),
            "started_at": raw.get(aliases["started_at"], raw.get("started_at")),
            "finished_at": raw.get(aliases["finished_at"], raw.get("finished_at")),
            "error_text": raw.get(aliases["error_text"], raw.get("error_text", "")),
            "next_scheduled_at": raw.get(aliases["next_scheduled_at"], raw.get("next_scheduled_at")),
        }
        records.append(record)
    return records


def classify_status(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    counts = {"success": 0, "failure": 0, "scheduled": 0, "pending": 0}
    classified: list[dict[str, Any]] = []
    for r in records:
        raw = str(r.get("status_raw", "")).strip().lower()
        if raw in _SUCCESS_ALIASES:
            status = "success"
        elif raw in _FAILURE_ALIASES:
            status = "failure"
        elif raw in _SCHEDULED_ALIASES:
            status = "scheduled"
        else:
            status = "pending"
        rec = dict(r)
        rec["status"] = status
        classified.append(rec)
        counts[status] += 1
    return classified, counts


def extract_next_runs(records: list[dict[str, Any]], time_range_hours: int) -> list[dict[str, Any]]:
    # Deterministic: every record carrying a next_scheduled_at is in-window.
    # time_range_hours is accepted (per proposal Step 5 contract) for future
    # timestamp-window filtering; the offline export has no "now" reference,
    # so all declared next-run windows are surfaced.
    del time_range_hours
    return [
        {"job_name": r.get("job_name", "unknown"), "next_scheduled_at": r.get("next_scheduled_at")}
        for r in records
        if r.get("next_scheduled_at")
    ]


def group_failures_deterministic(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic clustering by first-line error signature.

    Baseline (testable) grouping; FailureAnalyzeNode layers an LLM-synthesised
    narrative on top for the human-readable root-cause summary.
    """
    groups: dict[str, list[str]] = {}
    for r in records:
        if r.get("status") != "failure":
            continue
        error_text = (r.get("error_text") or "").strip()
        signature = error_text.splitlines()[0][:120] if error_text else "unknown error"
        groups.setdefault(signature, []).append(r.get("job_name", "unknown"))
    return [{"root_cause": signature, "job_names": jobs} for signature, jobs in groups.items()]


def extract_text(raw: Any) -> str:
    """Normalize a BaseLLM.complete() result to plain text.

    Canonical contract is `complete(messages: list) -> dict` with a `content`
    key (`shared/services/llm/base_llm.py`); test fakes historically returned
    a bare string. Accept both without ever letting a dict fall through to
    `.strip()`/`.splitlines()` call sites (would `AttributeError` with a real
    client), and without silently discarding a real dict response as if the
    LLM produced nothing.
    """
    if isinstance(raw, dict):
        content = raw.get("content", "")
        return content if isinstance(content, str) else ""
    if isinstance(raw, str):
        return raw
    return ""


def build_failure_analysis_prompt(groups: list[dict[str, Any]]) -> str:
    lines = ["Synthesize a concise, human-readable root-cause summary for these grouped automation failures:"]
    for g in groups:
        jobs = ", ".join(g.get("job_names", []))
        lines.append(f"- signature: {g.get('root_cause')!r} | affected jobs: {jobs}")
    return "\n".join(lines)


def build_digest_prompt(
    counts: dict[str, Any], failure_summaries: list[dict[str, Any]], next_runs: list[dict[str, Any]], narrative: str
) -> str:
    return (
        "Write a short narrative health-digest commentary (severity framing, "
        f"cross-platform correlation) given: counts={counts}, "
        f"failure_summaries={failure_summaries}, next_runs={next_runs}, "
        f"prior root-cause narrative={narrative!r}."
    )


def render_digest_markdown(
    counts: dict[str, Any],
    failure_summaries: list[dict[str, Any]],
    next_runs: list[dict[str, Any]],
    narrative: str | None,
    failure_alert_threshold: int,
) -> str:
    total = sum(counts.values())
    lines = [
        "## Summary",
        "",
        f"- Total runs: {total}",
        f"- Success: {counts.get('success', 0)}",
        f"- Failure: {counts.get('failure', 0)}",
        f"- Scheduled: {counts.get('scheduled', 0)}",
        f"- Pending: {counts.get('pending', 0)}",
        "",
    ]

    if counts.get("failure", 0) >= failure_alert_threshold:
        lines.append("## Failures")
        lines.append("")
        for grp in failure_summaries:
            jobs = ", ".join(grp.get("job_names", []))
            lines.append(f"- **{grp.get('root_cause', 'unknown')}** — affected jobs: {jobs}")
        lines.append("")

    lines.append("## Next Scheduled Runs")
    lines.append("")
    if next_runs:
        for run in next_runs:
            lines.append(f"- {run.get('job_name')}: {run.get('next_scheduled_at')}")
    else:
        lines.append("- No upcoming scheduled runs found in the export.")
    lines.append("")

    if narrative:
        lines.append("## Notes")
        lines.append("")
        lines.append(narrative)

    return "\n".join(lines)
