import sys
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import uuid
import getpass
import importlib.util
import click
from pathlib import Path
from datetime import datetime
from ruamel.yaml import YAML
from konman import __version__
from konman.engine import ContextEngine
from konman.context_graph import CONTEXT_NODE_CONFIG
from konman.documentation import render_context_markdown, write_markdown, write_pdf
from konman.models import (
    BoundaryRule, Change, ContextObject, Decision, Evidence, Question, Requirement, Risk,
)
from konman.redaction import redact_text, redact_value
from konman.storage import atomic_write_json, atomic_write_text, atomic_write_yaml, create_new_bytes, is_raw_ignored
from konman.transcripts import SOURCES, discover_paths, parse_record
from konman.config import (
    API_FORMATS,
    inject_antigravity_hooks, inject_claude_code_adapters, inject_codex_adapters,
    inject_vsc_copilot_adapters, inject_cursor_adapters, inject_kiro_adapters,
    resolve_llm_configuration, save_global_api_credentials, load_global_api_credentials,
    clear_global_api_credentials, migrate_legacy_credentials
)

EXTRACT_NODE_TYPES = tuple(CONTEXT_NODE_CONFIG)

class ConmanTopLevelGroup(click.Group):
    def format_help(self, ctx, formatter):
        formatter.write_usage(ctx.command_path, "[OPTIONS] COMMAND [ARGS]...")
        formatter.write_paragraph()
        formatter.write_text(
            "konman: repository-owned project context for AI development. "
            "For command options, run: konman <command> --help."
        )

        def usage(command, name, parent_ctx):
            command_ctx = click.Context(command, info_name=name, parent=parent_ctx)
            return command.get_usage(command_ctx).removeprefix("Usage: ")

        commands = self.list_commands(ctx)
        core_cmds = [c for c in commands if c in ["init", "setup", "sync", "state", "record", "resolve", "review", "doctor", "check", "config", "doc", "gui", "setup-hooks", "disable-hooks"]]
        pipe_cmds = [c for c in commands if c in ["backfill", "tail", "clean", "mine", "extract", "handoff", "hook", "mcp"]]

        if core_cmds:
            with formatter.section("Core Workspace Management Commands"):
                formatter.write_dl([
                    (usage(self.get_command(ctx, name), name, ctx), self.get_command(ctx, name).get_short_help_str())
                    for name in core_cmds
                ])
                setup = self.get_command(ctx, "setup")
                setup_ctx = click.Context(setup, info_name="setup", parent=ctx)
                formatter.write_text("Setup adapters:")
                formatter.write_dl([
                    (usage(setup.get_command(setup_ctx, name), f"setup {name}", ctx), setup.get_command(setup_ctx, name).get_short_help_str())
                    for name in setup.list_commands(setup_ctx)
                ])
        if pipe_cmds:
            with formatter.section("Context Extraction & Lifecycle Pipelines"):
                formatter.write_dl([
                    (usage(self.get_command(ctx, name), name, ctx), self.get_command(ctx, name).get_short_help_str())
                    for name in pipe_cmds
                ])
        formatter.write_paragraph()
        formatter.write_text("Examples:")
        formatter.write_dl([
            ("", "konman init --dir ."),
            ("", "konman setup claude-code --dir ."),
            ("", "konman record --type risk --id X-001"),
            ("", "konman config --api-key <key> --provider anthropic --model <model>"),
            ("", "konman config --provider custom --api-format openai-compatible --base-url <url> --api-key <key> --model <model>"),
            ("", "konman doc --format markdown"),
            ("", "konman gui --dir ."),
            ("", "konman config --provider ollama --model <model>"),
            ("", "konman extract --help"),
            ("", "konman handoff claude-code codex --dir ."),
            ("", "konman mcp --dir ."),
        ])
        click.Command.format_options(self, ctx, formatter)

@click.group(cls=ConmanTopLevelGroup)
def main():
    """konman (Context Manager): Automated, LLM-Agnostic Context Mapping Engine."""
    pass

@main.command()
@click.option("--dir", default=".", help="Target project root directory location.")
def init(dir):
    """Scaffold a new .context data graph directory inside a code repository."""
    engine = ContextEngine(dir)
    engine.init_folders()
    click.echo(f"Initialized .context folder array framework inside: {engine.base_dir}")


@main.command()
@click.option("--dir", default=".", help="Project root directory to visualize and edit.")
@click.option("--port", type=click.IntRange(1, 65535), default=8501, show_default=True, help="Local web server port.")
@click.option("--no-browser", is_flag=True, help="Start the local UI without opening a browser.")
def gui(dir, port, no_browser):
    """Launch the local interactive context graph editor."""
    missing = [module for module in ("streamlit", "streamlit_flow") if importlib.util.find_spec(module) is None]
    if missing:
        raise click.ClickException(
            "The GUI dependencies are not installed. Install them with `pip install \"konman[gui]\"`."
        )
    from konman.gui_app import __file__ as app_path

    engine = ContextEngine(dir)
    command = [
        sys.executable, "-m", "streamlit", "run",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        f"--server.headless={'true' if no_browser else 'false'}",
        "--browser.gatherUsageStats=false",
        str(Path(app_path).resolve()),
        "--",
        "--dir", str(engine.base_dir),
    ]
    click.echo(f"Starting Konman GUI at http://127.0.0.1:{port} for {engine.base_dir}")
    try:
        result = subprocess.run(command, cwd=engine.base_dir, check=False)
    except OSError as error:
        raise click.ClickException(f"Could not start Streamlit: {error}") from error
    if result.returncode:
        raise click.exceptions.Exit(result.returncode)


@main.group(name="setup")
def setup_group():
    """Inject specialized adapter workspace configurations for your preferred dev tool."""
    pass


def _apply_adapter(injector, target_dir):
    try:
        return injector(target_dir)
    except (OSError, ValueError) as error:
        raise click.ClickException(f"Adapter setup failed without replacing existing configuration: {error}") from error

@setup_group.command(name="antigravity")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_antigravity(dir):
    """Inject background tracking hooks and local server pointers into Antigravity configurations."""
    engine = ContextEngine(dir)
    engine.init_folders()
    for note in _apply_adapter(inject_antigravity_hooks, dir):
        click.echo(f"  {note}")
    engine.compile_agents_md()
    click.echo("Injected system bindings across Antigravity successfully.")

@setup_group.command(name="claude-code")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_claude_code(dir):
    """Generate localized CLAUDE.md routing pointers for Claude Code CLI."""
    engine = ContextEngine(dir)
    engine.init_folders()
    for note in _apply_adapter(inject_claude_code_adapters, dir):
        click.echo(f"  {note}")
    engine.compile_agents_md()
    click.echo("Injected system bindings across Claude Code successfully.")

@setup_group.command(name="codex")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_codex(dir):
    """Deploy workspace directory tracking layouts matching Codex specification tracks."""
    engine = ContextEngine(dir)
    engine.init_folders()
    for note in _apply_adapter(inject_codex_adapters, dir):
        click.echo(f"  {note}")
    engine.compile_agents_md()
    click.echo("Injected system bindings across Codex successfully.")

@setup_group.command(name="vsc-copilot")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_vsc_copilot(dir):
    """Generate .github/copilot-instructions.md configuration files for VS Code Copilot."""
    engine = ContextEngine(dir)
    engine.init_folders()
    for note in _apply_adapter(inject_vsc_copilot_adapters, dir):
        click.echo(f"  {note}")
    engine.compile_agents_md()
    click.echo("Injected system bindings across VS Code Copilot successfully.")

@setup_group.command(name="cursor")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_cursor(dir):
    """Generate .cursor/rules/ global metadata adapters for Cursor IDE."""
    engine = ContextEngine(dir)
    engine.init_folders()
    for note in _apply_adapter(inject_cursor_adapters, dir):
        click.echo(f"  {note}")
    engine.compile_agents_md()
    click.echo("Injected system bindings across Cursor successfully.")

@setup_group.command(name="kiro")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_kiro(dir):
    """Deploy workspace directory configurations for Kiro agent steering engines."""
    engine = ContextEngine(dir)
    engine.init_folders()
    for note in _apply_adapter(inject_kiro_adapters, dir):
        click.echo(f"  {note}")
    engine.compile_agents_md()
    click.echo("Injected system bindings across Kiro successfully.")

@main.command()
@click.option("--dir", default=".", help="Target project root directory location.")
def sync(dir):
    """Force cross-dependency checks, process structural changes, and refresh AGENTS.md."""
    engine = ContextEngine(dir)
    stale_updates = engine.process_staleness_propagation()
    engine.compile_agents_md()
    click.echo(f"Graph database synchronization complete. Flagged {stale_updates} decisions for review updates.")

@main.command()
@click.option("--dir", default=".", help="Target project root directory location.")
@click.option("--strict", is_flag=True, help="Also fail when proposed nodes await review.")
def check(dir, strict):
    """Read-only audit of schemas, references, boundaries, and stale decisions."""
    engine = ContextEngine(dir)
    violations = engine.check_graph_validity(strict=strict)
    if violations:
        click.echo(" CONTEXT INTEGRITY VALIDATION FAILED:")
        for v in violations:
            click.echo(f" {v}")
        sys.exit(1)
    click.echo("Context mapping validated. No unresolved structural anomalies located.")
    sys.exit(0)


@main.command()
@click.option("--dir", default=".", help="Target project root directory location.")
@click.option("--source", type=click.Choice(SOURCES), help="Check transcript discovery for one source.")
@click.option("--check-api", is_flag=True, help="Perform a short network reachability probe for the configured API.")
def doctor(dir, source, check_api):
    """Read-only diagnostics for project data, adapters, tools, and LLM config."""
    engine = ContextEngine(dir)
    failures = 0
    warnings = 0

    def report(level, label, detail):
        nonlocal failures, warnings
        failures += level == "FAIL"
        warnings += level == "WARN"
        click.echo(f"[{level}] {label}: {detail}")

    report("PASS", "Python", sys.version.split()[0])
    report("PASS", "Project root", str(engine.base_dir))
    if not engine.ctx_dir.is_dir():
        report("FAIL", "Context", "missing .context; run `konman init`")
    else:
        report("PASS", "Context", ".context directory found")
        for folder in ("requirements", "decisions", ".raw", "state"):
            path = engine.ctx_dir / folder
            if path.is_dir():
                report("PASS" if os.access(path, os.W_OK) else "FAIL", f".context/{folder}", "directory found and writable" if os.access(path, os.W_OK) else "directory is not writable")
            else:
                report("FAIL", f".context/{folder}", "directory missing")
        try:
            violations = engine.check_graph_validity()
            if violations:
                report("FAIL", "Graph", f"{len(violations)} check(s) failed")
                for violation in violations:
                    click.echo(f"       {violation}")
            else:
                report("PASS", "Graph", "schema and dependency checks passed")
        except Exception as error:
            report("FAIL", "Graph", str(error))

    if is_raw_ignored(engine.base_dir):
        report("PASS", "Raw data ignore", ".context/.raw is ignored")
    else:
        report("FAIL", "Raw data ignore", "raw prompts may be staged; run `konman init` to add the ignore rule")

    manifest_path = engine.ctx_dir / "manifest.yaml"
    if manifest_path.exists():
        try:
            manifest = YAML().load(manifest_path.read_text(encoding="utf-8")) or {}
            redaction = manifest.get("redaction", {}) if isinstance(manifest, dict) else {}
            patterns = redaction.get("patterns", []) if isinstance(redaction, dict) else []
            if not isinstance(patterns, list) or any(not isinstance(pattern, str) for pattern in patterns):
                raise ValueError("redaction.patterns must be a list of regular expressions")
            for pattern in patterns:
                re.compile(pattern)
            report("PASS", "Redaction patterns", f"{len(patterns)} custom pattern(s) valid")
        except Exception as error:
            report("FAIL", "Redaction patterns", str(error))

    adapter_paths = {
        "antigravity": engine.base_dir / ".agents" / "hooks.json",
        "claude-code": engine.base_dir / ".claude" / "settings.json",
        "codex": engine.base_dir / ".codex" / "hooks.json",
        "vsc-copilot": engine.base_dir / ".github" / "hooks" / "konman.json",
        "cursor": engine.base_dir / ".cursor" / "hooks.json",
        "kiro": engine.base_dir / ".kiro" / "hooks" / "konman.json",
    }
    for name, path in adapter_paths.items():
        if not path.exists():
            report("WARN", f"Adapter {name}", "not configured")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
            report("PASS", f"Adapter {name}", "config parses; hook runtime has not been verified")
        except (OSError, json.JSONDecodeError) as error:
            report("FAIL", f"Adapter {name}", f"invalid JSON: {error}")

    if shutil.which("konman"):
        report("PASS", "Konman executable", shutil.which("konman"))
    else:
        report("WARN", "Konman executable", "console command is not on PATH; pre-commit hook may not find it")
    executables = {"claude-code": "claude", "codex": "codex", "vsc-copilot": "code", "cursor": "cursor", "kiro": "kiro", "antigravity": "agy"}
    if source:
        try:
            paths = discover_paths(source)
            report("PASS" if paths else "WARN", f"Transcript {source}", f"found {len(paths)} candidate file(s); parser compatibility is version-specific")
        except Exception as error:
            report("WARN", f"Transcript {source}", str(error))
    for adapter, executable in executables.items():
        if adapter_paths[adapter].exists() and not shutil.which(executable):
            report("WARN", f"Tool {adapter}", f"'{executable}' is not on PATH; config presence does not prove hook support")

    config = load_global_api_credentials() or {}
    if config.get("config_error"):
        report("FAIL", "LLM configuration", config["config_error"])
    elif config.get("provider"):
        report("PASS", "LLM provider", f"{config.get('provider')} / {config.get('api_format', 'openai-compatible')} / {config.get('model', '(model not set)')}")
        try:
            resolve_llm_configuration(config.get("provider"), config.get("api_format"), config.get("base_url"))
        except (ValueError, AttributeError) as error:
            report("FAIL", "LLM settings", str(error))
        if config.get("api_format") != "ollama" and not (config.get("api_key") or os.environ.get("KONMAN_API_KEY") or os.environ.get("OPENAI_API_KEY")):
            if config.get("legacy_plaintext_credential"):
                report("WARN", "LLM credential", "legacy plaintext key detected; run `konman config --migrate`")
            else:
                report("FAIL", "LLM credential", config.get("credential_error", "credential unavailable"))
        elif config.get("api_format") == "ollama":
            report("PASS", "LLM credential", "not required for Ollama")
        else:
            report("PASS", "LLM credential", "available; value not displayed")
        if check_api:
            try:
                request = urllib.request.Request(config["base_url"], method="HEAD")
                with urllib.request.urlopen(request, timeout=8):
                    pass
                report("PASS", "LLM endpoint", "reachable")
            except urllib.error.HTTPError as error:
                level = "WARN" if error.code < 500 else "FAIL"
                report(level, "LLM endpoint", f"reachable; server returned HTTP {error.code}")
            except Exception as error:
                report("FAIL", "LLM endpoint", f"unreachable: {error}")
    else:
        report("WARN", "LLM provider", "not configured")

    try:
        hook_path = _pre_commit_path(engine.base_dir)
        if hook_path.exists():
            hook_text = hook_path.read_text(encoding="utf-8", errors="replace")
            report("PASS" if "# >>> konman managed pre-commit" in hook_text else "WARN", "Git hook", str(hook_path))
        else:
            report("WARN", "Git hook", "no pre-commit hook installed")
    except (OSError, subprocess.CalledProcessError):
        report("WARN", "Git hook", "project is not inside a Git repository")

    click.echo(f"Doctor finished: {failures} failure(s), {warnings} warning(s).")
    if failures:
        raise click.exceptions.Exit(1)

@main.command()
@click.option("--dir", default=".", help="Target project root directory location.")
def state(dir):
    """Render an interactive high-level dashboard map of current codebase architectural contexts."""
    engine = ContextEngine(dir)
    yaml = YAML()
    if not engine.ctx_dir.exists():
        click.echo("No context database found in this workspace directory. Run 'konman init' first.")
        return

    click.echo("\n======================================================================")
    click.echo(f"KONMAN CONTEXT DATABASE STATUS MATRIX: {engine.base_dir.name.upper()}")
    click.echo("======================================================================\n")

    click.echo("ACTIVE SYSTEM ARCHITECTURAL REQUIREMENTS:")
    req_dir = engine.ctx_dir / "requirements"
    has_reqs = False
    if req_dir.exists():
        for p in req_dir.glob("*.yaml"):
            with open(p, "r", encoding="utf-8") as f:
                r = yaml.load(f)
                if r and r.get("status") == "active":
                    has_reqs = True
                    click.echo(f"  ├─ {r.get('id')} [{str(r.get('kind') or 'UNKNOWN').upper()}]: {r.get('statement')}")
                    if r.get("why"):
                        click.echo(f"  │  └── Why: {r.get('why')}")
    if not has_reqs:
        click.echo("  └─ (No active requirements mapped to this repository yet)")

    click.echo("\n RECENT ARCHITECTURAL TRADEOFF DECISIONS:")
    dec_dir = engine.ctx_dir / "decisions"
    has_decs = False
    if dec_dir.exists():
        for p in dec_dir.glob("*.yaml"):
            with open(p, "r", encoding="utf-8") as f:
                d = yaml.load(f)
                if d:
                    has_decs = True
                    status = str(d.get("status") or "unknown")
                    status_indicator = f" [{status.upper()}]"
                    click.echo(f"  ├─ {d.get('id')} Chosen: {str(d.get('chosen') or 'UNKNOWN').upper()} -- {status_indicator}")
                    if d.get("reason"):
                        click.echo(f"  │  ├── Rationale: {d.get('reason')}")
                    rejected_opts = [c.get("object") for c in d.get("considered", []) if c.get("verdict") == "rejected"]
                    if rejected_opts:
                        click.echo(f"  │  └──  Rejected Options: {', '.join(rejected_opts)}")
    if not has_decs:
        click.echo("  └─ (No architectural tradeoff items logged in database layout)")

    for folder, title, statuses, default_status, field in (
        ("objects", "TRACKED OBJECTS", {"active"}, "active", "name"),
        ("evidence", "EVIDENCE", {"active"}, "active", "excerpt"),
        ("changes", "RECORDED CHANGES", {"active"}, "proposed", "summary"),
        ("questions", "OPEN QUESTIONS", {"open", "deferred"}, "open", "question"),
        ("risks", "RISK REGISTER", {"open", "mitigated", "accepted"}, "open", "statement"),
    ):
        directory = engine.ctx_dir / folder
        records = []
        if directory.is_dir():
            for path in sorted(directory.glob("*.yaml")):
                node = yaml.load(path.read_text(encoding="utf-8"))
                if node and node.get("status", default_status) in statuses:
                    records.append(node)
        click.echo(f"\n{title}:")
        if records:
            for node in records:
                status = str(node.get("status", default_status)).upper()
                click.echo(f"  ├─ {node.get('id')} [{status}]: {node.get(field) or '(no summary)'}")
        else:
            click.echo("  └─ (None)")

    click.echo("\n🔌 UNTRACKED BACKGROUND DATA CAPTURE QUEUE:")
    raw_dir = engine.ctx_dir / ".raw"
    untracked_files = [f.name for f in raw_dir.iterdir() if f.is_file()] if raw_dir.exists() else []
    if untracked_files:
        click.echo(f"   [PENDING] There are {len(untracked_files)} raw context history log packet files waiting.")
        click.echo("      Run 'konman extract' to automatically parse and promote them to your database.")
    else:
        click.echo("  No untracked history data packets currently idling inside your background raw queue pipes.")
    click.echo("\n======================================================================\n")


@main.command(name="doc")
@click.option("--dir", default=".", help="Target project root directory location.")
@click.option("--format", "doc_format", type=click.Choice(["markdown", "pdf"]), default="markdown", show_default=True, help="Documentation output format.")
@click.option("--output", type=click.Path(path_type=Path, dir_okay=False), help="Output file path; defaults to .context/context-document.<format>.")
def doc(dir, doc_format, output):
    """Generate Markdown or PDF documentation from project context and specifications."""
    engine = ContextEngine(dir)
    try:
        markdown = render_context_markdown(engine)
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error)) from error

    extension = "md" if doc_format == "markdown" else "pdf"
    output_path = output or (engine.ctx_dir / f"context-document.{extension}")
    if not output_path.is_absolute():
        output_path = engine.base_dir / output_path
    try:
        if doc_format == "markdown":
            write_markdown(markdown, output_path)
        else:
            write_pdf(markdown, output_path)
    except (OSError, RuntimeError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(f" Project context documentation written to {output_path}.")


@main.command()
@click.option("--type", "-t", required=True, type=click.Choice(EXTRACT_NODE_TYPES), help="The type of context entity to create.")
@click.option("--id", "-i", required=True, help="Unique identifier using the type prefix (R, D, B, E, C, Q, X, or O).")
@click.option("--dir", default=".", help="Target project root directory location.")
def record(type, id, dir):
    """Manually record a context entity in the data graph."""
    engine = ContextEngine(dir)
    engine.init_folders()
    yaml = YAML()
    yaml.preserve_quotes = True
    timestamp = datetime.now().strftime("%Y-%m-%d")
    expected_prefix = CONTEXT_NODE_CONFIG[type][0]
    if not re.fullmatch(rf"{expected_prefix}-\d+", id):
        raise click.BadParameter(f"{type} IDs must use the form {expected_prefix}-001.", param_hint="--id")

    if type == "requirement":
        statement = click.prompt(" Enter the core Requirement statement")
        kind = click.prompt("  Kind", type=click.Choice(["hard", "preference"]), default="hard")
        why = click.prompt(" Why is this requirement needed?", default="")
        payload = {"id": id, "statement": statement, "kind": kind, "priority": "high" if kind == "hard" else "medium", "source": {"who": "human:dev", "when": timestamp}, "why": why if why else None, "evidence_ids": _prompt_reference_list("Evidence IDs (comma-separated, optional)"), "status": "active"}
        target_path = engine.ctx_dir / "requirements" / f"{id}.yaml"
    elif type == "decision":
        chosen = click.prompt(" Chosen candidate/object name")
        chosen_object_id = click.prompt(" Tracked object ID (optional)", default="") or None
        mode = click.prompt("  Decision mode", type=click.Choice(["compared", "default", "forced", "taste"]), default="compared")
        reason = click.prompt(" Reason or tradeoff summary", default="")
        considered = []
        if mode == "compared":
            while click.confirm(" Would you like to record a rejected alternative option?"):
                alt_name = click.prompt(" Rejected object/technology name")
                fail_prop = click.prompt(f" Which property caused {alt_name} to fail?")
                fail_req = click.prompt(f" Which Requirement ID did it violate?")
                considered.append({"object": alt_name, "properties": [{"key": fail_prop, "value": True, "evidence": "documented"}], "evaluations": [{"req": fail_req, "result": "fail", "via": fail_prop}], "verdict": "rejected"})
        considered.append({"object": chosen, "object_id": chosen_object_id, "properties": [], "evaluations": [], "verdict": "selected"})
        payload = {"id": id, "chosen": chosen, "mode": mode, "decided": {"who": "human:dev", "when": timestamp}, "considered": considered, "reason": reason if reason else None, "evidence_ids": _prompt_reference_list("Evidence IDs (comma-separated, optional)"), "status": "active"}
        target_path = engine.ctx_dir / "decisions" / f"{id}.yaml"
    elif type == "boundary":
        path_str = click.prompt(" Enter the codebase file path to protect")
        why = click.prompt(" Why must this boundary be enforced?", default="")
        target_path = engine.ctx_dir / "boundaries.yaml"
        boundaries = []
        if target_path.exists():
            try:
                existing = yaml.load(target_path.read_text(encoding="utf-8")) or []
            except Exception as error:
                raise click.ClickException(f"Cannot read existing boundaries.yaml: {error}") from error
            boundaries = [existing] if isinstance(existing, dict) else existing
            if not isinstance(boundaries, list):
                raise click.ClickException("boundaries.yaml must contain a list or mapping.")
        if any(isinstance(item, dict) and (item.get("id") == id or item.get("path") == path_str) for item in boundaries):
            raise click.ClickException(f"Boundary ID '{id}' or path '{path_str}' already exists.")
        boundaries.append({"id": id, "path": path_str, "rule": "no_edit_without_approval", "why": why or None, "constrains": [], "evidence_ids": _prompt_reference_list("Evidence IDs (comma-separated, optional)")})
        payload = boundaries
    elif type == "evidence":
        source_type = click.prompt(
            " Evidence source type",
            type=click.Choice(["human", "transcript", "commit", "document", "issue", "test", "other"]),
            default="human",
        )
        locator = click.prompt(" Source locator (URL, commit, file, or event ID)", default="") or None
        excerpt = click.prompt(" Verbatim evidence excerpt")
        payload = {
            "id": id, "source_type": source_type, "locator": locator, "excerpt": excerpt,
            "captured_by": os.environ.get("KONMAN_REVIEWER") or getpass.getuser(),
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "related_nodes": _prompt_reference_list("Related node IDs (comma-separated, optional)"),
        }
        target_path = _context_node_path(engine, type, id)
    elif type == "change":
        summary = click.prompt(" Change summary")
        commit = click.prompt(" Commit hash (optional)", default="") or None
        files = _prompt_reference_list(" Changed file paths (comma-separated, optional)")
        payload = {
            "id": id, "summary": summary, "commit": commit,
            "author": os.environ.get("KONMAN_REVIEWER") or getpass.getuser(),
            "changed_at": datetime.now().strftime("%Y-%m-%d"),
            "files": files,
            "implements": _prompt_reference_list("Implemented decision IDs (comma-separated, optional)"),
            "affects": _prompt_reference_list("Affected requirement IDs (comma-separated, optional)"),
            "evidence": _prompt_reference_list("Evidence IDs (comma-separated, optional)"),
            "status": "active",
        }
        target_path = _context_node_path(engine, type, id)
    elif type == "question":
        payload = {
            "id": id,
            "question": click.prompt(" Unresolved question"),
            "owner": click.prompt(" Owner (optional)", default="") or None,
            "requirements": _prompt_reference_list("Related requirement IDs (comma-separated, optional)"),
            "decisions": _prompt_reference_list("Related decision IDs (comma-separated, optional)"),
            "objects": _prompt_reference_list("Related object IDs (comma-separated, optional)"),
            "evidence": _prompt_reference_list("Evidence IDs (comma-separated, optional)"),
            "status": "open",
        }
        target_path = _context_node_path(engine, type, id)
    elif type == "risk":
        payload = {
            "id": id,
            "statement": click.prompt(" Risk statement"),
            "likelihood": click.prompt(" Likelihood", type=click.Choice(["low", "medium", "high"]), default="medium"),
            "impact": click.prompt(" Impact", type=click.Choice(["low", "medium", "high"]), default="medium"),
            "mitigation": click.prompt(" Mitigation (optional)", default="") or None,
            "requirements": _prompt_reference_list("Related requirement IDs (comma-separated, optional)"),
            "decisions": _prompt_reference_list("Related decision IDs (comma-separated, optional)"),
            "changes": _prompt_reference_list("Related change IDs (comma-separated, optional)"),
            "evidence": _prompt_reference_list("Evidence IDs (comma-separated, optional)"),
            "status": "open",
        }
        target_path = _context_node_path(engine, type, id)
    elif type == "object":
        properties = []
        while click.confirm(" Add a property to this object?"):
            properties.append({
                "key": click.prompt(" Property name"),
                "value": click.prompt(" Property value"),
                "evidence": click.prompt(
                    " Property evidence basis",
                    type=click.Choice(["measured", "documented", "claimed"]),
                    default="claimed",
                ),
            })
        payload = {
            "id": id,
            "name": click.prompt(" Object name"),
            "kind": click.prompt(" Object kind (component, technology, service, etc.)", default="") or None,
            "description": click.prompt(" Description (optional)", default="") or None,
            "properties": properties,
            "evidence": _prompt_reference_list("Evidence IDs (comma-separated, optional)"),
            "status": "active",
        }
        target_path = _context_node_path(engine, type, id)

    if type != "boundary" and target_path.exists():
        raise click.ClickException(f"{id} already exists; refusing to overwrite context data.")

    try:
        if type == "boundary":
            for boundary in payload:
                BoundaryRule.model_validate(boundary)
        else:
            CONTEXT_NODE_CONFIG[type][2].model_validate(payload)
    except Exception as error:
        raise click.ClickException(f"Context record failed schema validation: {error}") from error

    from io import StringIO
    serialized = StringIO()
    yaml.dump(payload, serialized)
    atomic_write_text(target_path, serialized.getvalue())
    engine.compile_agents_md()
    click.echo(f" Successfully saved and synced {id} to the context database layer!")


@main.command()
@click.option("--dir", default=".", help="Target project root directory location.")
@click.option("--id", "node_id", help="Context node ID to review.")
@click.option("--approve", is_flag=True, help="Approve a proposed node after confirmation.")
@click.option("--reject", is_flag=True, help="Reject a proposed node with a recorded reason.")
@click.option("--edit", is_flag=True, help="Edit proposed node text before saving or approval.")
@click.option("--yes", is_flag=True, help="Skip approval confirmation for explicitly scripted use.")
def review(dir, node_id, approve, reject, edit, yes):
    """Inspect, edit, approve, or reject proposed context nodes."""
    if approve and reject:
        raise click.UsageError("Choose only one of --approve or --reject.")
    if yes and not approve:
        raise click.UsageError("--yes is only valid with --approve.")
    engine = ContextEngine(dir)
    yaml = YAML()
    yaml.preserve_quotes = True
    folders = {
        prefix: engine.ctx_dir / folder
        for prefix, folder, _, _ in CONTEXT_NODE_CONFIG.values()
        if prefix != "B"
    }
    boundaries_path = engine.ctx_dir / "boundaries.yaml"

    if not node_id:
        proposals = []
        for prefix, folder in folders.items():
            if not folder.exists():
                continue
            for path in sorted(folder.glob("*.yaml")):
                try:
                    node = yaml.load(path.read_text(encoding="utf-8"))
                except Exception as error:
                    click.echo(f"Invalid {path.relative_to(engine.base_dir)}: {error}")
                    continue
                if node and node.get("status") == "proposed":
                    proposals.append((prefix, node, path))
        if boundaries_path.exists():
            try:
                boundaries = yaml.load(boundaries_path.read_text(encoding="utf-8")) or []
                boundaries = [boundaries] if isinstance(boundaries, dict) else boundaries
                if not isinstance(boundaries, list):
                    raise ValueError("boundaries.yaml must contain a list or mapping.")
                proposals.extend(
                    ("B", boundary, boundaries_path)
                    for boundary in boundaries
                    if isinstance(boundary, dict) and boundary.get("status") == "proposed"
                )
            except Exception as error:
                click.echo(f"Invalid {boundaries_path.relative_to(engine.base_dir)}: {error}")
        if not proposals:
            click.echo("No proposed nodes are waiting for review.")
            return
        for prefix, node, path in proposals:
            label_field = next(config[3] for config in CONTEXT_NODE_CONFIG.values() if config[0] == prefix)
            label = node.get(label_field)
            click.echo(f"{node.get('id', path.stem)} [{prefix}] {label}")
            evidence_refs = node.get("evidence_ids") or node.get("evidence")
            if evidence_refs:
                click.echo(f"  Evidence: {evidence_refs}")
        click.echo("Run `konman review --id NODE_ID` to inspect or decide a proposal.")
        return

    prefixes = "".join(config[0] for config in CONTEXT_NODE_CONFIG.values())
    match = re.fullmatch(rf"([{prefixes}])-(\d+)", node_id)
    if not match:
        raise click.BadParameter("expected a typed context node ID such as R-001 or O-001", param_hint="--id")
    prefix = match.group(1)
    boundaries = None
    if prefix == "B":
        path = boundaries_path
        if not path.is_file():
            raise click.ClickException(f"No boundary with ID {node_id} exists.")
        try:
            boundaries = yaml.load(path.read_text(encoding="utf-8")) or []
            boundaries = [boundaries] if isinstance(boundaries, dict) else boundaries
            node = next((item for item in boundaries if isinstance(item, dict) and item.get("id") == node_id), None)
        except Exception as error:
            raise click.ClickException(f"Cannot parse {node_id}: {error}") from error
    else:
        path = folders[prefix] / f"{node_id}.yaml"
        if not path.is_file():
            raise click.ClickException(f"No context node with ID {node_id} exists.")
        try:
            node = yaml.load(path.read_text(encoding="utf-8"))
        except Exception as error:
            raise click.ClickException(f"Cannot parse {node_id}: {error}") from error
    if not node:
        raise click.ClickException(f"No context node with ID {node_id} exists.")
    if not isinstance(node, dict) or node.get("status") != "proposed":
        raise click.ClickException(f"{node_id} is not a valid proposed node.")

    node_type = next(key for key, value in CONTEXT_NODE_CONFIG.items() if value[0] == prefix)
    is_requirement = node_type == "requirement"
    is_decision = node_type == "decision"
    edit_field = CONTEXT_NODE_CONFIG[node_type][3]
    reason_field = {
        "requirement": "why", "decision": "reason", "boundary": "why",
        "evidence": "excerpt", "change": "summary", "question": "question",
        "risk": "statement", "object": "description",
    }[node_type]
    click.echo(f"{node_id}: {node.get(edit_field)}")
    click.echo(f"Evidence: {node.get('evidence_ids') or node.get('evidence', '(missing)')}")
    if edit:
        node[edit_field] = click.prompt(f"Updated {edit_field}", default=str(node.get(edit_field, "")))
        node[reason_field] = click.prompt(f"Updated {reason_field}", default=str(node.get(reason_field) or "")) or None
    if not approve and not reject and not edit:
        action = click.prompt("Action", type=click.Choice(["approve", "reject", "edit", "leave"]), default="leave")
        if action == "leave":
            return
        if action == "edit":
            node[edit_field] = click.prompt(f"Updated {edit_field}", default=str(node.get(edit_field, "")))
            edit = True
        else:
            approve, reject = action == "approve", action == "reject"

    if approve:
        if not yes and not click.confirm(f"Approve {node_id} and activate it?", default=False):
            click.echo("Approval cancelled.")
            return
        node["status"] = {
            "question": "open",
            "risk": "open",
            "object": "active",
        }.get(node_type, "active")
        if is_decision:
            for item in node.get("considered", []):
                if item.get("object") == node.get("chosen"):
                    item["verdict"] = "selected"
    elif reject:
        reason = click.prompt("Rejection reason")
        if not reason.strip():
            raise click.ClickException("A rejection reason is required.")
        node["status"] = "rejected"
        node["rejection_reason"] = reason

    if approve or reject or edit:
        try:
            model = CONTEXT_NODE_CONFIG[node_type][2]
            model.model_validate(node)
        except Exception as error:
            raise click.ClickException(f"Edited node failed schema validation: {error}") from error
        node["review"] = {"who": os.environ.get("KONMAN_REVIEWER") or getpass.getuser(), "when": datetime.now().isoformat(timespec="seconds")}
        from io import StringIO
        serialized = StringIO()
        yaml.dump(boundaries if prefix == "B" else node, serialized)
        atomic_write_text(path, serialized.getvalue())
        engine.compile_agents_md()
        click.echo(f"{node_id} saved with status '{node['status']}'.")

@main.command()
@click.argument("id")
@click.option("--replace-req", multiple=True, help="Replace a stale requirement reference as OLD_ID=ACTIVE_ID; repeatable.")
@click.option("--answer", help="Record an answer and resolve a question.")
@click.option("--defer", "defer_reason", help="Defer a question with a reason.")
@click.option("--mitigate", help="Record mitigation and resolve a risk as mitigated.")
@click.option("--accept-risk", help="Accept a risk with a rationale.")
@click.option("--close-risk", help="Close a risk with a resolution.")
@click.option("--dir", default=".", help="Target project root directory location.")
def resolve(id, replace_req, answer, defer_reason, mitigate, accept_risk, close_risk, dir):
    """Reconcile stale decisions or resolve open questions and risks."""
    engine = ContextEngine(dir)
    selected_actions = [answer, defer_reason, mitigate, accept_risk, close_risk]
    if sum(action is not None for action in selected_actions) > 1:
        raise click.UsageError("Choose only one question or risk resolution action.")
    if re.fullmatch(r"Q-\d+", id):
        if replace_req or not (answer or defer_reason):
            raise click.UsageError("Questions require either --answer TEXT or --defer REASON.")
        target_path = engine.ctx_dir / "questions" / f"{id}.yaml"
        if not target_path.is_file():
            raise click.ClickException(f"No question with ID '{id}' exists.")
        try:
            node = YAML().load(target_path.read_text(encoding="utf-8"))
            Question.model_validate(node)
        except Exception as error:
            raise click.ClickException(f"Cannot read question '{id}': {error}") from error
        if node["status"] not in ("open", "deferred"):
            raise click.ClickException(f"Question '{id}' is not open or deferred.")
        if answer:
            node.update({"status": "answered", "answer": answer, "resolution": answer})
        else:
            node.update({"status": "deferred", "resolution": defer_reason})
        atomic_write_yaml(target_path, node, engine.yaml)
        engine.compile_agents_md()
        click.echo(f" Question '{id}' saved with status '{node['status']}'.")
        return
    if re.fullmatch(r"X-\d+", id):
        action_by_option = {
            "mitigate": mitigate,
            "accept-risk": accept_risk,
            "close-risk": close_risk,
        }
        action = next((key for key, value in action_by_option.items() if value), None)
        if replace_req or not action:
            raise click.UsageError("Risks require one of --mitigate TEXT, --accept-risk RATIONALE, or --close-risk REASON.")
        target_path = engine.ctx_dir / "risks" / f"{id}.yaml"
        if not target_path.is_file():
            raise click.ClickException(f"No risk with ID '{id}' exists.")
        try:
            node = YAML().load(target_path.read_text(encoding="utf-8"))
            Risk.model_validate(node)
        except Exception as error:
            raise click.ClickException(f"Cannot read risk '{id}': {error}") from error
        if node["status"] not in ("open", "mitigated", "accepted"):
            raise click.ClickException(f"Risk '{id}' is not open.")
        if action == "mitigate":
            node.update({"status": "mitigated", "mitigation": mitigate, "resolution": mitigate})
        elif action == "accept-risk":
            node.update({"status": "accepted", "resolution": accept_risk})
        else:
            node.update({"status": "closed", "resolution": close_risk})
        atomic_write_yaml(target_path, node, engine.yaml)
        engine.compile_agents_md()
        click.echo(f" Risk '{id}' saved with status '{node['status']}'.")
        return
    if any(action is not None for action in selected_actions):
        raise click.UsageError("Question and risk resolution options require a Q- or X- node ID.")
    if not re.fullmatch(r"D-\d+", id):
        raise click.BadParameter("decision IDs must use D-001; questions use Q-001 and risks use X-001", param_hint="id")
    yaml = YAML()
    yaml.preserve_quotes = True
    target_path = engine.ctx_dir / "decisions" / f"{id}.yaml"
    
    if not target_path.exists():
        click.echo(f" Error: No decision node with ID '{id}' located inside the database matrix.")
        return

    try:
        d = yaml.load(target_path.read_text(encoding="utf-8"))
    except Exception as error:
        raise click.ClickException(f"Cannot parse decision '{id}': {error}") from error
    if not isinstance(d, dict) or d.get("status") != "needs_review":
        raise click.ClickException(f"Decision '{id}' is not a valid needs_review node.")

    click.echo(f"  Reconciling stale decision: {id}")
    requirement_dir = engine.ctx_dir / "requirements"
    stale_ids = set()
    for item in d.get("considered", []) or []:
        if not isinstance(item, dict):
            continue
        for evaluation in item.get("evaluations", []) or []:
            if not isinstance(evaluation, dict):
                continue
            req_path = requirement_dir / f"{evaluation.get('req')}.yaml"
            requirement = yaml.load(req_path.read_text(encoding="utf-8")) if req_path.exists() else None
            if not requirement or requirement.get("status") in ("superseded", "disproven"):
                stale_ids.add(evaluation.get("req"))
    replacements = {}
    for replacement in replace_req:
        old_id, separator, new_id = replacement.partition("=")
        if not separator or not old_id or not new_id:
            raise click.BadParameter("use OLD_ID=ACTIVE_ID", param_hint="--replace-req")
        replacements[old_id] = new_id
    unknown_replacements = set(replacements) - stale_ids
    if unknown_replacements:
        raise click.BadParameter(f"no stale or missing requirement reference for {', '.join(sorted(unknown_replacements))}", param_hint="--replace-req")
    for old_id in sorted(stale_ids):
        new_id = replacements.get(old_id) or click.prompt(f"Active replacement requirement for {old_id}")
        new_path = requirement_dir / f"{new_id}.yaml"
        if not new_path.is_file():
            raise click.ClickException(f"Replacement requirement '{new_id}' does not exist.")
        replacement = yaml.load(new_path.read_text(encoding="utf-8"))
        if not replacement or replacement.get("status") != "active":
            raise click.ClickException(f"Replacement requirement '{new_id}' must be active.")
        for item in d.get("considered", []) or []:
            if not isinstance(item, dict):
                continue
            for evaluation in item.get("evaluations", []) or []:
                if isinstance(evaluation, dict) and evaluation.get("req") == old_id:
                    evaluation["req"] = new_id

    new_reason = click.prompt(" Enter the updated tradeoff justification for keeping this choice")
    if not new_reason.strip():
        raise click.ClickException("A non-empty updated justification is required.")
    
    if click.confirm(" Reset status back to 'active' and clear git blocking flags?"):
        d["reason"] = new_reason
        d["status"] = "active"
        original = target_path.read_text(encoding="utf-8")
        from io import StringIO
        serialized = StringIO()
        yaml.dump(d, serialized)
        atomic_write_text(target_path, serialized.getvalue())
        engine.compile_agents_md()
        violations = engine.check_graph_validity()
        if violations:
            atomic_write_text(target_path, original)
            engine.compile_agents_md()
            click.echo(" Decision saved, but graph checks still fail:")
            for violation in violations:
                click.echo(f"  {violation}")
            raise click.exceptions.Exit(1)
        click.echo(f" Decision '{id}' is active and graph checks pass.")

@main.command()
@click.option("--count", "-c", default=10, help="Number of historical commit messages back to process.")
@click.option("--dir", default=".", help="Target project root directory location.")
def mine(count, dir):
    """Capture Git history and propose structured Change and Evidence records."""
    engine = ContextEngine(dir)
    click.echo(f"  Mining the last {count} git commits for architectural reasoning clues...")
    extracted = engine.mine_git_history(count)
    click.echo(
        f" History mining complete. Stored [{extracted}] raw context dumps and proposed "
        "Change/Evidence records for commits with explicit reasoning clues."
    )


def _collect_human_turns(value):
    turns = []
    if isinstance(value, dict):
        event = value.get("hook_event_name") or value.get("event") or value.get("trigger")
        if isinstance(event, str) and event.casefold() in {"userpromptsubmit", "beforesubmitprompt"}:
            prompt = value.get("prompt") or value.get("user_prompt")
            if isinstance(prompt, str) and prompt.strip():
                turns.append(prompt)
        role = value.get("role") or value.get("speaker")
        if isinstance(role, str) and role.casefold() in {"user", "human"}:
            content = value.get("content") or value.get("text") or value.get("message")
            if isinstance(content, str) and content.strip():
                turns.append(content)
            elif isinstance(content, list):
                turns.extend(item["text"] for item in content if isinstance(item, dict) and isinstance(item.get("text"), str))
        for child in value.values():
            if isinstance(child, (dict, list)):
                turns.extend(_collect_human_turns(child))
    elif isinstance(value, list):
        for item in value:
            turns.extend(_collect_human_turns(item))
    return turns


def _file_identity(path: Path, stat) -> str:
    with path.open("rb") as source_file:
        prefix = source_file.read(4096)
    prefix_hash = hashlib.sha256(prefix).hexdigest()
    return f"{stat.st_dev}:{stat.st_ino}:{prefix_hash}"


def _cursor_checkpoint(path: Path, offset: int) -> str:
    start = max(0, offset - 4096)
    with path.open("rb") as source_file:
        source_file.seek(start)
        sample = source_file.read(offset - start)
    return hashlib.sha256(sample).hexdigest()


def _custom_redaction_patterns(context_dir: Path) -> list[str]:
    manifest_path = Path(context_dir) / "manifest.yaml"
    if not manifest_path.exists():
        return []
    try:
        manifest = YAML().load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as error:
        raise ValueError(f"Cannot read redaction policy in {manifest_path}: {error}") from error
    if not isinstance(manifest, dict):
        raise ValueError("manifest.yaml must be a mapping before custom redaction can run.")
    redaction = manifest.get("redaction", {})
    if not isinstance(redaction, dict):
        raise ValueError("redaction in manifest.yaml must be a mapping.")
    patterns = redaction.get("patterns", [])
    if not isinstance(patterns, list) or any(not isinstance(pattern, str) for pattern in patterns):
        raise ValueError("redaction.patterns must be a list of regular expressions.")
    try:
        for pattern in patterns:
            re.compile(pattern)
    except re.error as error:
        raise ValueError(f"Invalid custom redaction pattern: {error}") from error
    return patterns


def _redact_capture_text(text: str, custom_patterns=()) -> tuple[str, int]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        output = []
        total = 0
        for line in text.splitlines(keepends=True):
            ending = "\n" if line.endswith("\n") else ""
            body = line[:-1] if ending else line
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                redacted_line, count = redact_text(body, custom_patterns)
            else:
                parsed, count = redact_value(parsed, custom_patterns)
                redacted_line = json.dumps(parsed, ensure_ascii=False)
            output.append(redacted_line + ending)
            total += count
        return "".join(output), total
    redacted, count = redact_value(parsed, custom_patterns)
    return json.dumps(redacted, ensure_ascii=False), count


def _backfill_source(source, project_dir, source_paths=(), since=None, dry_run=False):
    engine = ContextEngine(project_dir)
    if not dry_run:
        engine.init_folders()
    custom_patterns = _custom_redaction_patterns(engine.ctx_dir)
    files = sorted({Path(path).resolve() for path in source_paths}) if source_paths else discover_paths(source)
    cursor_dir = engine.ctx_dir / "state" / "cursors"
    raw_dir = engine.ctx_dir / ".raw"
    totals = {"discovered": len(files), "parsed": 0, "skipped": 0, "failed": 0, "persisted": 0}
    for path in files:
        try:
            stat = path.stat()
            identity = _file_identity(path, stat)
            cursor_id = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
            cursor_path = cursor_dir / f"{source}-{cursor_id}.json"
            cursor = json.loads(cursor_path.read_text(encoding="utf-8")) if cursor_path.exists() else {}
            old_offset = cursor.get("offset", 0)
            checkpoint_changed = bool(cursor.get("checkpoint")) and cursor.get("checkpoint") != _cursor_checkpoint(path, old_offset)
            if cursor.get("identity") != identity or old_offset > stat.st_size or checkpoint_changed:
                cursor = {"offset": 0, "seen": []}

            records = []
            new_offset = cursor.get("offset", 0)
            if path.suffix.casefold() == ".json":
                if stat.st_size > 20 * 1024 * 1024:
                    totals["failed"] += 1
                    continue
                content = path.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                if cursor.get("snapshot_digest") == digest:
                    totals["skipped"] += 1
                    continue
                records = [(0, content, True)]
                new_offset = len(content)
                cursor["snapshot_digest"] = digest
            else:
                base_offset = cursor.get("offset", 0)
                max_record_bytes = 2 * 1024 * 1024
                with path.open("rb") as source_file:
                    source_file.seek(base_offset)
                    while True:
                        record_offset = source_file.tell()
                        line = source_file.readline(max_record_bytes + 1)
                        if not line:
                            break
                        oversized = len(line) > max_record_bytes
                        while oversized and line and not line.endswith((b"\n", b"\r")):
                            line = source_file.readline(max_record_bytes + 1)
                        end_offset = source_file.tell()
                        if not line.endswith((b"\n", b"\r")):
                            break
                        records.append((record_offset, b"" if oversized else line.rstrip(b"\r\n"), False))
                        new_offset = end_offset

            seen = set(cursor.get("seen", []))
            for record_offset, raw_record, is_snapshot in records:
                try:
                    if path.suffix.casefold() == ".log":
                        values = [{"line": raw_record.decode("utf-8", errors="replace")}]
                    else:
                        decoded = json.loads(raw_record.decode("utf-8"))
                        values = decoded if is_snapshot and isinstance(decoded, list) else [decoded]
                    events = []
                    for index, value in enumerate(values):
                        events.extend(parse_record(source, value, record_offset + index))
                except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                    totals["failed"] += 1
                    continue

                for event in events:
                    if since and (not event.timestamp or event.timestamp < since):
                        totals["skipped"] += 1
                        continue
                    totals["parsed"] += 1
                    if event.event_id in seen:
                        totals["skipped"] += 1
                        continue
                    redacted, redaction_count = redact_value(event.as_dict(), custom_patterns)
                    output_path = raw_dir / f"backfill-{source}-{event.event_id}.json"
                    if output_path.exists():
                        seen.add(event.event_id)
                        totals["skipped"] += 1
                        continue
                    redacted["redaction_count"] = redaction_count
                    if not dry_run:
                        atomic_write_json(output_path, redacted)
                    seen.add(event.event_id)
                    totals["persisted"] += 1

            cursor.update({
                "identity": identity,
                "offset": new_offset,
                "checkpoint": _cursor_checkpoint(path, new_offset),
                "seen": list(seen)[-20000:],
            })
            if not dry_run:
                atomic_write_json(cursor_path, cursor)
        except OSError:
            totals["failed"] += 1
    return totals


@main.command()
@click.option("--source", required=True, type=click.Choice(SOURCES), help="Transcript provider to backfill.")
@click.option("--source-path", "source_paths", multiple=True, type=click.Path(path_type=Path, exists=True, file_okay=True, dir_okay=False), help="Read this transcript file instead of auto-discovery; repeatable.")
@click.option("--since", help="Only persist events with ISO timestamps at or after this value.")
@click.option("--dry-run", is_flag=True, help="Parse and report without writing events or cursors.")
@click.option("--dir", default=".", help="Target project root directory location.")
def backfill(source, source_paths, since, dry_run, dir):
    """Incrementally parse saved transcripts for one supported source."""
    try:
        totals = _backfill_source(source, dir, source_paths, since, dry_run)
    except ValueError as error:
        raise click.ClickException(f"Cannot apply redaction policy: {error}") from error
    click.echo(
        f"{source}: discovered={totals['discovered']} parsed={totals['parsed']} "
        f"persisted={totals['persisted']} skipped={totals['skipped']} failed={totals['failed']}"
    )


@main.command(deprecated=True)
@click.option("--count", "-c", default=10, type=click.IntRange(min=1), help="Maximum saved Copilot source files to backfill.")
@click.option("--dir", default=".", help="Target project root directory location.")
def tail(count, dir):
    """Deprecated alias for `konman backfill --source copilot`."""
    click.echo("Warning: `konman tail` is deprecated; use `konman backfill --source copilot`.", err=True)
    paths = discover_paths("copilot")
    paths = sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)[:count]
    try:
        totals = _backfill_source("copilot", dir, paths)
    except ValueError as error:
        raise click.ClickException(f"Cannot apply redaction policy: {error}") from error
    click.echo(
        f"copilot: discovered={totals['discovered']} parsed={totals['parsed']} "
        f"persisted={totals['persisted']} skipped={totals['skipped']} failed={totals['failed']}"
    )


@main.command()
@click.option("--older-than", required=True, type=click.IntRange(min=1), help="Delete raw capture files older than this many days.")
@click.option("--dry-run", is_flag=True, help="List eligible captures without deleting them.")
@click.option("--dir", default=".", help="Target project root directory location.")
def clean(older_than, dry_run, dir):
    """Remove old raw capture files only when explicitly requested."""
    raw_dir = ContextEngine(dir).ctx_dir / ".raw"
    if not raw_dir.is_dir():
        click.echo("No raw capture directory found.")
        return
    cutoff = datetime.now().timestamp() - older_than * 86400
    eligible = [path for path in raw_dir.iterdir() if path.is_file() and path.stat().st_mtime < cutoff]
    for path in eligible:
        click.echo(f"{'Would remove' if dry_run else 'Removed'} {path.name}")
        if not dry_run:
            path.unlink()
    click.echo(f"{len(eligible)} raw capture file(s) {'eligible' if dry_run else 'removed'}.")


def _split_capture(content, max_chars=12000):
    chunks = []
    human_turns = []
    try:
        parsed = json.loads(content)
        human_turns = _collect_human_turns(parsed)
        lines = [content]
    except json.JSONDecodeError:
        lines = content.splitlines()
        for line in lines:
            try:
                human_turns.extend(_collect_human_turns(json.loads(line)))
            except json.JSONDecodeError:
                continue
    current, start = [], 0
    for line in lines:
        line = line + "\n"
        if current and sum(map(len, current)) + len(line) > max_chars:
            chunk_text = "".join(current)
            chunks.append((start, chunk_text))
            start += len(chunk_text.encode("utf-8"))
            current = []
        if len(line) > max_chars:
            if current:
                chunk_text = "".join(current)
                chunks.append((start, chunk_text))
                start += len(chunk_text.encode("utf-8"))
                current = []
            byte_offset = 0
            for offset in range(0, len(line), max_chars):
                part = line[offset:offset + max_chars]
                chunks.append((start + byte_offset, part))
                byte_offset += len(part.encode("utf-8"))
            start += byte_offset
        else:
            current.append(line)
    if current:
        chunks.append((start, "".join(current)))
    return [
        (offset, text, "\n".join(turn for turn in human_turns if turn and turn in text))
        for offset, text in chunks
    ]


def _write_context_node(folder, prefix, payload, capture_id, chunk_index, yaml):
    folder.mkdir(parents=True, exist_ok=True)
    subject_field = {
        "R": "statement", "D": "chosen", "E": "excerpt", "C": "summary",
        "Q": "question", "X": "statement", "O": "name",
    }.get(prefix, "statement")
    subject = " ".join(str(payload.get(subject_field, "")).split()).casefold()
    candidate_fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    for existing_path in folder.glob(f"{prefix}-*.yaml"):
        existing = yaml.load(existing_path.read_text(encoding="utf-8"))
        existing_subject = " ".join(str((existing or {}).get(subject_field, "")).split()).casefold()
        if prefix != "E" and subject and subject == existing_subject:
            return existing.get("id"), False
        if (
            existing
            and existing.get("capture_id") == capture_id
            and existing.get("capture_chunk") == chunk_index
            and existing.get("candidate_fingerprint") == candidate_fingerprint
        ):
            return existing.get("id"), False
    existing_ids = [
        int(match.group(1))
        for path in folder.glob(f"{prefix}-*.yaml")
        if (match := re.fullmatch(rf"{prefix}-(\d+)", path.stem))
    ]
    node_id = f"{prefix}-{max(existing_ids, default=0) + 1:03d}"
    payload.update({
        "id": node_id,
        "capture_id": capture_id,
        "capture_chunk": chunk_index,
        "candidate_fingerprint": candidate_fingerprint,
    })
    model = next((config[2] for config in CONTEXT_NODE_CONFIG.values() if config[0] == prefix), None)
    if model is None or model is BoundaryRule:
        raise ValueError(f"Unsupported context node prefix: {prefix}")
    model.model_validate(payload)
    from io import StringIO
    serialized = StringIO()
    yaml.dump(payload, serialized)
    atomic_write_text(folder / f"{node_id}.yaml", serialized.getvalue())
    return node_id, True


def _prompt_reference_list(label):
    value = click.prompt(label, default="")
    return [item.strip() for item in value.split(",") if item.strip()]


def _context_node_path(engine, node_type, node_id):
    prefix, folder, _, _ = CONTEXT_NODE_CONFIG[node_type]
    if node_type == "boundary":
        return engine.ctx_dir / "boundaries.yaml"
    return engine.ctx_dir / folder / f"{node_id}.yaml"


def _write_boundary_node(boundaries_path, payload, capture_id, chunk_index, yaml):
    existing = []
    if boundaries_path.exists():
        existing_data = yaml.load(boundaries_path.read_text(encoding="utf-8")) or []
        existing = [existing_data] if isinstance(existing_data, dict) else existing_data
        if not isinstance(existing, list):
            raise ValueError("boundaries.yaml must contain a list or mapping.")

    candidate_fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    for boundary in existing:
        if not isinstance(boundary, dict):
            continue
        if boundary.get("path") == payload["path"]:
            return boundary.get("id"), False
        if (
            boundary.get("capture_id") == capture_id
            and boundary.get("capture_chunk") == chunk_index
            and boundary.get("candidate_fingerprint") == candidate_fingerprint
        ):
            return boundary.get("id"), False

    existing_ids = [
        int(match.group(1))
        for boundary in existing
        if isinstance(boundary, dict)
        and (match := re.fullmatch(r"B-(\d+)", str(boundary.get("id", ""))))
    ]
    node_id = f"B-{max(existing_ids, default=0) + 1:03d}"
    payload.update({
        "id": node_id,
        "capture_id": capture_id,
        "capture_chunk": chunk_index,
        "candidate_fingerprint": candidate_fingerprint,
    })
    BoundaryRule.model_validate(payload)
    existing.append(payload)
    from io import StringIO
    serialized = StringIO()
    yaml.dump(existing, serialized)
    atomic_write_text(boundaries_path, serialized.getvalue())
    return node_id, True


def _write_quote_evidence(engine, quote, model, today, capture_id, chunk_id, yaml):
    return _write_context_node(
        engine.ctx_dir / "evidence", "E", {
            "source_type": "transcript",
            "locator": f"{capture_id}:{chunk_id}",
            "excerpt": quote,
            "captured_by": f"llm:{model}",
            "captured_at": today,
            "status": "proposed",
        }, capture_id, chunk_id, yaml,
    )


@main.command()
@click.option("--api-key", envvar=["KONMAN_API_KEY", "OPENAI_API_KEY"], help="Provider API key (or set KONMAN_API_KEY).")
@click.option("--provider", default=None, help="Provider label; defaults to the saved provider.")
@click.option("--api-format", type=click.Choice(API_FORMATS), default=None, help="Provider API protocol format.")
@click.option("--model", default=None, help="Model name; defaults to the saved config or gpt-4o-mini.")
@click.option("--base-url", default=None, envvar=["KONMAN_BASE_URL", "OPENAI_BASE_URL"], help="Provider API root URL; defaults to the saved provider endpoint.")
@click.option("--type", "node_types", multiple=True, type=click.Choice(EXTRACT_NODE_TYPES), help="Node type(s) to extract; repeat to select multiple. Defaults to all.")
@click.option("--dir", default=".", help="Target project root directory location.")
def extract(api_key, provider, api_format, model, base_url, node_types, dir):
    """Extract evidence-grounded proposed context nodes from unprocessed captures."""
    node_types = tuple(dict.fromkeys(node_types)) or EXTRACT_NODE_TYPES
    global_cfg = load_global_api_credentials() or {}
    if global_cfg.get("config_error"):
        raise click.ClickException(global_cfg["config_error"])
    if not api_key:
        api_key = global_cfg.get("api_key")
    provider = provider or global_cfg.get("provider") or "openai"
    api_format = api_format or global_cfg.get("api_format")
    try:
        llm_config = resolve_llm_configuration(
            provider,
            api_format,
            base_url or global_cfg.get("base_url"),
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    model = model or global_cfg.get("model")
    if not model:
        if llm_config["api_format"] == "ollama":
            model = "llama3.2"
        elif llm_config["api_format"] == "openai-compatible":
            model = "gpt-4o-mini"
        else:
            raise click.ClickException(f"Pass --model for the {llm_config['api_format']} API format.")
    base_url = llm_config["base_url"]
    api_format = llm_config["api_format"]
    if api_format != "ollama" and not api_key:
        raise click.ClickException("No API key configured. Use `konman config --api-key ...` or set KONMAN_API_KEY.")
    engine = ContextEngine(dir)
    raw_dir = engine.ctx_dir / ".raw"
    processed_dir = raw_dir / ".processed"
    try:
        custom_patterns = _custom_redaction_patterns(engine.ctx_dir)
    except ValueError as error:
        raise click.ClickException(f"Cannot apply redaction policy: {error}") from error
    supported = {".json", ".jsonl", ".log", ".txt"}
    raw_files = [path for path in raw_dir.iterdir() if path.is_file() and path.suffix.lower() in supported] if raw_dir.exists() else []
    pending = []
    for path in sorted(raw_files):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if content.strip():
            state_path = processed_dir / f"{hashlib.sha256(path.name.encode('utf-8')).hexdigest()}.json"
            pending.append((path, content, digest, state_path))

    if not pending:
        click.echo(" No unprocessed raw captures found in .context/.raw/.")
        return

    processed_dir.mkdir(parents=True, exist_ok=True)
    yaml = YAML()
    yaml.preserve_quotes = True
    today = datetime.now().strftime("%Y-%m-%d")
    created = 0
    failed = 0
    for path, content, digest, state_path in pending:
        chunks = _split_capture(content)
        state = {}
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
        if state.get("digest") != digest:
            state = {"digest": digest, "completed_chunks": [], "chunks": {}}
        completed = set(state.get("completed_chunks", []))
        chunk_states = state.setdefault("chunks", {})
        capture_id = hashlib.sha256(f"{path.name}:{digest}".encode("utf-8")).hexdigest()

        for chunk_index, (offset, text, human_evidence) in enumerate(chunks):
            chunk_id = f"{offset}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
            previous = chunk_states.get(chunk_id, {})
            completed_types = set(previous.get("completed_node_types", []))
            if chunk_id in completed and "completed_node_types" not in previous:
                completed_types.update(("requirement", "decision"))
            types_to_extract = tuple(node_type for node_type in node_types if node_type not in completed_types)
            if not types_to_extract:
                continue
            completed.discard(chunk_id)
            redacted_text, redaction_count = _redact_capture_text(text, custom_patterns)
            click.echo(f" Extracting {path.name} chunk {chunk_index + 1}/{len(chunks)} ({redaction_count} redactions)...")
            chunk_states[chunk_id] = {
                "status": "processing",
                "attempts": previous.get("attempts", 0) + 1,
                "source_offset": offset,
                "completed_node_types": sorted(completed_types),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            state.update({"digest": digest, "completed_chunks": sorted(completed), "chunks": chunk_states})
            atomic_write_json(state_path, state)
            try:
                response = engine.execute_llm_distillation(
                    redacted_text, api_key, model, base_url, api_format, node_types=types_to_extract
                )
                extracted_data = json.loads(response)
                if not isinstance(extracted_data, dict) or extracted_data.get("error"):
                    raise ValueError(extracted_data.get("error", "Provider response must be a JSON object"))
                requirements = extracted_data.get("requirements", [])
                decisions = extracted_data.get("decisions", [])
                boundaries = extracted_data.get("boundaries", [])
                evidence_records = extracted_data.get("evidence", [])
                changes = extracted_data.get("changes", [])
                questions = extracted_data.get("questions", [])
                risks = extracted_data.get("risks", [])
                objects = extracted_data.get("objects", [])
                selected_arrays = {
                    "requirement": ("requirements", requirements),
                    "decision": ("decisions", decisions),
                    "boundary": ("boundaries", boundaries),
                    "evidence": ("evidence", evidence_records),
                    "change": ("changes", changes),
                    "question": ("questions", questions),
                    "risk": ("risks", risks),
                    "object": ("objects", objects),
                }
                for node_type, (key, values) in selected_arrays.items():
                    if node_type in types_to_extract and not isinstance(values, list):
                        raise ValueError(f"{key} must be a JSON array")

                chunk_created = 0
                for requirement in requirements if "requirement" in types_to_extract else []:
                    if not isinstance(requirement, dict):
                        continue
                    quote = requirement.get("evidence")
                    if not isinstance(quote, str) or not quote.strip() or quote not in human_evidence or quote not in redacted_text:
                        continue
                    if not requirement.get("statement") or requirement.get("kind") not in ("hard", "preference"):
                        continue
                    evidence_id, evidence_created = _write_quote_evidence(
                        engine, quote, model, today, capture_id, chunk_id, yaml,
                    )
                    node_id, was_created = _write_context_node(
                        engine.ctx_dir / "requirements", "R", {
                            "statement": str(requirement["statement"]),
                            "kind": requirement["kind"],
                            "why": requirement.get("why"),
                            "evidence": quote,
                            "evidence_ids": [evidence_id],
                            "source": {"who": f"llm:{model}", "when": today},
                            "status": "proposed",
                        }, capture_id, chunk_id, yaml,
                    )
                    if was_created:
                        click.echo(f"    Proposed Requirement: {node_id}")
                        created += 1
                        chunk_created += 1
                    if evidence_created:
                        click.echo(f"    Proposed Evidence: {evidence_id}")
                        created += 1
                        chunk_created += 1

                for decision in decisions if "decision" in types_to_extract else []:
                    if not isinstance(decision, dict):
                        continue
                    quote = decision.get("evidence")
                    if not isinstance(quote, str) or not quote.strip() or quote not in human_evidence or quote not in redacted_text:
                        continue
                    if not decision.get("chosen") or decision.get("mode") not in ("compared", "default", "forced", "taste"):
                        continue
                    evidence_id, evidence_created = _write_quote_evidence(
                        engine, quote, model, today, capture_id, chunk_id, yaml,
                    )
                    node_id, was_created = _write_context_node(
                        engine.ctx_dir / "decisions", "D", {
                            "chosen": str(decision["chosen"]),
                            "mode": decision["mode"],
                            "decided": {"who": f"llm:{model}", "when": today},
                            "considered": [{"object": str(decision["chosen"]), "properties": [], "evaluations": [], "verdict": "proposed"}],
                            "reason": decision.get("reason"),
                            "evidence": quote,
                            "evidence_ids": [evidence_id],
                            "status": "proposed",
                        }, capture_id, chunk_id, yaml,
                    )
                    if was_created:
                        click.echo(f"    Proposed Decision: {node_id}")
                        created += 1
                        chunk_created += 1
                    if evidence_created:
                        click.echo(f"    Proposed Evidence: {evidence_id}")
                        created += 1
                        chunk_created += 1

                for boundary in boundaries if "boundary" in types_to_extract else []:
                    if not isinstance(boundary, dict):
                        continue
                    quote = boundary.get("evidence")
                    if not isinstance(quote, str) or not quote.strip() or quote not in human_evidence or quote not in redacted_text:
                        continue
                    if not isinstance(boundary.get("path"), str) or not boundary["path"].strip():
                        continue
                    evidence_id, evidence_created = _write_quote_evidence(
                        engine, quote, model, today, capture_id, chunk_id, yaml,
                    )
                    node_id, was_created = _write_boundary_node(
                        engine.ctx_dir / "boundaries.yaml", {
                            "path": boundary["path"].strip(),
                            "rule": boundary.get("rule") or "no_edit_without_approval",
                            "why": boundary.get("why"),
                            "evidence": quote,
                            "evidence_ids": [evidence_id],
                            "status": "proposed",
                        }, capture_id, chunk_id, yaml,
                    )
                    if was_created:
                        click.echo(f"    Proposed Boundary: {node_id}")
                        created += 1
                        chunk_created += 1
                    if evidence_created:
                        click.echo(f"    Proposed Evidence: {evidence_id}")
                        created += 1
                        chunk_created += 1

                for evidence in evidence_records if "evidence" in types_to_extract else []:
                    if not isinstance(evidence, dict):
                        continue
                    quote = evidence.get("excerpt")
                    if not isinstance(quote, str) or not quote.strip() or quote not in human_evidence or quote not in redacted_text:
                        continue
                    source_type = evidence.get("source_type", "transcript")
                    if source_type not in ("human", "transcript", "commit", "document", "issue", "test", "other"):
                        continue
                    evidence_payload = {
                        "source_type": source_type,
                        "locator": evidence.get("locator") or f"{capture_id}:{chunk_id}",
                        "excerpt": quote,
                        "captured_by": f"llm:{model}",
                        "captured_at": today,
                        "status": "proposed",
                    }
                    node_id, was_created = _write_context_node(
                        engine.ctx_dir / "evidence", "E", evidence_payload,
                        capture_id, chunk_id, yaml,
                    )
                    if was_created:
                        click.echo(f"    Proposed Evidence: {node_id}")
                        created += 1
                        chunk_created += 1

                for node_type, records_to_write, fields in (
                    ("change", changes, {
                        "summary": "summary", "files": "files", "implements": "implements",
                        "affects": "affects", "verification": "verification",
                    }),
                    ("question", questions, {"question": "question", "owner": "owner"}),
                    ("risk", risks, {
                        "statement": "statement", "likelihood": "likelihood",
                        "impact": "impact", "mitigation": "mitigation",
                    }),
                    ("object", objects, {"name": "name", "kind": "kind", "description": "description"}),
                ):
                    if node_type not in types_to_extract:
                        continue
                    prefix, folder, model_type, _ = CONTEXT_NODE_CONFIG[node_type]
                    for candidate in records_to_write:
                        if not isinstance(candidate, dict):
                            continue
                        quote = candidate.get("evidence")
                        if not isinstance(quote, str) or not quote.strip() or quote not in human_evidence or quote not in redacted_text:
                            continue
                        if not candidate.get(fields[next(iter(fields))]):
                            continue
                        evidence_id, evidence_created = _write_quote_evidence(
                            engine, quote, model, today, capture_id, chunk_id, yaml,
                        )
                        payload = {
                            key: candidate.get(source_key)
                            for key, source_key in fields.items()
                            if candidate.get(source_key) is not None
                        }
                        if node_type == "change":
                            files = payload.get("files", [])
                            if files is None:
                                files = []
                            elif isinstance(files, str):
                                files = [files]
                            if not isinstance(files, list) or any(not isinstance(path, str) for path in files):
                                continue
                            payload["files"] = files
                            payload["implements"] = []
                            payload["affects"] = []
                            payload.update({
                                "commit": None,
                                "author": f"llm:{model}",
                                "changed_at": today,
                                "evidence": [evidence_id],
                                "status": "proposed",
                            })
                        elif node_type == "question":
                            payload.update({
                                "requirements": [], "decisions": [], "objects": [],
                                "evidence": [evidence_id], "status": "proposed",
                            })
                        elif node_type == "risk":
                            payload.update({
                                "requirements": [], "decisions": [], "changes": [],
                                "evidence": [evidence_id], "status": "proposed",
                            })
                        else:
                            payload.update({
                                "properties": candidate.get("properties", []) if isinstance(candidate.get("properties", []), list) else [],
                                "evidence": [evidence_id],
                                "status": "proposed",
                            })
                        node_id, was_created = _write_context_node(
                            engine.ctx_dir / folder, prefix, payload,
                            capture_id, chunk_id, yaml,
                        )
                        if evidence_created:
                            click.echo(f"    Proposed Evidence: {evidence_id}")
                            created += 1
                            chunk_created += 1
                        if was_created:
                            click.echo(f"    Proposed {node_type.title()}: {node_id}")
                            created += 1
                            chunk_created += 1

                completed_types.update(types_to_extract)
                if set(("requirement", "decision", "boundary")).issubset(completed_types):
                    completed.add(chunk_id)
                chunk_states[chunk_id] = {
                    "status": "processed",
                    "attempts": chunk_states[chunk_id]["attempts"],
                    "source_offset": offset,
                    "completed_node_types": sorted(completed_types),
                    "proposed_nodes": chunk_created,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
                state.update({"digest": digest, "completed_chunks": sorted(completed), "chunks": chunk_states})
                atomic_write_json(state_path, state)
                if not chunk_created:
                    click.echo(f"    No proposed nodes found in {path.name} chunk {chunk_index + 1}.")
            except (ValueError, KeyError, TypeError, OSError) as error:
                failed += 1
                attempts = chunk_states[chunk_id]["attempts"]
                chunk_states[chunk_id] = {
                    "status": "failed",
                    "attempts": attempts,
                    "source_offset": offset,
                    "completed_node_types": sorted(completed_types),
                    "error_type": type(error).__name__,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
                state.update({"digest": digest, "completed_chunks": sorted(completed), "chunks": chunk_states})
                atomic_write_json(state_path, state)
                safe_error, _ = redact_text(str(error), _custom_redaction_patterns(engine.ctx_dir))
                click.echo(f" Failed chunk {chunk_index + 1} from {path.name}: {safe_error}", err=True)

    if created:
        engine.compile_agents_md()
    click.echo(f" Extraction complete: {created} proposed node(s); {failed} chunk(s) remain retryable.")
    if failed:
        raise click.ClickException("One or more captures failed; successful chunks remain recorded and failed chunks can be retried.")

@main.command(name="handoff")
@click.argument("previous_tool")
@click.argument("next_tool")
@click.option("--dir", default=".", help="Target project root directory location.")
@click.option("--output", type=click.Path(path_type=Path), help="Write the handoff pack to this path instead of the history directory.")
def handoff(previous_tool, next_tool, dir, output):
    """Write a reviewable context pack and configure the destination tool adapter."""
    engine = ContextEngine(dir)
    aliases = {
        "antigravity": "antigravity",
        "claude": "claude-code",
        "claude-code": "claude-code",
        "codex": "codex",
        "copilot": "vsc-copilot",
        "vscode-copilot": "vsc-copilot",
        "vsc-copilot": "vsc-copilot",
        "cursor": "cursor",
        "kiro": "kiro",
    }
    adapters = {
        "antigravity": inject_antigravity_hooks,
        "claude-code": inject_claude_code_adapters,
        "codex": inject_codex_adapters,
        "vsc-copilot": inject_vsc_copilot_adapters,
        "cursor": inject_cursor_adapters,
        "kiro": inject_kiro_adapters,
    }
    destination = aliases.get(next_tool.lower())
    if destination is None:
        raise click.BadParameter(f"unknown destination tool '{next_tool}'", param_hint="next_tool")

    engine.init_folders()
    engine.compile_agents_md()
    history_dir = engine.ctx_dir / "state" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    pack_path = output or history_dir / f"handoff-{timestamp}.md"
    if not pack_path.is_absolute():
        pack_path = engine.base_dir / pack_path
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    context_files = [engine.base_dir / "AGENTS.md", engine.ctx_dir / "project.md", engine.ctx_dir / "manifest.yaml"]
    context_files.extend(sorted((engine.ctx_dir / "requirements").glob("*.yaml")))
    context_files.extend(sorted((engine.ctx_dir / "decisions").glob("*.yaml")))
    for folder in ("objects", "evidence", "changes", "questions", "risks"):
        context_files.extend(sorted((engine.ctx_dir / folder).glob("*.yaml")))
    context_files.extend(sorted((engine.ctx_dir / "questions").glob("*.md")))
    context_files.extend([engine.ctx_dir / "boundaries.yaml", engine.ctx_dir / "state" / "current.yaml"])
    sections = [
        "# Konman Handoff Pack",
        f"\nFrom: {previous_tool}\nTo: {destination}\nCreated: {datetime.now().isoformat(timespec='seconds')}\n",
    ]
    for path in context_files:
        if not path.is_file():
            continue
        relative = path.relative_to(engine.base_dir).as_posix()
        content = path.read_text(encoding="utf-8", errors="replace").strip()
        if content:
            sections.append(f"## {relative}\n\n```text\n{content}\n```")
    try:
        git_result = subprocess.run(
            ["git", "status", "--short"], cwd=engine.base_dir, capture_output=True, text=True, check=True
        )
        diff_result = subprocess.run(
            ["git", "diff", "--stat"], cwd=engine.base_dir, capture_output=True, text=True, check=True
        )
        sections.append(f"## Git Status\n\n```text\n{git_result.stdout.strip() or '(clean)'}\n```\n\nDiff summary:\n\n```text\n{diff_result.stdout.strip() or '(no unstaged diff)'}\n```")
    except (OSError, subprocess.CalledProcessError):
        sections.append("## Git Status\n\nGit status is unavailable for this directory.")
    atomic_write_text(pack_path, "\n\n".join(sections) + "\n")

    try:
        notes = adapters[destination](str(engine.base_dir))
    except Exception as error:
        click.echo(f" Handoff pack retained at {pack_path}; adapter setup failed: {error}", err=True)
        raise click.ClickException("Handoff pack created, but destination adapter setup failed.") from error
    for note in notes:
        click.echo(f"  {note}")
    click.echo(f" Handoff pack written to {pack_path}.")
    click.echo(f" Adapter configured for {destination}; the previous tool was not disabled.")

@main.command(name="config")
@click.option("--api-key", "-k", help="Provider API key. Not required for local Ollama.")
@click.option("--provider", "-p", default=None, help="Provider name or custom provider label.")
@click.option("--api-format", type=click.Choice(API_FORMATS), default=None, help="API wire format for this provider.")
@click.option("--base-url", help="Provider API root URL; required for unknown/custom providers.")
@click.option("--model", default=None, help="Default model used by `konman extract`.")
@click.option("--migrate", is_flag=True, help="Move a legacy plaintext API key into the OS credential store.")
@click.option("--clear", "clear_config", is_flag=True, help="Delete saved provider metadata and its stored API key.")
def config_command(api_key, provider, api_format, base_url, model, migrate, clear_config):
    """Configure or inspect any supported LLM API provider."""
    if clear_config:
        try:
            removed = clear_global_api_credentials()
        except (RuntimeError, ValueError) as error:
            raise click.ClickException(str(error)) from error
        click.echo(" Saved LLM configuration removed." if removed else " No saved LLM configuration found.")
        return
    if migrate:
        try:
            migrated = migrate_legacy_credentials()
        except (RuntimeError, ValueError) as error:
            raise click.ClickException(str(error)) from error
        click.echo(" Migrated the legacy API key to the OS credential store." if migrated else " No legacy plaintext API key found.")
        return
    current_cfg = load_global_api_credentials() or {}
    if not any((api_key, provider, api_format, base_url, model)):
        if current_cfg.get("config_error"):
            raise click.ClickException(current_cfg["config_error"])
        if current_cfg and current_cfg.get("provider"):
            click.echo(f" konman Core Configuration: Active Provider [{str(current_cfg.get('provider', 'openai')).upper()}]")
            click.echo(f"   API Format: {current_cfg.get('api_format', 'openai-compatible')}")
            click.echo(f"   API Base URL: {current_cfg.get('base_url', '')}")
            click.echo(f"   Default Model: {current_cfg.get('model', '')}")
            if current_cfg.get("api_key"):
                click.echo(f"   Stored Credential Token: ...{current_cfg.get('api_key')[-4:]}")
            elif current_cfg.get("credential_error"):
                click.echo(f"   Credential unavailable: {current_cfg['credential_error']}")
            elif current_cfg.get("legacy_plaintext_credential"):
                click.echo("   Legacy plaintext key found. Run `konman config --migrate` to secure it.")
        else:
            click.echo(" No global LLM configuration found. Run `konman config --help` for setup options.")
        return

    provider = provider or current_cfg.get("provider") or "openai"
    reusing_configured_provider = (
        str(current_cfg.get("provider", "")).casefold() == provider.casefold()
    )
    if reusing_configured_provider:
        api_key = api_key or current_cfg.get("api_key")
        api_format = api_format or current_cfg.get("api_format")
        base_url = base_url or current_cfg.get("base_url")
    try:
        llm_config = resolve_llm_configuration(provider, api_format, base_url)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    if llm_config["api_format"] != "ollama" and not api_key:
        raise click.UsageError("--api-key is required for hosted providers.")
    if not model:
        if llm_config["api_format"] == "ollama":
            model = "llama3.2"
        elif llm_config["api_format"] == "openai-compatible":
            model = "gpt-4o-mini"
        else:
            raise click.UsageError(f"--model is required for the {llm_config['api_format']} API format.")
    try:
        saved_path = save_global_api_credentials(
            api_key or "",
            llm_config["provider"],
            llm_config["base_url"],
            model,
            llm_config["api_format"],
        )
    except (RuntimeError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(f" Successfully locked structural credentials globally inside profile path: {saved_path}")
    click.echo(f" Provider [{provider}], format [{llm_config['api_format']}], model [{model}], API [{llm_config['base_url']}].")

def _resolve_raw_capture_dir(raw_payload: str):
    """Find .context/.raw by walking up from payload cwd, Cursor workspace_roots, or process cwd."""
    starts = []
    try:
        data = json.loads(raw_payload)
        if isinstance(data, dict):
            cwd = data.get("cwd")
            if isinstance(cwd, str) and cwd:
                starts.append(Path(cwd))
            roots = data.get("workspace_roots")
            if isinstance(roots, list) and roots and isinstance(roots[0], str):
                starts.append(Path(roots[0]))
    except Exception:
        pass
    starts.append(Path.cwd())
    seen = set()
    for start in starts:
        try:
            current = start.resolve()
        except Exception:
            continue
        for parent in [current, *current.parents]:
            key = str(parent)
            if key in seen:
                continue
            seen.add(key)
            ctx = parent / ".context"
            if ctx.is_dir():
                raw = ctx / ".raw"
                raw.mkdir(parents=True, exist_ok=True)
                return raw
    return None


def _strip_local_metadata(value):
    if isinstance(value, dict):
        cleaned = {}
        private_fields = {"cwd", "workspace_roots", "transcript_path", "project_root", "workspace_path"}
        for key, item in value.items():
            if str(key).casefold() in private_fields:
                continue
            if str(key).casefold() in {"path", "file_path", "filepath"} and isinstance(item, str) and Path(item).is_absolute():
                continue
            cleaned[key] = _strip_local_metadata(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_local_metadata(item) for item in value]
    return value


@main.command()
@click.option("--event", required=True, help="Triggering lifecycle event tracking property identifier.")
def hook(event):
    """Passive fail-open streaming logging trap execution pipeline configuration interface."""
    try:
        raw_payload = sys.stdin.read(2 * 1024 * 1024 + 1) if not sys.stdin.isatty() else ""
        if raw_payload:
            if len(raw_payload.encode("utf-8")) > 2 * 1024 * 1024:
                click.echo("Konman capture skipped: hook payload exceeds the 2 MiB limit.", err=True)
                sys.exit(0)
            raw_dir = _resolve_raw_capture_dir(raw_payload)
            if raw_dir is not None:
                custom_patterns = _custom_redaction_patterns(raw_dir.parent)
                safe_event = "".join(c if c.isalnum() or c in "-_" else "_" for c in event)
                try:
                    captured = _strip_local_metadata(json.loads(raw_payload))
                    redacted, redaction_count = redact_value(captured, custom_patterns)
                    if isinstance(redacted, dict):
                        redacted["konman_redaction_count"] = redaction_count
                    else:
                        redacted = {"payload": redacted, "konman_redaction_count": redaction_count}
                    stored = json.dumps(redacted, ensure_ascii=False, indent=2).encode("utf-8")
                except json.JSONDecodeError:
                    redacted_text, redaction_count = redact_text(raw_payload, custom_patterns)
                    stored = json.dumps({"text": redacted_text, "konman_redaction_count": redaction_count}, ensure_ascii=False, indent=2).encode("utf-8")
                filename = f"{safe_event}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}.json"
                create_new_bytes(raw_dir / filename, stored)
    except Exception as error:
        click.echo(f"Konman capture failed open: {error}", err=True)
        sys.exit(0)
    sys.exit(0)

def _mcp_context(engine, tool_name, arguments):
    yaml = YAML()
    if tool_name == "get_context":
        result = {
            "requirements": [], "decisions": [], "boundaries": [], "objects": [],
            "evidence": [], "changes": [], "questions": [], "risks": [],
            "current_state": None,
        }
        req_dir = engine.ctx_dir / "requirements"
        if req_dir.exists():
            for path in sorted(req_dir.glob("*.yaml")):
                node = yaml.load(path.read_text(encoding="utf-8"))
                if node and node.get("status") == "active":
                    result["requirements"].append(node)
        dec_dir = engine.ctx_dir / "decisions"
        if dec_dir.exists():
            for path in sorted(dec_dir.glob("*.yaml")):
                node = yaml.load(path.read_text(encoding="utf-8"))
                if node and node.get("status") in ("active", "needs_review"):
                    result["decisions"].append(node)
        boundaries_path = engine.ctx_dir / "boundaries.yaml"
        if boundaries_path.exists():
            boundaries = yaml.load(boundaries_path.read_text(encoding="utf-8")) or []
            boundaries = [boundaries] if isinstance(boundaries, dict) else boundaries
            result["boundaries"] = [
                item for item in boundaries
                if isinstance(item, dict) and item.get("status") not in ("proposed", "rejected")
            ]
        active_statuses = {
            "objects": ({"active"}, "active"),
            "evidence": ({"active"}, "active"),
            "changes": ({"active"}, "proposed"),
            "questions": ({"open", "deferred"}, "open"),
            "risks": ({"open", "mitigated", "accepted"}, "open"),
        }
        for kind, (statuses, default_status) in active_statuses.items():
            directory = engine.ctx_dir / kind
            if directory.is_dir():
                for path in sorted(directory.glob("*.yaml")):
                    node = yaml.load(path.read_text(encoding="utf-8"))
                    if node and node.get("status", default_status) in statuses:
                        result[kind].append(node)
        current_path = engine.ctx_dir / "state" / "current.yaml"
        if current_path.exists():
            result["current_state"] = current_path.read_text(encoding="utf-8")
        return result

    if tool_name == "get_boundaries":
        boundaries_path = engine.ctx_dir / "boundaries.yaml"
        if not boundaries_path.exists():
            return []
        boundaries = yaml.load(boundaries_path.read_text(encoding="utf-8")) or []
        if isinstance(boundaries, dict):
            boundaries = [boundaries]
        boundaries = [
            item for item in boundaries
            if isinstance(item, dict) and item.get("status") not in ("proposed", "rejected")
        ]
        requested_path = arguments.get("path")
        if requested_path:
            boundaries = [item for item in boundaries if item.get("path") and (requested_path == item["path"] or requested_path.startswith(item["path"].rstrip("/") + "/"))]
        return boundaries

    if tool_name == "search_decisions":
        query = str(arguments.get("query", "")).casefold()
        decisions = []
        dec_dir = engine.ctx_dir / "decisions"
        if dec_dir.exists():
            for path in sorted(dec_dir.glob("*.yaml")):
                node = yaml.load(path.read_text(encoding="utf-8"))
                if not node or node.get("status") not in ("active", "needs_review"):
                    continue
                haystack = json.dumps(node, ensure_ascii=False, default=str).casefold()
                if not query or query in haystack:
                    decisions.append(node)
        return decisions

    if tool_name == "list_context_nodes":
        node_type = arguments.get("type")
        collections = {
            "requirements": ("requirements", {"active", "proposed"}, "active"),
            "decisions": ("decisions", {"active", "needs_review", "proposed"}, "active"),
            "objects": ("objects", {"active", "proposed"}, "active"),
            "evidence": ("evidence", {"active", "proposed"}, "active"),
            "changes": ("changes", {"active", "proposed"}, "proposed"),
            "questions": ("questions", {"open", "deferred", "proposed"}, "open"),
            "risks": ("risks", {"open", "mitigated", "accepted", "proposed"}, "open"),
        }
        if node_type not in collections:
            raise ValueError("type must be one of: " + ", ".join(collections))
        folder, statuses, default_status = collections[node_type]
        directory = engine.ctx_dir / folder
        records = []
        if directory.is_dir():
            for path in sorted(directory.glob("*.yaml")):
                node = yaml.load(path.read_text(encoding="utf-8"))
                if node and node.get("status", default_status) in statuses:
                    records.append(node)
        return records
    raise ValueError(f"Unknown tool: {tool_name}")


@main.command()
@click.option("--dir", default=".", help="Target project root directory location.")
def mcp(dir):
    """Run the Konman read-only Model Context Protocol server over stdio."""
    engine = ContextEngine(dir)
    tools = [
        {"name": "get_context", "description": "Read active project requirements, decisions, boundaries, objects, evidence, changes, questions, risks, and current state.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "get_boundaries", "description": "List protected paths, optionally filtered to a path.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "additionalProperties": False}},
        {"name": "search_decisions", "description": "Search recorded decisions by text.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "additionalProperties": False}},
        {"name": "list_context_nodes", "description": "List active and proposed records for a context node type.", "inputSchema": {"type": "object", "properties": {"type": {"type": "string", "enum": ["requirements", "decisions", "objects", "evidence", "changes", "questions", "risks"]}}, "required": ["type"], "additionalProperties": False}},
    ]

    def send(message):
        sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                send({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
                continue
            request_id = request.get("id")
            method = request.get("method")
            if method == "notifications/initialized":
                continue
            if method == "initialize":
                params = request.get("params") or {}
                send({"jsonrpc": "2.0", "id": request_id, "result": {
                    "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "konman", "version": __version__},
                }})
            elif method == "ping":
                send({"jsonrpc": "2.0", "id": request_id, "result": {}})
            elif method == "tools/list":
                send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}})
            elif method == "tools/call":
                params = request.get("params") or {}
                try:
                    result = _mcp_context(engine, params.get("name"), params.get("arguments") or {})
                    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
                    send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text}], "isError": False}})
                except Exception as error:
                    send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": str(error)}], "isError": True}})
            elif request_id is not None:
                send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}})
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})

_HOOK_START = "# >>> konman managed pre-commit"
_HOOK_END = "# <<< konman managed pre-commit"


def _pre_commit_path(project_dir):
    root = Path(project_dir).resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks/pre-commit"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else root / path


def _managed_hook_block():
    return (
        f"{_HOOK_START}\n"
        "repository_root=$(git rev-parse --show-toplevel) || exit 1\n"
        "if ! konman check --dir \"$repository_root\"; then\n"
        "    echo '[Konman] Commit aborted: resolve context graph review errors first.' >&2\n"
        "    exit 1\n"
        "fi\n"
        f"{_HOOK_END}\n"
    )


@main.command()
@click.option("--dir", default=".", help="Target project root directory location.")
def disable_hooks(dir):
    """Remove only the Konman-managed block from the Git pre-commit hook."""
    try:
        pre_commit_file = _pre_commit_path(dir)
    except (OSError, subprocess.CalledProcessError):
        raise click.ClickException("Target folder is not inside a valid Git repository.")
    if not pre_commit_file.exists():
        click.echo(" No pre-commit hook found. Nothing to disable.")
        return
    content = pre_commit_file.read_text(encoding="utf-8", errors="replace")
    start = content.find(_HOOK_START)
    end = content.find(_HOOK_END, start + len(_HOOK_START)) if start >= 0 else -1
    if start < 0 or end < 0:
        click.echo(" No marked Konman hook block found; existing hook was left unchanged.")
        return
    line_start = content.rfind("\n", 0, start) + 1
    line_end = content.find("\n", end + len(_HOOK_END))
    line_end = len(content) if line_end < 0 else line_end + 1
    remaining = content[:line_start] + content[line_end:]
    if not remaining.strip() or remaining.strip() == "#!/bin/sh":
        pre_commit_file.unlink()
    else:
        pre_commit_file.write_text(remaining, encoding="utf-8", newline="\n")
    click.echo(" Removed the Konman pre-commit block; other hook content was preserved.")

@main.command(name="setup-hooks")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_hooks(dir):
    """Install an idempotent, marked verification block into Git's pre-commit hook."""
    try:
        pre_commit_file = _pre_commit_path(dir)
        pre_commit_file.parent.mkdir(parents=True, exist_ok=True)
        content = pre_commit_file.read_text(encoding="utf-8", errors="replace") if pre_commit_file.exists() else ""
        if _HOOK_START in content and _HOOK_END in content:
            click.echo(" Konman pre-commit block is already installed.")
            return
        if not content:
            content = "#!/bin/sh\n"
        if content.startswith("#!"):
            first_line_end = content.find("\n")
            first_line_end = len(content) if first_line_end < 0 else first_line_end + 1
            content = content[:first_line_end] + _managed_hook_block() + content[first_line_end:]
        else:
            content = _managed_hook_block() + content
        pre_commit_file.write_text(content, encoding="utf-8", newline="\n")
        if os.name != "nt":
            import stat
            current_mode = os.stat(pre_commit_file).st_mode
            os.chmod(pre_commit_file, current_mode | stat.S_IEXEC)
        click.echo(f" Installed Konman validation in {pre_commit_file}.")
    except (OSError, subprocess.CalledProcessError) as error:
        raise click.ClickException(f"Could not install Git pre-commit hook: {error}") from error

if __name__ == "__main__":
    main()
