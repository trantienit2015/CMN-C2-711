# CMN-C2-711 — Enterprise Scheduled Agent Automation Status Report Agent

> **Category**: Cat 2 (orchestrates multiple steps to accomplish a specific use case)
> **Industry**: CMN

## Overview

Turns a run-log export from a job scheduler or workflow engine into a Markdown health digest
for the people who operate those automations. The input is a JSON object with `log_format`
(`hermes`, `n8n`, `temporal`, `airflow` or `generic-json`, default `generic-json`), `raw_export`
(a JSON array of run records, or an object wrapping one under `runs`, `records` or `jobs`) and an
optional `time_range_hours`. Empty input, input that is not valid JSON, an unknown `log_format`
and an empty export are rejected. Each format only differs in field names; they are mapped to one
record shape (job name, raw status, start/finish time, error text, next scheduled run).

The agent classifies every run as success, failure, scheduled or pending from a fixed list of
status words, groups failed runs by the first line of their error text, lists every record that
declares a next scheduled run, and renders a digest with Summary, Failures, Next Scheduled Runs and
(when present) Notes sections. `time_range_hours` is accepted but not yet used to filter runs.
Credential-shaped values (bearer tokens, API keys, access keys, JWTs, database connection strings)
are flagged at validation and redacted from the digest; content the framework's output gate
classifies as a credential ends the run with an error rather than a masked digest.

A language model is optional. When one is configured it writes a root-cause narrative for the
grouped failures and a short commentary that appears under Notes; a failed or empty reply ends the
run with an error. Without a model both steps are skipped and the digest is built purely from the
deterministic counts and groupings. The bundled HTTP entry point supplies an Anthropic client only
when `ANTHROPIC_API_KEY` is available, and requires an internal-trust caller.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | 3.11 or later |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent raises
`PlatformRequired` during graph compile / start-up preflight rather than starting in a partially
working state. This is intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and test specification
```

See `docs/02_design.md` for the design and `docs/03_test_spec.md` for the test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
