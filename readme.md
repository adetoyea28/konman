# konman (Context Manager) v1.1.3a4 Alpha

**Experimental alpha:** Konman is being tested by early users. Generated adapters and parser fixtures do not prove that every vendor client/version will invoke its hooks. Verify your own tool with `konman doctor`; do not treat prompts or Git hooks as a security boundary. Extraction proposes context for human review and can send redacted transcript text to the configured provider.

Konman keeps developer context in version-controlled project data rather than only in chat sessions.

## What's New in 1.1.3a4

- Track first-class Objects, Evidence, Changes, Questions, and Risks alongside requirements, decisions, and protected boundaries. These records support extraction, review, resolution, validation, state, handoff, MCP, and generated documentation.
- `konman mine` now proposes structured Change and Evidence records for commit messages containing explicit reasoning clues.
- Requirements, decisions, and boundaries extracted from captures are linked to proposed Evidence records; this provenance record is created alongside the selected node type.
- `konman record`, `konman review`, and `konman resolve` support the new node lifecycles; `konman check` validates their schemas and graph references.
- Fixed GUI node creation so the newly created node is selected without mutating Streamlit's selectbox state after the widget has been instantiated.
- Launch the optional local Streamlit context graph with `konman gui` after installing `konman[gui]`. Browse typed relationships, create/edit records, review proposals, resolve questions/risks, and check graph validity.

### Previous updates in 1.1.2a1

- Generate a Markdown or PDF specification document from project context with `konman doc`; PDF generation is available through the optional `pdf` extra.

### Previous updates in 1.1.1a1

- Select the context node types to extract with repeatable `konman extract --type` options. Requirements, decisions, and boundaries can be extracted, and later runs can process additional types from the same captures.
- Extracted boundaries are proposed for review like other extracted nodes. They become active context only after approval with `konman review --id B-001`.
- Switching providers with `konman config --provider` now uses the selected provider's defaults rather than silently reusing the previous provider's API format, endpoint, or credential. Partial updates to the currently configured provider continue to reuse its saved settings.

---

## 🎯 Core Philosophy

Standard AI-driven development tools lock your project's history inside localized chat interfaces or vendor ecosystems. When your API tokens expire or you switch models, the new assistant lacks the complete picture, often modifying code it shouldn't touch or re-proposing rejected options.

**konman** solves this by breaking context down into 6 fundamental dimensions:
1. **Who**: The actor (Human or specific LLM) making the assertion.
2. **What**: The changes made (Code modifications, symbols, diffs).
3. **Where**: The scope of the adjustment (File paths, dependency graphs).
4. **When**: The timeline anchor (Git commit history, session timestamps).
5. **How**: The mechanism used (Build configs, testing assertions).
6. **Why**: The human intent, constraints, and evaluated tradeoffs.

While *What, Where, When,* and *How* can easily be recovered by indexing raw code, the **Why** is completely lost once a session vanishes. **konman** dynamically captures the "Why" at the moment it is generated, standardizing it into an evaluation matrix:

\[\text{Object } (O) \xrightarrow{\text{satisfies}} \text{Requirement } (R) \text{ due to its verified Property } (P)\]

---

## 🚀 Quickstart & Global Installation

### 1. Install the library via pip
Ensure you have Python 3.10+ installed. Install the core library for Markdown documentation:

```bash
pip install konman==1.1.3a4
```

To enable PDF documentation generation, install the `pdf` optional dependency extra:

```bash
pip install "konman[pdf]==1.1.3a4"
```

Verify your global environment configuration setup by triggering the structured help display:
```bash
konman --help
```

### 2. Scaffold a Codebase Repository
Navigate into your target software application codebase folder (e.g., `playce-api`) and initialize the context filesystem:
```bash
cd /path/to/project
konman init
```
This deploys the underlying `.context/` data graph infrastructure:
* `requirements/`: `.yaml` files detailing hard structural limitations and developer preferences.
* `decisions/`: Architectural tradeoffs, chosen technologies, and rejected alternative options.
* `objects/`: First-class tracked components, technologies, services, and their properties.
* `evidence/`: Verbatim evidence and its source/provenance.
* `changes/`: Proposed or accepted implementation changes and links to requirements/decisions.
* `questions/`: Open questions, answers, and deferred items.
* `risks/`: Risks, their likelihood/impact, mitigation, and resolution.
* `boundaries.yaml`: Protected codebase paths mapped to explicit verification criteria.
* `.raw/`: Project-ignored temporary cache for redacted captured/backfilled events before extraction. Redaction is best-effort; inspect policy and data before sharing.

### Optional local context GUI

Install the GUI extra to browse the linked context graph and manage records in a local Streamlit interface:

```bash
pip install "konman[gui]==1.1.3a4"
konman gui
```

The GUI binds to `127.0.0.1` by default, opens the local page in your browser, and stores edits in the project’s `.context/` YAML files. Use `konman gui --dir PATH --port 8502` to select a project and port, or add `--no-browser` to start it without opening a browser. The interface supports graph filters, node inspection, creation/editing and relationships, lifecycle status updates, and graph validation. It does not expose a network service; do not forward the local port to an untrusted network.

---

## 🔌 Multi-Tool Setup & Integration Manual

**konman** is built to sit between you and your developer assistants. Instead of modifying tool core logic, running `konman setup [tool-name]` drops target-specific metadata adapters into your project directory. Every adapter explicitly directs its assistant to look up instructions from a centralized, auto-compiled index file named `AGENTS.md`.

Setup commands generate configuration; they do not prove that a vendor application accepted or fired the hooks. Hook schemas and transcript paths change by tool/version. Confirm the generated files and test a real prompt with the host application before relying on capture. Konman does not sandbox agent file edits.

### 1. Antigravity Setup
Antigravity utilizes dynamic lifecycle event hooks and dynamic background JSON-RPC configurations.
* **Setup Command**: 
  ```bash
  konman setup antigravity
  ```
* **What it configures**: 
  Appends background server hooks directly to your system profile data (`~/.gemini/config/mcp_config.json`) and drops an event configuration module down at `.agents/hooks.json`.
* **Workflow**:
  When Antigravity invokes a configured hook, Konman stores a redacted event under `.context/.raw/`. Confirm hook events and payloads with your installed Antigravity version.

### 2. VS Code Copilot Setup
Agent-mode Copilot (preview) and Copilot CLI **do** run hooks. Inline completions and classic Copilot Chat do not.
* **Setup Command**: 
  ```bash
  konman setup vsc-copilot
  ```
* **What it configures**: 
  `.github/copilot-instructions.md` (read AGENTS.md) and `.github/hooks/konman.json` (`UserPromptSubmit`, `Stop`).
* **Workflow**:
  Agent sessions can capture events when the host invokes its hook. Classic Chat does not use these hooks; attempt transcript backfill where logs are available:
  ```bash
  konman backfill --source copilot
  ```

### 3. Cursor Setup
Cursor Agent chat exposes `beforeSubmitPrompt` (plus `sessionEnd` / `stop`).
* **Setup Command**: 
  ```bash
  konman setup cursor
  ```
* **What it configures**: 
  `.cursor/rules/konman-context.mdc` (`alwaysApply: true`) and merges capture entries into `.cursor/hooks.json` without wiping existing hooks.
* **Workflow**:
  Prompts can be captured when Cursor invokes the configured hook. Tab completions use a different surface and are not covered by this adapter.

### 4. Claude Code Setup
Claude Code is the cleanest capture path: labeled human `prompt` on `UserPromptSubmit`, plus `transcript_path` on every event.
* **Setup Command**: 
  ```bash
  konman setup claude-code
  ```
* **What it configures**: 
  `CLAUDE.md` (pointer to AGENTS.md) and merges hooks into `.claude/settings.json` for `UserPromptSubmit`, `Stop`, and `SessionEnd`.
* **Workflow**:
  Configured hooks capture events when Claude Code invokes them. Session JSONL locations vary by configuration; use `konman backfill --source claude-code` to check supported paths.

### 5. Codex Setup
Codex now has the same nested hook schema as Claude Code, plus JSONL rollouts on disk.
* **Setup Command**: 
  ```bash
  konman setup codex
  ```
* **What it configures**: 
  Merges capture hooks into `.codex/hooks.json` (`UserPromptSubmit`, `Stop`, `SessionEnd` with a 3s timeout).
* **Workflow**:
  Trust/enable hooks in the Codex CLI with `/hooks` where required. Use `konman backfill --source codex` to scan supported rollout paths.

### 6. Kiro Setup
Kiro IDE 1.x and CLI V3 load standalone hook files. Steering remains the static instruction channel.
* **Setup Command**: 
  ```bash
  konman setup kiro
  ```
* **What it configures**: 
  `.kiro/steering/context_steering.md` and `.kiro/hooks/konman.json` (`UserPromptSubmit`, `Stop`).
* **Workflow**:
  Kiro hook payloads and transcript paths vary by IDE/CLI version. Confirm the prompt event is received, then use `konman backfill --source kiro` for supported session files.

---

## 🛠️ Operational Command Reference

### 🎯 Core Workspace Management Commands

| Command | Syntax / Usage | Operational Description |
| :--- | :--- | :--- |
| **`init`** | `konman init` | Scaffolds the standard `.context/` data graph layout inside a code repository. |
| **`setup`** | `konman setup [tool-choice]` | Deploys targeted workspace adapters (`antigravity`, `claude-code`, `codex`, `vsc-copilot`, `cursor`, `kiro`). |
| **`sync`** | `konman sync` | Traces dependencies, processes staleness propagation rules, and regenerates `AGENTS.md`. |
| **`state`** | `konman state` | Renders a terminal visualization tree detailing active requirements, recent choices, and untracked queues. |
| **`record`** | `konman record -t [type] -i [id]` | Manually records a requirement, decision, boundary, evidence, change, question, risk, or object. IDs use `R`, `D`, `B`, `E`, `C`, `Q`, `X`, and `O` prefixes respectively. |
| **`resolve`** | `konman resolve [id] [--answer|--defer|--mitigate|--accept-risk|--close-risk]` | Reconciles stale decisions and resolves or tracks open questions and risks. |
| **`config`** | `konman config [-k key] [-p provider] [--api-format format] [--base-url url] [--model name] [--migrate] [--clear]` | Saves provider metadata in `~/.config/konman/config.json` and API keys in the OS credential store. |
| **`doc`** | `konman doc [--format markdown|pdf] [--output FILE]` | Generates a project context and specifications document from `.context/` as Markdown or PDF. |
| **`gui`** | `konman gui [--dir PROJECT] [--port PORT] [--no-browser]` | Launches the optional local Streamlit graph editor and context viewer. Install with `pip install "konman[gui]"`. |
| **`setup-hooks`** | `konman setup-hooks` | Installs an idempotent, marked validation block in Git's pre-commit hook while preserving other hook commands. |
| **`disable-hooks`** | `konman disable-hooks` | Removes only the marked Konman block; unrelated pre-commit hook content is preserved. |
| **`check`** | `konman check [--strict]` | Read-only schema/reference/staleness audit; `--strict` also fails on proposed nodes. Used by the optional pre-commit hook. |
| **`doctor`** | `konman doctor [--source name] [--check-api]` | Read-only environment, adapter, credential, and optional endpoint diagnostics. |
| **`review`** | `konman review [--id NODE_ID] [--approve|--reject] [--edit]` | Inspect and explicitly approve, edit, or reject any proposed context node. |

### 🔌 Context Extraction & Lifecycle Pipelines

| Command | Syntax / Usage | Operational Description |
| :--- | :--- | :--- |
| **`backfill`** | `konman backfill --source name [--source-path FILE] [--dry-run]` | Incrementally parses supported source transcripts with durable cursors; parser coverage is version-specific. |
| **`tail`** | `konman tail` | Deprecated Copilot-only alias for `backfill --source copilot`. |
| **`clean`** | `konman clean --older-than DAYS [--dry-run]` | Previews or explicitly removes old raw capture files. |
| **`mine`** | `konman mine -c [count]` | Captures local Git history and creates proposed Change and Evidence records for commits with explicit reasoning clues. |
| **`extract`** | `konman extract [--provider name] [--api-format format] [--model name] [--base-url url] [--type NODE_TYPE]` | Sends unprocessed captures to a supported provider API and writes quote-grounded `proposed` nodes for human review. Repeat `--type` to select multiple types: requirement, decision, boundary, evidence, change, question, risk, or object; by default all types are extracted. |
| **`handoff`** | `konman handoff [from] [to]` | Writes a context pack under `.context/state/history/` and configures the destination adapter. |
| **`mcp`** | `konman mcp [--dir project]` | Runs the read-only Konman MCP server over stdio with context, boundary, decision-search, and typed-node listing tools. |

`config` supports four request formats: `openai-compatible`, `anthropic`, `gemini`, and `ollama`. Known provider names select a default format and endpoint. For a custom endpoint, provide its API root URL and the format it implements. Konman does not support arbitrary provider-specific REST schemas. Anthropic and Gemini configurations require an explicit model; Ollama works locally without an API key. Keys are stored in the OS credential store when available; existing plaintext keys must be explicitly migrated.

Generate a project context document in Markdown (the default) or PDF:

```bash
konman doc
konman doc --format markdown --output docs/project-context.md
```

The default file path is `.context/context-document.<format>`. PDF support is optional; install it with `pip install "konman[pdf]"`, then use:

```bash
konman doc --format pdf --output docs/project-context.pdf
```

The document includes the project overview, all node types, protected boundaries, and current state. It excludes raw captures and internal extraction metadata.

### Context node types and lifecycle

Konman stores these records as linked context rather than treating all notes as interchangeable:

- **Object (`O`)**: a named component, technology, service, or other entity, with properties.
- **Evidence (`E`)**: a source locator and excerpt supporting one or more context claims.
- **Change (`C`)**: an implementation change, optionally linked to decisions, requirements, files, and verification.
- **Question (`Q`)**: an unresolved information gap that can be answered or deferred.
- **Risk (`X`)**: a possible adverse outcome with likelihood, impact, mitigation, and resolution.

All node types can be added manually with `konman record` or proposed from captured context with `konman extract`. Proposed records stay inactive until reviewed. Use `konman review` to list proposals, then approve, edit, or reject by ID:

```bash
konman record --type object --id O-001
konman extract --type evidence --type risk
konman review
konman review --id E-001 --approve
konman resolve Q-001 --answer "The API must remain backward compatible."
konman resolve X-001 --mitigate "Add a compatibility test before release."
konman check --strict
```

Evidence IDs use `E-001`, changes `C-001`, questions `Q-001`, risks `X-001`, and tracked objects `O-001`. Requirements, decisions, and boundaries use `R`, `D`, and `B` prefixes. Run `konman record --help` and `konman resolve --help` for required fields and lifecycle options.

Examples:

```bash
# Known hosted providers select their API format and endpoint automatically.
konman config --api-key "$ANTHROPIC_API_KEY" --provider anthropic --model "$ANTHROPIC_MODEL"
konman config --api-key "$GEMINI_API_KEY" --provider gemini --model "$GEMINI_MODEL"
konman config --api-key "$GROQ_API_KEY" --provider groq --model "$GROQ_MODEL"

# Configure any custom endpoint that implements a supported API format.
konman config --api-key "$LLM_API_KEY" --provider my-provider --api-format openai-compatible --base-url https://llm.example/v1 --model my-model
```

Select the context types requested from the model by specifying one or more `--type` options. Supported types are requirements, decisions, boundaries, evidence, changes, questions, risks, and objects. Quote-backed evidence records are also saved as provenance when extracting another type. Without the option, extraction requests all supported types.

```bash
konman extract --type requirement
konman extract --type decision --type risk
```

```bash
# Local Ollama does not require an API key.
konman config --provider ollama --model llama3.2
konman extract
konman doctor --check-api
konman review
```

With no arguments, `konman config` displays saved non-secret settings. Use `konman config --migrate` for legacy plaintext settings and `konman config --clear` to remove configuration. `konman extract` uses saved settings or one-off `--provider`, `--api-format`, `--base-url`, `--model`, and `--api-key` values. `KONMAN_API_KEY` and `KONMAN_BASE_URL` are supported; `OPENAI_API_KEY` and `OPENAI_BASE_URL` remain aliases. When changing to a different provider with `konman config --provider`, supply that provider's required credentials and any custom endpoint or API format; settings from the previous provider are not inherited. Omitting `--provider` or updating the currently configured provider preserves its saved settings. Extraction results stay `proposed` until approved with `konman review`; use `konman review` to list proposals and `konman review --id B-001` to inspect a boundary proposal.

Raw transcript data is sensitive. Konman applies best-effort credential-pattern redaction before capture and upload, but this is not a guarantee that all secrets or personal data are detected. Inspect captures and use `konman clean` for explicit retention cleanup. Add project-specific patterns to `.context/manifest.yaml`:

```yaml
redaction:
  patterns:
    - '(?i)internal-token-[A-Za-z0-9]+'
```

Review the full limitations below before enabling capture for a team.

Run `konman --help` for command forms and common examples, or `konman COMMAND --help` for a command's options. Setup subcommands also have dedicated help, for example `konman setup claude-code --help`.

---

## 🔒 Enforcement Guardrails & Git Lifecycles

To catch invalid or stale context locally, embed **konman** in the repository's Git workflow. This is a developer convenience, not a security boundary; hooks can be bypassed or omitted in other worktrees and CI environments.

### Activating the Protection Guardrail:
Run this command inside your target codebase application directory:
```bash
konman setup-hooks
```
This adds a marked block to the active pre-commit hook and executes read-only `konman check`. Stale dependencies are detected at check time without requiring `sync`. Resolve flagged decisions with `konman resolve [id]`; use `konman review` separately for proposed extraction nodes.

### Opting Out / Disabling the Guardrail:
If you need to lift the validation gates for temporary testing cycles, bypass the pre-commit checks, or remove **konman** from your automated lifecycle track, execute the decoupling unlinker:
```bash
konman disable-hooks
```
This removes only Konman's marked block and preserves unrelated hook commands.

## Alpha Limitations

- Hook formats, transcript locations, and tool behavior vary by vendor and version. Adapters and parsers need validation with the exact host application; a generated file does not prove a hook fired.
- Transcript parsers cover known layouts, not every release or account configuration. `backfill --source` reports parsed/failed counts; inspect the result before relying on it.
- Redaction uses patterns and can miss credentials, personal information, or proprietary text. It is best-effort, not a data-loss-prevention system.
- Extraction is model-assisted and may omit, misunderstand, or duplicate context. Results remain proposed until a human reviews them; quotes establish textual provenance, not truth.
- The configured provider receives redacted transcript excerpts during `extract`. Review the selected provider's retention and data-use policies before use.
- Git hooks and AGENTS instructions are advisory local safeguards, not sandboxing or access control.
- Alpha testing has not validated every adapter or provider against a live vendor environment. Please report tool name/version, OS, and sanitized diagnostics when filing issues; do not attach raw prompts or credentials.
