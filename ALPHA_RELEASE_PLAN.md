# Konman Alpha Readiness Plan

## Purpose

This document is the implementation specification for preparing Konman for a small, explicitly labeled alpha. It is not a claim that the current build is production-ready. The current code has useful CLI and graph foundations, but tests primarily exercise synthetic configurations and mocked provider responses. No real vendor-hook session or hosted LLM request has been verified end to end.

The alpha goal is safe, inspectable experimentation: preserve source evidence, avoid silent loss, make proposed context reviewable, and report integration limitations honestly. It is not to promise universal agent coverage or enforce boundaries against an agent that can edit files outside Konman's controls.

## Release Blockers

Do not announce the package as generally stable until the following are complete:

1. Raw prompt/transcript data is excluded from the user's Git repository by default, redacted before persistence and upload, and covered by clear retention controls.
2. Transcript ingestion is source-specific, incremental, restartable, and does not mark truncated or failed input processed.
3. `check` detects stale dependency effects itself; commit blocking must not depend on a prior `sync` run.
4. Proposed context has an explicit approve/reject/edit workflow and validation before active use.
5. Adapter installers preserve all existing user configuration and malformed config fails without destructive fallback.
6. `doctor` and automated tests clearly distinguish locally tested behavior from vendor/API behavior not tested against live services.
7. Credentials are not written in plaintext by default, including on Windows.

## Patch Plan

### 1. Data Safety and Atomic Writes

**Files:** `src/konman/engine.py`, `src/konman/config.py`, `src/konman/cli.py`

- During `konman init`, merge `.context/.raw/` into the repository `.gitignore`. Preserve all existing lines and comments, add a Konman-managed marker, and make repeated initialization idempotent. Never replace the user's `.gitignore`.
- Add a small atomic text/JSON/YAML write helper: write a sibling temporary file, flush and close it, then replace the target. Use it for captures, processed markers, graph nodes, adapter JSON, and config updates.
- Make raw capture filenames collision-resistant (UUID or monotonic sequence plus event/source), not second-resolution timestamps. Open new captures without overwriting an existing capture.
- Add `konman clean --older-than DAYS [--dry-run]` or equivalent retention controls. Default behavior must not delete captured data without the user's request.
- Make capture payloads avoid unnecessary absolute local paths and environment details. Treat prompts and transcripts as sensitive user data.

### 2. Credential Handling

**Files:** `src/konman/config.py`, `src/konman/cli.py`, `pyproject.toml`, README

- Replace default plaintext API-key persistence with an OS credential store (for example, Python `keyring`, whose Windows backend uses Credential Manager). Store non-secret provider fields in `~/.config/konman/config.json`; store only a credential reference there.
- If the credential backend is unavailable, require an environment variable or explicit opt-in to plaintext storage. Never print the key; redact it from errors and logs.
- Add `konman config --clear` and a migration path for existing plaintext config. Migration should import to the key store, then remove the plaintext value only after success. Warn clearly if migration cannot complete.
- Preserve the four declared API formats: `openai-compatible`, `anthropic`, `gemini`, and `ollama`. Reject unsupported formats before making a request. Verify actual request headers, endpoint paths, model naming, response extraction, and error bodies against provider docs and opt-in live smoke tests.

### 3. Source-Specific Transcript Ingestion

**Files:** new `src/konman/transcripts/` package, `src/konman/cli.py`, tests, README

Replace the generic VS Code recursive glob implementation behind `tail` with a parser registry and durable per-source cursors. Prefer a new explicit command:

```text
konman backfill --source claude-code|codex|cursor|copilot|kiro|antigravity [--dir PATH] [--since TIME]
```

Keep `tail` only as a documented deprecated alias during alpha, or remove it with a migration note. It must not imply a live listener.

Each parser must:

- Read only documented or fixture-verified source locations; accept an explicit source path for testing and nonstandard installs.
- Parse that source's actual JSON/JSONL format into a normalized event record containing source, session ID when available, role, event time, and text.
- Maintain a cursor per source file under `.context/state/cursors/`. Record byte/line offset plus a file identity/fingerprint. Detect truncation, rotation, and replacement; do not silently skip or duplicate events after restart.
- Support a dry run and report discovered, parsed, skipped, and failed counts. A malformed record must not discard the rest of a JSONL file.
- Persist only newly parsed records; do not read a growing log from byte zero every run.
- Include fixtures for each parser and document unsupported versions/layouts. Do not claim every IDE/version is supported until tested.

The hook-based `konman hook` path remains a separate live-capture adapter. It should use collision-resistant append/new-file semantics, enforce a maximum payload size with a visible diagnostic outside agent stdout, and fail open without swallowing evidence silently.

### 4. Redaction Before Persistence and Upload

**Files:** new `src/konman/redaction.py`, capture/extraction pipeline, tests, README

- Add a deterministic redaction pass for common credentials: authorization headers, API-key environment assignments, cloud access keys, private-key blocks, and known token formats. Apply it before any raw file is written and again before any remote provider request as defense in depth.
- Redact recursively in structured JSON fields as well as plain text. Preserve enough surrounding structure for transcript parsing.
- Add custom redaction patterns in project config. Do not transmit custom patterns or unredacted content to a model.
- Report how many spans were redacted, never the original values. Add tests with secrets in nested JSON, multiline text, and false-positive examples.
- State clearly that pattern redaction is best-effort and is not a guarantee that arbitrary secrets or personal data will be detected.

### 5. Extraction Queue Correctness

**Files:** `src/konman/cli.py`, `src/konman/engine.py`, tests

- Replace the single combined `[:60000]` truncation with bounded per-session/per-chunk requests. Each chunk must have a source ID and exact source offsets so evidence quotes can be checked against that chunk.
- Track each capture/chunk with states such as `pending`, `processing`, `processed`, and `failed`, including digest, cursor, attempt time, and error category. Use atomic state writes.
- Mark a chunk processed only after a valid provider response has been parsed and all accepted proposed nodes have been written. On network, parse, or disk failure, leave it retryable. A successful response with no candidates may be marked processed and must say so in output.
- Ensure human requirement evidence is extracted from the normalized human-role event, not inferred from arbitrary raw text. Decisions may cite assistant/user messages, but retain speaker attribution and exact evidence.
- Handle repeated or overlapping quotes, invalid response shape, provider refusal, truncated JSON, rate limits, and duplicate semantic candidates. Never claim a model assertion is verified merely because a quote exists.
- Save extraction output only as `proposed`; `AGENTS.md` and MCP active context must not promote proposed items as approved constraints.

### 6. `review` Command

**Files:** `src/konman/cli.py`, `src/konman/models.py`, graph helpers, tests, README

Add an interactive and noninteractive review command:

```text
konman review [--dir PATH] [--id NODE_ID] [--approve|--reject] [--edit]
```

- With no ID, list proposed nodes with type, evidence, source, and status.
- Support inspecting one node, approving it, rejecting it with a reason, or editing fields before approval.
- Record reviewer identity and timestamp. Do not overwrite the original evidence or model/source attribution.
- Add `rejected` to valid status schemas and ensure rejected/proposed nodes are excluded from active instructions and normal active-context MCP queries.
- Require confirmation before approval; allow scripted explicit approval flags for automation.
- Do not let `resolve` silently approve extraction proposals; stale decisions and unreviewed proposals are distinct workflows.

### 7. `check` and `sync` Contract

**Files:** `src/konman/engine.py`, `src/konman/cli.py`, pre-commit hook tests

Update `check` to be a read-only validator that independently computes and reports:

- YAML parse errors, schema errors, missing/duplicate IDs, and filename/ID mismatches.
- Dangling decision-to-requirement references and malformed boundary entries.
- Decisions whose evaluations reference superseded/disproven requirements, even if `sync` has not run.
- `needs_review` decisions and, under `--strict`, proposed nodes.
- Missing `.context` layout or raw-ignore protections.

`sync` may persist staleness status and regenerate `AGENTS.md`; `check` must not mutate files. The pre-commit hook should call `konman check` against the resolved repository root and block on errors. It must not depend on running `sync` or silently mutate tracked files during `git commit`.

`resolve` should validate that the decision exists, only clear stale state after the user confirms the updated reasoning, then run `check` again. Avoid `.get(...).upper()` crashes on malformed nodes; report validation errors instead.

### 8. `doctor` Command

**Files:** `src/konman/cli.py`, integration helpers, tests, README

Add:

```text
konman doctor [--dir PATH] [--source NAME] [--check-api]
```

Checks should be read-only by default and report PASS/WARN/FAIL for:

- Python/Konman version, repository root, `.context` layout, manifest schema, writable state/raw directories, and `.gitignore` coverage.
- Adapter files found, parseable JSON/YAML, expected hook command, and whether the configured tool executable is on PATH.
- Source transcript paths and parser support; do not claim hooks have fired based only on config-file existence.
- Provider name/format/model, credential availability without printing it, and endpoint reachability only when `--check-api` is requested.
- Pre-commit hook location and whether the managed block is present without replacing or changing it.

Exit nonzero for actionable failures; warnings such as an uninstalled vendor CLI or unverified hook runtime should be explicit, not treated as success.

### 9. Adapter Installers and `handoff`

**Files:** `src/konman/config.py`, `src/konman/cli.py`, adapter fixture tests

- Make every adapter merge idempotently. In particular, Antigravity must merge `.agents/hooks.json` instead of replacing it, preserve unrelated MCP server entries, and refuse to overwrite unreadable/invalid JSON.
- Validate every generated hook schema against checked-in fixtures derived from the supported tool versions. Add a `doctor` warning for version-specific limitations and trust/enablement requirements.
- In `handoff`, generate the pack and destination adapter only after checking the target. Avoid saying it hot-swaps or disables the previous tool. Add `--output` and include current checkpoint, open questions, pending proposals, active boundaries, and a concise Git diff/status summary where available.
- If the destination setup fails, retain the generated handoff pack and report the partial result accurately.

### 10. Record and Graph Data Integrity

**Files:** `src/konman/cli.py`, `src/konman/engine.py`, `src/konman/models.py`

- Refuse duplicate IDs unless the user explicitly requests edit/replace and confirms it.
- Store boundaries as a list and append a new boundary instead of replacing `boundaries.yaml`; support explicit edit/remove by stable boundary ID.
- Validate every write against the Pydantic models or a single equivalent schema layer. Keep model schema and YAML examples synchronized.
- Ensure `state`, MCP, and generated `AGENTS.md` handle null/malformed fields without crashing.
- Prevent `AGENTS.md` generation from suggesting proposed or rejected nodes as active constraints.

### 11. Alpha Packaging, Tests, and Documentation

**Files:** `pyproject.toml`, `README.md`, tests, changelog/release notes

- Replace the `Production/Stable` classifier with an Alpha classifier, align `pyproject.toml` and `src/konman/__init__.py` versions, and state that vendor hook formats can change.
- Add automated tests for each source parser, cursor resume/rotation, redaction, queue retry behavior, schema validation, boundary append, duplicate IDs, hook collisions, and pre-commit behavior.
- Keep provider request tests offline and deterministic; add opt-in live smoke tests that require explicit consent and environment variables. Never run real provider calls in default CI.
- Test supported Python versions on Windows, macOS, and Linux. Include package build/install smoke tests in CI.
- Rewrite README claims to distinguish implemented, fixture-tested, and not-yet-verified integrations. Explicitly state what raw data is stored, what is sent to an LLM, retention behavior, and how to delete it.
- Add a known-limitations section: no guaranteed universal hook coverage, parser support is version-specific, redaction is best-effort, model extraction proposes rather than verifies intent, and Git hooks are advisory local safeguards rather than a security sandbox.

## Suggested Implementation Order

1. Raw ignore rules, collision-safe writes, key storage, and accurate alpha messaging.
2. Source parser registry, durable cursors, redaction, and retry-safe chunk extraction.
3. Graph schemas, `review`, and independently correct `check`/pre-commit behavior.
4. `doctor`, non-destructive adapter installers, and handoff reporting.
5. Cross-platform CI, parser fixtures, opt-in integration tests, and alpha packaging.

## Alpha Acceptance Gate

A release candidate is suitable for a small alpha only when all are true:

- A clean install can initialize a project without staging raw capture data by default.
- Re-running capture/backfill after interruption neither loses nor duplicates events, including after log rotation.
- A requirement quoted only from an assistant turn cannot be promoted as a human requirement.
- Redaction is tested before local persistence and before provider upload; limitations are documented.
- Provider failures, malformed responses, and disk errors leave work retryable and never mark truncated input processed.
- `review` is required to activate extracted proposals; `check` catches invalid graph and stale-dependency states without prior `sync`.
- A pre-existing Git hook and each supported adapter config survive install/uninstall unchanged except for Konman's managed block.
- `doctor` clearly distinguishes configured adapters from integrations verified to have fired.
- Tests pass on supported OS/Python combinations; any vendor API/hook surface not exercised is listed as unverified in the release notes.

Until that gate is met, describe Konman as an experimental alpha prototype, not a production-stable context engine.