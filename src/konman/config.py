import os
import json
from pathlib import Path
from datetime import datetime

def inject_antigravity_hooks(target_dir: str):
    """Register konman directly inside the environment settings matching Antigravity schemas."""
    home = Path.home()
    ag_configs = [
        home / ".gemini/antigravity/mcp_config.json",
        home / ".gemini/config/mcp_config.json"
    ]
    
    mcp_injection = {
        "command": "konman",
        "args": ["mcp"],
        "env": {"PYTHONUNBUFFERED": "1"}
    }

    for path in ag_configs:
        if path.parent.exists():
            config_data = {}
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        config_data = json.load(f)
                except Exception:
                    config_data = {}
            
            if "mcpServers" not in config_data:
                config_data["mcpServers"] = {}
                
            config_data["mcpServers"]["konman"] = mcp_injection
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)

    hooks_dir = Path(target_dir) / ".agents"
    hooks_dir.mkdir(exist_ok=True)
    hooks_file = hooks_dir / "hooks.json"
    
    hooks_payload = {
        "hooks": [
            {"event": "UserPromptSubmit", "command": "konman", "args": ["hook", "--event", "UserPromptSubmit"], "fail_mode": "open"},
            {"event": "SessionEnd", "command": "konman", "args": ["hook", "--event", "SessionEnd"], "fail_mode": "open"}
        ]
    }
    with open(hooks_file, "w", encoding="utf-8") as f:
        json.dump(hooks_payload, f, indent=2)

def inject_claude_code_adapters(target_dir: str):
    """Enforce context mapping pointers layout compatible with Claude Code interface files."""
    base = Path(target_dir)
    claude_md = base / "CLAUDE.md"
    if not claude_md.exists():
        with open(claude_md, "w", encoding="utf-8") as f:
            f.write(
                "# CLAUDE.md Configuration Instructions\n\n"
                "System instructions and constraints for this repository are centralized.\n"
                "Please read the structural system rules from **AGENTS.md** before processing builds.\n"
            )

def inject_codex_adapters(target_dir: str):
    """Appends configurations to guarantee cross-compatibility across Codex runtime tracks."""
    base = Path(target_dir)
    codex_hook_dir = base / ".codex"
    codex_hook_dir.mkdir(exist_ok=True)

def inject_vsc_copilot_adapters(target_dir: str):
    """Generates custom context integration patterns for VS Code Copilot."""
    base = Path(target_dir)
    github_dir = base / ".github"
    github_dir.mkdir(exist_ok=True)
    
    copilot_md = github_dir / "copilot-instructions.md"
    if not copilot_md.exists():
        with open(copilot_md, "w", encoding="utf-8") as f:
            f.write(
                "# VS Code Copilot Workspace Instructions\n\n"
                "This project uses a codebase context management tool framework.\n"
                "Before altering files or architecture paths, look up hard architectural boundary constraints inside **AGENTS.md**.\n"
            )

def inject_cursor_adapters(target_dir: str):
    """Generates custom system rules `.mdc` file layers with dynamic globs inside Cursor spaces."""
    base = Path(target_dir)
    cursor_rules_dir = base / ".cursor" / "rules"
    cursor_rules_dir.mkdir(parents=True, exist_ok=True)
    
    conman_mdc = cursor_rules_dir / "konman-context.mdc"
    if not conman_mdc.exists():
        with open(conman_mdc, "w", encoding="utf-8") as f:
            f.write(
                "---\n"
                "description: Enforce global first-principles architectural constraints mapped by konman\n"
                "globs: \"*\"\n"
                "alwaysApply: true\n"
                "---\n\n"
                "# 📌 Cursor Workspace Execution Directive\n\n"
                "This codebase relies on version-controlled semantic context metadata blocks.\n"
                "Before processing code modifications, you MUST verify active requirements, tradeoffs, and protected path criteria inside **AGENTS.md**.\n"
            )

def inject_kiro_adapters(target_dir: str):
    """Deploys explicit semantic context files matching Kiro agent system steering schemas."""
    base = Path(target_dir)
    kiro_steering_dir = base / ".kiro" / "steering"
    kiro_steering_dir.mkdir(parents=True, exist_ok=True)
    
    kiro_md = kiro_steering_dir / "context_steering.md"
    if not kiro_md.exists():
        with open(kiro_md, "w", encoding="utf-8") as f:
            f.write(
                "# 🚀 Kiro System Steering Context Map\n\n"
                "This file routes background project intent to the Kiro model loop engine.\n"
                "Please cross-reference constraints with the master mapping index generated at **AGENTS.md**.\n"
            )

def save_global_api_credentials(api_key: str, provider: str = "openai") -> str:
    """Persists API credentials globally inside the user's home configuration directory path."""
    config_dir = Path.home() / ".config" / "konman"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    
    payload = {
        "provider": provider,
        "api_key": api_key,
        "configured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        
    if os.name != "nt":
        os.chmod(config_file, 0o600)
    return str(config_file)

def load_global_api_credentials() -> dict:
    """Loads globally mapped authentication parameters from the home configuration directory."""
    config_file = Path.home() / ".config" / "konman" / "config.json"
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}
