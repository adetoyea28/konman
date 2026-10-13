import os
import json
from pathlib import Path
from datetime import datetime
from konman.storage import atomic_write_json

HOOK_CMD = "konman hook --event"
API_FORMATS = ("openai-compatible", "anthropic", "gemini", "ollama")

PROVIDER_DEFAULTS = {
    "openai": ("openai-compatible", "https://api.openai.com/v1"),
    "anthropic": ("anthropic", "https://api.anthropic.com/v1"),
    "claude": ("anthropic", "https://api.anthropic.com/v1"),
    "gemini": ("gemini", "https://generativelanguage.googleapis.com/v1beta"),
    "google": ("gemini", "https://generativelanguage.googleapis.com/v1beta"),
    "ollama": ("ollama", "http://localhost:11434"),
    "openrouter": ("openai-compatible", "https://openrouter.ai/api/v1"),
    "groq": ("openai-compatible", "https://api.groq.com/openai/v1"),
    "deepseek": ("openai-compatible", "https://api.deepseek.com"),
    "together": ("openai-compatible", "https://api.together.xyz/v1"),
    "xai": ("openai-compatible", "https://api.x.ai/v1"),
    "mistral": ("openai-compatible", "https://api.mistral.ai/v1"),
    "perplexity": ("openai-compatible", "https://api.perplexity.ai"),
    "fireworks": ("openai-compatible", "https://api.fireworks.ai/inference/v1"),
    "cerebras": ("openai-compatible", "https://api.cerebras.ai/v1"),
}


def resolve_llm_configuration(provider: str, api_format: str = None, base_url: str = None) -> dict:
    """Resolve a known provider or validate a user-supplied provider endpoint/format."""
    provider_key = provider.strip().casefold()
    if api_format and api_format not in API_FORMATS:
        raise ValueError(f"Unsupported API format '{api_format}'. Choose from: {', '.join(API_FORMATS)}")
    defaults = PROVIDER_DEFAULTS.get(provider_key)
    resolved_format = api_format or (defaults[0] if defaults else "openai-compatible")
    resolved_url = (base_url or (defaults[1] if defaults else "")).rstrip("/")
    if not resolved_url:
        raise ValueError("A custom provider requires --base-url (the API root URL).")
    return {"provider": provider.strip(), "api_format": resolved_format, "base_url": resolved_url}


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read existing configuration {path}: {error}") from error
    if not isinstance(data, type(default)):
        raise ValueError(f"Configuration {path} must contain a {type(default).__name__}.")
    return data


def _dump_json(path: Path, payload) -> None:
    atomic_write_json(path, payload)


def _contains_konman_hook(value) -> bool:
    if isinstance(value, str):
        return "konman hook" in value
    if isinstance(value, dict):
        return any(_contains_konman_hook(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_konman_hook(v) for v in value)
    return False


def _claude_matcher_group(event: str) -> dict:
    return {
        "hooks": [
            {
                "type": "command",
                "command": f"{HOOK_CMD} {event}",
            }
        ]
    }


def _merge_claude_style_hooks(existing_hooks, events: list) -> dict:
    """Merge into Claude/Codex nested hook maps: event -> [matcher groups]."""
    if existing_hooks is None:
        existing_hooks = {}
    if not isinstance(existing_hooks, dict):
        raise ValueError("Existing hooks configuration must be an object.")
    for event in events:
        groups = existing_hooks.get(event)
        if groups is None:
            groups = []
        elif not isinstance(groups, list):
            raise ValueError(f"Existing {event} hooks must be a list.")
        if not _contains_konman_hook(groups):
            extra = _claude_matcher_group(event)
            if event == "SessionEnd":
                extra["hooks"][0]["timeout"] = 3
            groups.append(extra)
        existing_hooks[event] = groups
    return existing_hooks


def inject_antigravity_hooks(target_dir: str) -> list:
    """Register konman directly inside the environment settings matching Antigravity schemas."""
    notes = []
    home = Path.home()
    ag_configs = [
        home / ".gemini/antigravity/mcp_config.json",
        home / ".gemini/config/mcp_config.json"
    ]

    mcp_injection = {
        "command": "konman",
        "args": ["mcp", "--dir", str(Path(target_dir).resolve())],
        "env": {"PYTHONUNBUFFERED": "1"}
    }

    for path in ag_configs:
        if path.parent.exists():
            config_data = _load_json(path, {})
            servers = config_data.setdefault("mcpServers", {})
            if not isinstance(servers, dict):
                raise ValueError(f"mcpServers in {path} must be an object.")
            servers["konman"] = mcp_injection
            _dump_json(path, config_data)
            notes.append(f"Registered MCP pointer at {path}")

    hooks_dir = Path(target_dir) / ".agents"
    hooks_dir.mkdir(exist_ok=True)
    hooks_file = hooks_dir / "hooks.json"

    hooks_payload = _load_json(hooks_file, {})
    hooks = hooks_payload.setdefault("hooks", [])
    if not isinstance(hooks, list):
        raise ValueError(f"hooks in {hooks_file} must be a list.")
    for event in ("UserPromptSubmit", "SessionEnd"):
        already_installed = any(
            item.get("event") == event
            and (
                _contains_konman_hook(item)
                or (item.get("command") == "konman" and "hook" in item.get("args", []))
            )
            for item in hooks
            if isinstance(item, dict)
        )
        if not already_installed:
            hooks.append({"event": event, "command": "konman", "args": ["hook", "--event", event], "fail_mode": "open"})
    _dump_json(hooks_file, hooks_payload)
    notes.append(f"Wrote Antigravity capture hooks at {hooks_file}")
    return notes


def inject_claude_code_adapters(target_dir: str) -> list:
    """Write CLAUDE.md plus project hooks that dump labeled turns into .context/.raw/."""
    notes = []
    base = Path(target_dir)
    claude_md = base / "CLAUDE.md"
    if not claude_md.exists():
        with open(claude_md, "w", encoding="utf-8") as f:
            f.write(
                "# CLAUDE.md Configuration Instructions\n\n"
                "System instructions and constraints for this repository are centralized.\n"
                "Please read the structural system rules from **AGENTS.md** before processing builds.\n"
            )
        notes.append(f"Created {claude_md}")

    settings_path = base / ".claude" / "settings.json"
    settings = _load_json(settings_path, {})
    if not isinstance(settings, dict):
        settings = {}
    settings["hooks"] = _merge_claude_style_hooks(
        settings.get("hooks"),
        ["UserPromptSubmit", "Stop", "SessionEnd"],
    )
    _dump_json(settings_path, settings)
    notes.append(f"Merged capture hooks into {settings_path}")
    notes.append("Claude Code will pipe UserPromptSubmit/Stop/SessionEnd JSON to `konman hook`.")
    return notes


def inject_codex_adapters(target_dir: str) -> list:
    """Write .codex/hooks.json using Codex's Claude-compatible nested hook schema."""
    notes = []
    base = Path(target_dir)
    hooks_path = base / ".codex" / "hooks.json"
    payload = _load_json(hooks_path, {})
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("description", "konman conversation capture hooks")
    payload["hooks"] = _merge_claude_style_hooks(
        payload.get("hooks"),
        ["UserPromptSubmit", "Stop", "SessionEnd"],
    )
    _dump_json(hooks_path, payload)
    notes.append(f"Merged capture hooks into {hooks_path}")
    notes.append("Codex will not run these until you trust them: open the CLI and run `/hooks`.")
    notes.append("Session rollouts (backfill) live under ~/.codex/sessions/YYYY/MM/DD/.")
    return notes


def inject_vsc_copilot_adapters(target_dir: str) -> list:
    """Write Copilot instructions plus agent-mode hooks under .github/hooks/."""
    notes = []
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
        notes.append(f"Created {copilot_md}")

    hooks_path = github_dir / "hooks" / "konman.json"
    payload = _load_json(hooks_path, {})
    hooks = payload.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"hooks in {hooks_path} must be an object.")
    for event in ("UserPromptSubmit", "Stop"):
        entries = hooks.get(event, [])
        if not isinstance(entries, list):
            raise ValueError(f"{event} hooks in {hooks_path} must be a list.")
        if not _contains_konman_hook(entries):
            entries.append({"type": "command", "command": f"{HOOK_CMD} {event}"})
        hooks[event] = entries
    payload.setdefault("version", 1)
    _dump_json(hooks_path, payload)
    notes.append(f"Wrote agent capture hooks at {hooks_path}")
    notes.append("These fire for Copilot agent sessions and Copilot CLI (preview in VS Code).")
    notes.append("Inline completions and classic Copilot Chat do not run hooks; try `konman backfill --source copilot` where logs are available.")
    return notes


def inject_cursor_adapters(target_dir: str) -> list:
    """Write Cursor rules plus .cursor/hooks.json capture on beforeSubmitPrompt."""
    notes = []
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
                "# Cursor Workspace Execution Directive\n\n"
                "This codebase relies on version-controlled semantic context metadata blocks.\n"
                "Before processing code modifications, you MUST verify active requirements, tradeoffs, and protected path criteria inside **AGENTS.md**.\n"
            )
        notes.append(f"Created {conman_mdc}")

    hooks_path = base / ".cursor" / "hooks.json"
    payload = _load_json(hooks_path, {})
    if not isinstance(payload, dict):
        raise ValueError(f"Configuration {hooks_path} must contain an object.")
    payload["version"] = payload.get("version", 1)
    hooks = payload.get("hooks")
    if hooks is None:
        hooks = {}
    elif not isinstance(hooks, dict):
        raise ValueError(f"hooks in {hooks_path} must be an object.")

    cursor_events = {
        "beforeSubmitPrompt": f"{HOOK_CMD} beforeSubmitPrompt",
        "sessionEnd": f"{HOOK_CMD} sessionEnd",
        "stop": f"{HOOK_CMD} stop",
    }
    for event, command in cursor_events.items():
        entries = hooks.get(event)
        if entries is None:
            entries = []
        elif not isinstance(entries, list):
            raise ValueError(f"{event} hooks in {hooks_path} must be a list.")
        if not _contains_konman_hook(entries):
            entries.append({"command": command})
        hooks[event] = entries

    payload["hooks"] = hooks
    _dump_json(hooks_path, payload)
    notes.append(f"Merged capture hooks into {hooks_path}")
    notes.append("Cursor Agent chat fires beforeSubmitPrompt with the human prompt on stdin.")
    return notes


def inject_kiro_adapters(target_dir: str) -> list:
    """Write Kiro steering plus standalone .kiro/hooks/konman.json (IDE 1.x / CLI V3)."""
    notes = []
    base = Path(target_dir)
    kiro_steering_dir = base / ".kiro" / "steering"
    kiro_steering_dir.mkdir(parents=True, exist_ok=True)

    kiro_md = kiro_steering_dir / "context_steering.md"
    if not kiro_md.exists():
        with open(kiro_md, "w", encoding="utf-8") as f:
            f.write(
                "# Kiro System Steering Context Map\n\n"
                "This file routes background project intent to the Kiro model loop engine.\n"
                "Please cross-reference constraints with the master mapping index generated at **AGENTS.md**.\n"
            )
        notes.append(f"Created {kiro_md}")

    hooks_path = base / ".kiro" / "hooks" / "konman.json"
    payload = _load_json(hooks_path, {})
    hooks = payload.setdefault("hooks", [])
    if not isinstance(hooks, list):
        raise ValueError(f"hooks in {hooks_path} must be a list.")
    for name, trigger in (("konman-capture-prompt", "UserPromptSubmit"), ("konman-capture-stop", "Stop")):
        if not any(item.get("name") == name for item in hooks if isinstance(item, dict)):
            hooks.append({
                "name": name,
                "trigger": trigger,
                "action": {"type": "command", "command": f"{HOOK_CMD} {trigger}"},
                "enabled": True,
            })
    payload.setdefault("version", "v1")
    _dump_json(hooks_path, payload)
    notes.append(f"Wrote Kiro capture hooks at {hooks_path}")
    notes.append("Requires Kiro IDE 1.x or CLI V3. Older `.kiro.hook` files are inert on 1.x.")
    notes.append("Capture hooks print nothing on stdout so Kiro does not inject log text into the agent.")
    return notes


def save_global_api_credentials(
    api_key: str,
    provider: str = "openai",
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o-mini",
    api_format: str = "openai-compatible",
) -> str:
    """Save provider metadata and keep secrets in the operating system credential store."""
    config_dir = Path.home() / ".config" / "konman"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"

    metadata = {}
    if config_file.exists():
        try:
            metadata = json.loads(config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Existing Konman config is not valid JSON: {error}") from error
    if not isinstance(metadata, dict):
        raise ValueError("Existing Konman config must contain a JSON object.")
    old_ref = metadata.get("credential_ref")
    credential_ref = provider.strip()
    if api_key:
        keyring = _get_credential_store()
        keyring.set_password("konman", credential_ref, api_key)

    payload = {
        "provider": provider,
        "api_format": api_format,
        "base_url": base_url.rstrip("/"),
        "model": model,
        "credential_ref": credential_ref if api_key or old_ref == credential_ref else None,
        "configured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    atomic_write_json(config_file, payload)
    if os.name != "nt":
        os.chmod(config_file, 0o600)
    if old_ref and old_ref != credential_ref:
        _delete_credential(old_ref)
    return str(config_file)


def _get_credential_store():
    try:
        import keyring
        backend = keyring.get_keyring()
        backend_module = backend.__class__.__module__.casefold()
        backend_name = backend.__class__.__name__.casefold()
        if getattr(backend, "priority", 0) <= 0 or any(name in backend_module or name in backend_name for name in ("plaintext", "keyrings.alt.file", "failkeyring")):
            raise RuntimeError("No secure operating-system credential backend is available.")
        return keyring
    except ImportError as error:
        raise RuntimeError("Secure credential storage is unavailable; install the keyring dependency or use KONMAN_API_KEY.") from error


def _delete_credential(credential_ref: str) -> None:
    if not credential_ref:
        return
    keyring = _get_credential_store()
    if keyring.get_password("konman", credential_ref) is not None:
        keyring.delete_password("konman", credential_ref)


def migrate_legacy_credentials() -> bool:
    config_file = Path.home() / ".config" / "konman" / "config.json"
    if not config_file.exists():
        return False
    try:
        payload = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Existing Konman config is not valid JSON: {error}") from error
    legacy_key = payload.get("api_key")
    if not legacy_key:
        return False
    credential_ref = str(payload.get("provider") or "openai")
    _get_credential_store().set_password("konman", credential_ref, legacy_key)
    payload.pop("api_key", None)
    payload["credential_ref"] = credential_ref
    atomic_write_json(config_file, payload)
    if os.name != "nt":
        os.chmod(config_file, 0o600)
    return True


def clear_global_api_credentials() -> bool:
    config_file = Path.home() / ".config" / "konman" / "config.json"
    if not config_file.exists():
        return False
    try:
        payload = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Existing Konman config is not valid JSON: {error}") from error
    _delete_credential(payload.get("credential_ref"))
    config_file.unlink()
    return True


def load_global_api_credentials() -> dict:
    """Loads globally mapped authentication parameters from the home configuration directory."""
    config_file = Path.home() / ".config" / "konman" / "config.json"
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
            payload["api_key"] = None
            credential_ref = payload.get("credential_ref")
            if credential_ref:
                try:
                    payload["api_key"] = _get_credential_store().get_password("konman", credential_ref)
                except RuntimeError as error:
                    payload["credential_error"] = str(error)
            if payload.get("api_key") is None and payload.get("credential_ref"):
                payload["credential_error"] = payload.get("credential_error", "Credential not found in the operating-system credential store.")
            if "api_key" in json.loads(config_file.read_text(encoding="utf-8")):
                payload["legacy_plaintext_credential"] = True
            return payload
        except Exception as error:
            return {"config_error": f"Cannot load Konman config: {error}"}
    return {}
