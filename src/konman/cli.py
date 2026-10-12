import sys
import glob
import os
import click
from pathlib import Path
from datetime import datetime
from ruamel.yaml import YAML
from konman.engine import ContextEngine
from konman.config import (
    inject_antigravity_hooks, inject_claude_code_adapters, inject_codex_adapters,
    inject_vsc_copilot_adapters, inject_cursor_adapters, inject_kiro_adapters,
    save_global_api_credentials, load_global_api_credentials
)

class ConmanTopLevelGroup(click.Group):
    def format_help(self, ctx, formatter):
        formatter.write_usage(ctx.command_path, "[COMMAND] [OPTIONS]")
        formatter.write_paragraph()
        formatter.write_text("🧠 konman (Context Manager): Automated, LLM-Agnostic Codebase Context Engine.")
        
        commands = self.list_commands(ctx)
        core_cmds = [c for c in commands if c in ["init", "setup", "sync", "state", "record", "resolve", "check", "config", "setup-hooks", "disable-hooks"]]
        pipe_cmds = [c for c in commands if c in ["tail", "mine", "extract", "handoff", "hook", "mcp"]]
        
        if core_cmds:
            with formatter.section("🎯 Core Workspace Management Commands"):
                formatter.write_dl([(c, self.get_command(ctx, c).get_short_help_str()) for c in core_cmds])
        if pipe_cmds:
            with formatter.section("🔌 Context Extraction & Lifecycle Pipelines"):
                formatter.write_dl([(c, self.get_command(ctx, c).get_short_help_str()) for c in pipe_cmds])
        self.format_options(ctx, formatter)

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
    click.echo(f"✨ Initialized .context folder array framework inside: {engine.base_dir}")

@main.group(name="setup")
def setup_group():
    """Inject specialized adapter workspace configurations for your preferred dev tool."""
    pass

@setup_group.command(name="antigravity")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_antigravity(dir):
    """Inject background tracking hooks and local server pointers into Antigravity configurations."""
    engine = ContextEngine(dir)
    engine.init_folders()
    inject_antigravity_hooks(dir)
    engine.compile_agents_md()
    click.echo("🚀 Injected system bindings across Antigravity successfully.")

@setup_group.command(name="claude-code")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_claude_code(dir):
    """Generate localized CLAUDE.md routing pointers for Claude Code CLI."""
    engine = ContextEngine(dir)
    engine.init_folders()
    inject_claude_code_adapters(dir)
    engine.compile_agents_md()
    click.echo("🚀 Injected system bindings across Claude Code successfully.")

@setup_group.command(name="codex")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_codex(dir):
    """Deploy workspace directory tracking layouts matching Codex specification tracks."""
    engine = ContextEngine(dir)
    engine.init_folders()
    inject_codex_adapters(dir)
    engine.compile_agents_md()
    click.echo("🚀 Injected system bindings across Codex successfully.")

@setup_group.command(name="vsc-copilot")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_vsc_copilot(dir):
    """Generate .github/copilot-instructions.md configuration files for VS Code Copilot."""
    engine = ContextEngine(dir)
    engine.init_folders()
    inject_vsc_copilot_adapters(dir)
    engine.compile_agents_md()
    click.echo("🚀 Injected system bindings across VS Code Copilot successfully.")

@setup_group.command(name="cursor")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_cursor(dir):
    """Generate .cursor/rules/ global metadata adapters for Cursor IDE."""
    engine = ContextEngine(dir)
    engine.init_folders()
    inject_cursor_adapters(dir)
    engine.compile_agents_md()
    click.echo("🚀 Injected system bindings across Cursor successfully.")

@setup_group.command(name="kiro")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_kiro(dir):
    """Deploy workspace directory configurations for Kiro agent steering engines."""
    engine = ContextEngine(dir)
    engine.init_folders()
    inject_kiro_adapters(dir)
    engine.compile_agents_md()
    click.echo("🚀 Injected system bindings across Kiro successfully.")

@main.command()
@click.option("--dir", default=".", help="Target project root directory location.")
def sync(dir):
    """Force cross-dependency checks, process structural changes, and refresh AGENTS.md."""
    engine = ContextEngine(dir)
    stale_updates = engine.process_staleness_propagation()
    engine.compile_agents_md()
    click.echo(f"🔄 Graph database synchronization complete. Flagged {stale_updates} decisions for review updates.")

@main.command()
@click.option("--dir", default=".", help="Target project root directory location.")
def check(dir):
    """Audit the local context data layout for unresolved reviews or stale dependency tracks."""
    engine = ContextEngine(dir)
    violations = engine.check_graph_validity()
    if violations:
        click.echo("⚠️  CONTEXT INTEGRITY VALIDATION FAILED:")
        for v in violations:
            click.echo(f"  ❌ {v}")
        sys.exit(1)
    click.echo("🟢 Context mapping validated. No unresolved structural anomalies located.")
    sys.exit(0)

@main.command()
@click.option("--dir", default=".", help="Target project root directory location.")
def state(dir):
    """Render an interactive high-level dashboard map of current codebase architectural contexts."""
    engine = ContextEngine(dir)
    yaml = YAML()
    if not engine.ctx_dir.exists():
        click.echo("❌ No context database found in this workspace directory. Run 'konman init' first.")
        return

    click.echo("\n======================================================================")
    click.echo(f"📊 KONMAN CONTEXT DATABASE STATUS MATRIX: {engine.base_dir.name.upper()}")
    click.echo("======================================================================\n")

    click.echo("📌 ACTIVE SYSTEM ARCHITECTURAL REQUIREMENTS:")
    req_dir = engine.ctx_dir / "requirements"
    has_reqs = False
    if req_dir.exists():
        for p in req_dir.glob("*.yaml"):
            with open(p, "r", encoding="utf-8") as f:
                r = yaml.load(f)
                if r and r.get("status") == "active":
                    has_reqs = True
                    click.echo(f"  ├─ {r.get('id')} [{r.get('kind').upper()}]: {r.get('statement')}")
                    if r.get("why"):
                        click.echo(f"  │  └── 🧠 Why: {r.get('why')}")
    if not has_reqs:
        click.echo("  └─ (No active requirements mapped to this repository yet)")

    click.echo("\n🧠 RECENT ARCHITECTURAL TRADEOFF DECISIONS:")
    dec_dir = engine.ctx_dir / "decisions"
    has_decs = False
    if dec_dir.exists():
        for p in dec_dir.glob("*.yaml"):
            with open(p, "r", encoding="utf-8") as f:
                d = yaml.load(f)
                if d:
                    has_decs = True
                    status_indicator = "🟢 [ACTIVE]" if d.get("status") == "active" else "⚠️  [REVIEW]"
                    click.echo(f"  ├─ {d.get('id')} Chosen: {d.get('chosen').upper()} -- {status_indicator}")
                    if d.get("reason"):
                        click.echo(f"  │  ├── Rationale: {d.get('reason')}")
                    rejected_opts = [c.get("object") for c in d.get("considered", []) if c.get("verdict") == "rejected"]
                    if rejected_opts:
                        click.echo(f"  │  └── ❌ Rejected Options: {', '.join(rejected_opts)}")
    if not has_decs:
        click.echo("  └─ (No architectural tradeoff items logged in database layout)")

    click.echo("\n🔌 UNTRACKED BACKGROUND DATA CAPTURE QUEUE:")
    raw_dir = engine.ctx_dir / ".raw"
    untracked_files = [f.name for f in raw_dir.iterdir() if f.is_file()] if raw_dir.exists() else []
    if untracked_files:
        click.echo(f"  ⚠️  [PENDING] There are {len(untracked_files)} raw context history log packet files waiting.")
        click.echo("     👉 Run 'konman extract' to automatically parse and promote them to your database.")
    else:
        click.echo("  🟢 No untracked history data packets currently idling inside your background raw queue pipes.")
    click.echo("\n======================================================================\n")

@main.command()
@click.option("--type", "-t", required=True, type=click.Choice(["requirement", "decision", "boundary"]), help="The type of context entity to create.")
@click.option("--id", "-i", required=True, help="Unique identifier (e.g., R-101, D-002, B-001).")
@click.option("--dir", default=".", help="Target project root directory location.")
def record(type, id, dir):
    """Manually record an entity (Requirement, Decision, Boundary) into the data graph."""
    engine = ContextEngine(dir)
    engine.init_folders()
    yaml = YAML()
    yaml.preserve_quotes = True
    timestamp = datetime.now().strftime("%Y-%m-%d")

    if type == "requirement":
        statement = click.prompt("📋 Enter the core Requirement statement")
        kind = click.prompt("🏷️  Kind", type=click.Choice(["hard", "preference"]), default="hard")
        why = click.prompt("🧠 Why is this requirement needed?", default="")
        payload = {"id": id, "statement": statement, "kind": kind, "priority": "high" if kind == "hard" else "medium", "source": {"who": "human:dev", "when": timestamp}, "why": why if why else None, "status": "active"}
        target_path = engine.ctx_dir / "requirements" / f"{id}.yaml"
    elif type == "decision":
        chosen = click.prompt("✅ Chosen candidate/object name")
        mode = click.prompt("🛠️  Decision mode", type=click.Choice(["compared", "default", "forced", "taste"]), default="compared")
        reason = click.prompt("🧠 Reason or tradeoff summary", default="")
        considered = []
        if mode == "compared":
            while click.confirm("🔄 Would you like to record a rejected alternative option?"):
                alt_name = click.prompt("❌ Rejected object/technology name")
                fail_prop = click.prompt(f"🔍 Which property caused {alt_name} to fail?")
                fail_req = click.prompt(f"🔗 Which Requirement ID did it violate?")
                considered.append({"object": alt_name, "properties": [{"key": fail_prop, "value": True, "evidence": "documented"}], "evaluations": [{"req": fail_req, "result": "fail", "via": fail_prop}], "verdict": "rejected"})
        considered.append({"object": chosen, "properties": [], "evaluations": [], "verdict": "selected"})
        payload = {"id": id, "chosen": chosen, "mode": mode, "decided": {"who": "human:dev", "when": timestamp}, "considered": considered, "reason": reason if reason else None, "status": "active"}
        target_path = engine.ctx_dir / "decisions" / f"{id}.yaml"
    elif type == "boundary":
        path_str = click.prompt("📁 Enter the codebase file path to protect")
        why = click.prompt("🧠 Why must this boundary be enforced?", default="")
        payload = {"path": path_str, "rule": "no_edit_without_approval", "why": why, "constrains": []}
        target_path = engine.ctx_dir / "boundaries.yaml"

    with open(target_path, "w", encoding="utf-8") as f:
        yaml.dump(payload, f)
    engine.compile_agents_md()
    click.echo(f"🎉 Successfully saved and synced {id} to the context database layer!")

@main.command()
@click.argument("id")
@click.option("--dir", default=".", help="Target project root directory location.")
def resolve(id, dir):
    """Interactively reconcile and repair a decision node flagged with review states."""
    engine = ContextEngine(dir)
    yaml = YAML()
    yaml.preserve_quotes = True
    target_path = engine.ctx_dir / "decisions" / f"{id}.yaml"
    
    if not target_path.exists():
        click.echo(f"❌ Error: No decision node with ID '{id}' located inside the database matrix.")
        return

    with open(target_path, "r", encoding="utf-8") as f:
        d = yaml.load(f)

    click.echo(f"\n🛠️  Reconciling Stale State Flag for Decision: {id}")
    new_reason = click.prompt("🧠 Enter the updated tradeoff justification for keeping this choice")
    
    if click.confirm("🟢 Reset status back to 'active' and clear git blocking flags?"):
        d["reason"] = new_reason
        d["status"] = "active"
        with open(target_path, "w", encoding="utf-8") as f:
            yaml.dump(d, f)
        engine.compile_agents_md()
        click.echo(f"🎉 Graph healed! Decision '{id}' is now active. Git hooks unblocked.")

@main.command()
@click.option("--count", "-c", default=10, help="Number of historical commit messages back to process.")
@click.option("--dir", default=".", help="Target project root directory location.")
def mine(count, dir):
    """Parse local Git repository commit messages history trail to capture contextual explanation data logs."""
    engine = ContextEngine(dir)
    click.echo(f"⛏️  Mining the last {count} git commits for architectural reasoning clues...")
    extracted = engine.mine_git_history(count)
    click.echo(f"🎉 History archeology complete! Extracted [{extracted}] raw context dumps into .context/.raw/")

@main.command()
@click.option("--dir", default=".", help="Target project root directory location.")
def tail(dir):
    """Scan and merge deeply nested VS Code Copilot extension logs into a continuous history."""
    engine = ContextEngine(dir)
    raw_dir = engine.ctx_dir / ".raw"
    user_home = Path.home()
    search_pattern = os.path.join(user_home, "AppData", "Roaming", "Code", "logs", "**", "GitHub.copilot-chat", "GitHub Copilot Chat.log")
    
    log_files = glob.glob(search_pattern, recursive=True)
    valid_files = [f for f in log_files if os.path.isfile(f)]
    if not valid_files:
        click.echo("⚠️ No active background Copilot log streams detected.")
        return

    latest_log = max(valid_files, key=os.path.getmtime)
    try:
        with open(latest_log, "r", encoding="utf-8", errors="ignore") as f:
            new_log_content = f.read().strip()
        if not new_log_content:
            return

        history_file = raw_dir / "copilot_history.log"
        with open(history_file, "w", encoding="utf-8") as out:
            out.write(new_log_content)
        click.echo(f"🎉 Successfully pulled previous prompts into: .context/.raw/copilot_history.log")
    except Exception as e:
        click.echo(f"❌ Error: {str(e)}")

@main.command()
@click.option("--api-key", envvar="OPENAI_API_KEY", help="Your OpenAI API credentials key parameter.")
@click.option("--model", default="gpt-4o-mini", help="Target LLM model selector pass value.")
@click.option("--dir", default=".", help="Target project root directory location.")
def extract(api_key, model, dir):
    """Passively scan untracked file histories inside .raw/ and use an LLM to distill YAML nodes automatically."""
    if not api_key:
        global_cfg = load_global_api_credentials()
        if global_cfg and global_cfg.get("api_key"):
            api_key = global_cfg.get("api_key")
        elif os.environ.get("OPENAI_API_KEY"):
            api_key = os.environ.get("OPENAI_API_KEY")
        else:
            click.echo("❌ Error: No API credentials located. Configure your global key using: konman config -k <key>")
            sys.exit(1)

    engine = ContextEngine(dir)
    history_file = engine.ctx_dir / ".raw" / "copilot_history.log"
    if not history_file.exists():
        click.echo("😴 No untracked history file found inside .context/.raw/. Run 'konman tail' first.")
        return

    click.echo(f"🤖 Shipping transcript data stream over to LLM [{model}] for semantic processing...")
    with open(history_file, "r", encoding="utf-8", errors="ignore") as f:
        raw_text = f.read()[:15000]
        
    structured_json_str = engine.execute_llm_distillation(raw_text, api_key, model)
    try:
        import json
        extracted_data = json.loads(structured_json_str)
        yaml = YAML()
        
        for r in extracted_data.get("requirements", []):
            r["status"] = "active"
            r["source"] = {"who": f"llm:{model}", "when": datetime.now().strftime("%Y-%m-%d")}
            with open(engine.ctx_dir / "requirements" / f"{r['id']}.yaml", "w", encoding="utf-8") as out:
                yaml.dump(r, out)
            click.echo(f"   ✨ Synthesized Requirement Node: {r['id']}")

        for d in extracted_data.get("decisions", []):
            d["status"] = "active"
            d["decided"] = {"who": f"llm:{model}", "when": datetime.now().strftime("%Y-%m-%d")}
            d["considered"] = [{"object": d["chosen"], "properties": [], "evaluations": [], "verdict": "selected"}]
            with open(engine.ctx_dir / "decisions" / f"{d['id']}.yaml", "w", encoding="utf-8") as out:
                yaml.dump(d, out)
            click.echo(f"   ✨ Synthesized Decision Node: {d['id']}")
            
        engine.compile_agents_md()
        click.echo("🎉 Semantic code extraction pass complete!")
    except Exception as e:
        click.echo(f"❌ Failed to parse LLM payload responses: {str(e)}")

@main.command(name="handoff")
@click.argument("previous_tool")
@click.argument("next_tool")
@click.option("--dir", default=".", help="Target project root directory location.")
def handoff(previous_tool, next_tool, dir):
    """Compile context package for the next model and instantly hot-swap active project rules adapters."""
    engine = ContextEngine(dir)
    click.echo(f"📦 Initiating seamless context transit migration from [{previous_tool}] to [{next_tool}]...")
    
    if next_tool == "antigravity":
        inject_antigravity_hooks(dir)
    elif next_tool == "claude-code":
        inject_claude_code_adapters(dir)
    elif next_tool == "vsc-copilot":
        inject_vsc_copilot_adapters(dir)
    elif next_tool == "cursor":
        inject_cursor_adapters(dir)
    elif next_tool == "kiro":
        inject_kiro_adapters(dir)
    else:
        click.echo(f"⚠️ Unknown destination adapter environment: {next_tool}. Configuration skipped.")
        
    engine.compile_agents_md()
    click.echo(f"🎉 Context migration completed successfully! AGENTS.md recompiled matching {next_tool} guidelines.")

@main.command(name="config")
@click.option("--api-key", "-k", help="Your developer platform API credential string.")
@click.option("--provider", "-p", default="openai", type=click.Choice(["openai"]), help="Target interface platform router configuration baseline.")
def config_command(api_key, provider):
    """Securely register or inspect global developer LLM API configurations across your system environment."""
    if not api_key:
        current_cfg = load_global_api_credentials()
        if current_cfg and current_cfg.get("api_key"):
            click.echo(f"🔒 konman Core Configuration: Active Provider [{current_cfg.get('provider').upper()}]")
            click.echo(f"   Stored Credential Token: sk-...{current_cfg.get('api_key')[-4:]}")
        else:
            click.echo("❌ Error: No global key configured. Register using: konman config -k <key>")
        return
    saved_path = save_global_api_credentials(api_key, provider)
    click.echo(f"🚀 Successfully locked structural credentials globally inside profile path: {saved_path}")

@main.command()
@click.option("--event", required=True, help="Triggering lifecycle event tracking property identifier.")
def hook(event):
    """Passive fail-open streaming logging trap execution pipeline configuration interface."""
    try:
        raw_payload = sys.stdin.read() if not sys.stdin.isatty() else ""
        if raw_payload:
            raw_dir = Path(".context/.raw")
            if raw_dir.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                with open(raw_dir / f"{event}_{timestamp}.json", "w", encoding="utf-8") as f:
                    f.write(raw_payload)
    except Exception:
        sys.exit(0)
    sys.exit(0)

@main.command()
def mcp():
    """Interactive protocol listener layer matching baseline standard MCP JSON-RPC routing frameworks."""
    click.echo("Context Manager MCP Engine Online Active Terminal State loop placeholder.", err=True)
    sys.exit(0)

@main.command()
@click.option("--dir", default=".", help="Target project root directory location.")
def disable_hooks(dir):
    """Remove and disable the konman validation guardrail from your local Git pre-commit workflow."""
    engine = ContextEngine(dir)
    pre_commit_file = Path(dir) / ".git" / "hooks" / "pre-commit"
    
    if not pre_commit_file.parent.exists():
        click.echo("❌ Error: Target folder is not a valid Git repository root.")
        sys.exit(1)
        
    if not pre_commit_file.exists():
        click.echo("✨ No active Git pre-commit hooks found. Nothing to disable.")
        return
        
    try:
        # Read the file to see if it belongs to konman or a third-party tool
        with open(pre_commit_file, "r", encoding="utf-8") as f:
            content = f.read()
            
        if "konman check" in content:
            # Safely delete the konman hook script file
            pre_commit_file.unlink()
            click.echo("🛑 Successfully removed 'konman check' guardrails from your Git pre-commit lifecycle hooks.")
        else:
            click.echo("⚠️  The active pre-commit file belongs to a third-party tool. Skipping removal to avoid data loss.")
            click.echo("👉 If you want to disable it manually, edit or delete: .git/hooks/pre-commit")
            
    except Exception as e:
        click.echo(f"❌ Failed to disable pre-commit script loop: {str(e)}")
        sys.exit(1)

@main.command(name="setup-hooks")
@click.option("--dir", default=".", help="Target project root directory location.")
def setup_hooks(dir):
    """Inject a pre-configured verification shell script loop directly into your local Git workflow gates."""
    engine = ContextEngine(dir)
    
    # Safely resolve git directory locations using pathlib attributes
    git_dir = Path(dir).resolve() / ".git"
    
    if not git_dir.exists():
        click.echo("❌ Error: Target folder is not a valid Git repository root. Run 'git init' first.")
        sys.exit(1)
        
    git_hooks_dir = git_dir / "hooks"
    git_hooks_dir.mkdir(exist_ok=True)
    
    pre_commit_file = git_hooks_dir / "pre-commit"
    
    # Standard shell script trap directing validation steps to 'konman check'
    hook_content = (
        "#!/bin/sh\n"
        "echo '🔍 [Konman] Verifying active codebase context data graph integrity...'\n"
        "konman check\n"
        "if [ $? -ne 0 ]; then\n"
        "    echo '❌ [Konman] Git commit aborted. Fix outstanding stale context files or clear needs_review tags first.'\n"
        "    exit 1\n"
        "fi\n"
    )
    
    try:
        # Enforce UTF-8 write streams to bypass Windows locale codec blockages
        with open(pre_commit_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(hook_content)
            
        # Grant execution permissions explicitly on macOS/Linux/Git Bash environments
        if os.name != "nt":
            import stat
            current_mode = os.stat(pre_commit_file).st_mode
            os.chmod(pre_commit_file, current_mode | stat.S_IEXEC)
            
        click.echo("🚀 Successfully linked 'konman check' into .git/hooks/pre-commit gate runner!")
    except Exception as e:
        click.echo(f"❌ Failed to write Git pre-commit script hook: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
