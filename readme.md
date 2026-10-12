# 🧠 konman (Context Manager) v1.0.0

An automated, first-principles, LLM-agnostic codebase context engine. **konman** decouples developer context from ephemeral chat sessions and anchors it directly inside your codebase as version-controlled data. 

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

### 1. Assemble the Package Dependencies
Ensure you have Python 3.10+ installed. Clone your workspace and install **konman** globally in editable mode using `pip`:

```bash
cd conman_tool
pip install -e .
```

Verify your global environment configuration setup by triggering the structured help display:
```bash
konman --help
```

### 2. Scaffold a Codebase Repository
Navigate into your target software application codebase folder (e.g., `playce-api`) and initialize the context filesystem:
```bash
cd /path/to/playce-api
konman init
```
This deploys the underlying `.context/` data graph infrastructure:
* `requirements/`: `.yaml` files detailing hard structural limitations and developer preferences.
* `decisions/`: Architectural tradeoffs, chosen technologies, and rejected alternative options.
* `boundaries.yaml`: Protected codebase paths mapped to explicit verification criteria.
* `.raw/`: Gitignored temporary buffer cache where streaming logs are collected prior to model extraction.

---

## 🔌 Multi-Tool Setup & Integration Manual

**konman** is built to sit between you and your developer assistants. Instead of modifying tool core logic, running `konman setup [tool-name]` drops target-specific metadata adapters into your project directory. Every adapter explicitly directs its assistant to look up instructions from a centralized, auto-compiled index file named `AGENTS.md`.

### 1. Antigravity Setup
Antigravity utilizes dynamic lifecycle event hooks and dynamic background JSON-RPC configurations.
* **Setup Command**: 
  ```bash
  konman setup antigravity
  ```
* **What it configures**: 
  Appends background server hooks directly to your system profile data (`~/.gemini/config/mcp_config.json`) and drops an event configuration module down at `.agents/hooks.json`.
* **Workflow**: 
  Every time you submit a prompt or close a chat panel shell inside Antigravity, the tool pipes background conversation logs straight to `.context/.raw/` silently using an insulated, fail-open background channel.

### 2. VS Code Copilot Setup
VS Code Copilot blocks background lifecycle execution commands but natively queries structural instruction parameters.
* **Setup Command**: 
  ```bash
  konman setup vsc-copilot
  ```
* **What it configures**: 
  Creates a workspace routing directory at `.github/copilot-instructions.md`.
* **Workflow**: 
  Because Copilot restricts third-party process eavesdropping, use the continuous window cache scraping utility to pull past conversation prompts from your system log directory:
  ```bash
  konman tail
  ```

### 3. Cursor Setup
Cursor allows developers to enforce custom system guidelines over matching codebase directory modules.
* **Setup Command**: 
  ```bash
  konman setup cursor
  ```
* **What it configures**: 
  Generates a system override rule file at `.cursor/rules/konman-context.mdc`.
* **Workflow**: 
  The file is pre-configured with rules (`alwaysApply: true`, `globs: "*"`) that force the Cursor model to crawl `AGENTS.md` boundaries before proposing code modifications.

### 4. Claude Code Setup
Claude Code looks up structural constraints from plain markdown files situated in the repository root path.
* **Setup Command**: 
  ```bash
  konman setup claude-code
  ```
* **What it configures**: 
  Creates a standard `CLAUDE.md` control file.
* **Workflow**: 
  It defines absolute constraints, instructing the Claude Code terminal runner to scan your active requirements schema before running build scripts or code rewrites.

### 5. Codex Setup
Codex tracks state parameters across isolated session tracking layouts.
* **Setup Command**: 
  ```bash
  konman setup codex
  ```
* **What it configures**: 
  Deploys a standard workspace tracker layout at `.codex/`.

### 6. Kiro Setup
Kiro relies on system steering inputs to orchestrate background model automation scripts.
* **Setup Command**: 
  ```bash
  konman setup kiro
  ```
* **What it configures**: 
  Deploys explicit semantic steering files to `.kiro/steering/context_steering.md`.

---

## 🛠️ Operational Command Reference

### 🎯 Core Workspace Management Commands

| Command | Syntax / Usage | Operational Description |
| :--- | :--- | :--- |
| **`init`** | `konman init` | Scaffolds the standard `.context/` data graph layout inside a code repository. |
| **`setup`** | `konman setup [tool-choice]` | Deploys targeted workspace adapters (`antigravity`, `claude-code`, `codex`, `vsc-copilot`, `cursor`, `kiro`). |
| **`sync`** | `konman sync` | Traces dependencies, processes staleness propagation rules, and regenerates `AGENTS.md`. |
| **`state`** | `konman state` | Renders a terminal visualization tree detailing active requirements, recent choices, and untracked queues. |
| **`record`** | `konman record -t [type] -i [id]` | Launches an interactive console wizard to manually log a new `requirement`, `decision`, or `boundary`. |
| **`resolve`** | `konman resolve [id]` | Reconciles stale nodes flagged with `needs_review`, updating trade-off justifications and healing the graph. |
| **`check`** | `konman check` | Audits the graph database. Returns error code `1` if any node requires review. Used as a pre-commit block. |
| **`config`** | `konman config -k [key]` | Securely locks your developer LLM platform API key credentials to `~/.config/konman/config.json`. |
| **`setup-hooks`** | `konman setup-hooks` | Injects an automated verification shell script loop directly into your local `.git/hooks/pre-commit` workflow. |
| **`disable-hooks`** | `konman disable-hooks` | Safely tears down and decouples the konman validation script from your local Git pre-commit lifecycles. |

### 🔌 Context Extraction & Lifecycle Pipelines

| Command | Syntax / Usage | Operational Description |
| :--- | :--- | :--- |
| **`tail`** | `konman tail` | Scrapes deeply nested Windows VS Code cache paths to pull your active Copilot transcript history. |
| **`mine`** | `konman mine -c [count]` | Parses your local Git commit history trail to extract structural reasoning clues from message text blocks. |
| **`extract`** | `konman extract` | Pipes collected logs from `.context/.raw/` into your LLM to automatically synthesize fresh `.yaml` nodes. |
| **`handoff`** | `konman handoff [from] [to]` | Packages context boundaries for a new model window and updates active adapters to point to the new tool. |

---

## 🔒 Enforcement Guardrails & Git Lifecycles

To guarantee that stale information or unconfirmed context models are caught before code is pushed to a remote server, embed **konman** directly into your repository's local Git workflow gates.

### Activating the Protection Guardrail:
Run this command inside your target codebase application directory:
```bash
konman setup-hooks
```
This creates an automated shell script at `.git/hooks/pre-commit` that intercepts every `git commit` attempt to execute `konman check`. If an upstream requirement has been `superseded` or changed, all down-tree decisions automatically lock into a `needs_review` phase, and **konman blocks the commit sequence**. Run `konman resolve [id]` to input your updated tradeoffs and unblock the pipeline instantly.

### Opting Out / Disabling the Guardrail:
If you need to lift the validation gates for temporary testing cycles, bypass the pre-commit checks, or remove **konman** from your automated lifecycle track, execute the decoupling unlinker:
```bash
konman disable-hooks
```
This safely inspects the pre-commit script file and destroys the execution hooks without risking damage to third-party tools or modifications to your untracked source directories.
