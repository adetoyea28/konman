import hashlib
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path


SOURCES = ("claude-code", "codex", "cursor", "copilot", "kiro", "antigravity")


@dataclass(frozen=True)
class TranscriptEvent:
    source: str
    session_id: str
    role: str
    timestamp: str
    text: str
    event_id: str

    def as_dict(self):
        return asdict(self)


def _text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(text for item in value if (text := _text_content(item)))
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("parts"), list):
            return _text_content(value["parts"])
        return _text_content(value.get("content", ""))
    return ""


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def parse_record(source: str, value, record_index: int = 0) -> list[TranscriptEvent]:
    if source not in SOURCES:
        raise ValueError(f"Unsupported transcript source: {source}")
    events = []
    session_id = ""
    timestamp = ""
    objects = list(_walk(value))
    for item in objects:
        session_id = session_id or str(item.get("session_id") or item.get("sessionId") or item.get("conversationId") or "")
        timestamp = timestamp or str(item.get("timestamp") or item.get("created_at") or item.get("time") or "")

    for item in objects:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        hook_name = str(item.get("hook_event_name") or item.get("event") or item.get("trigger") or "").casefold()
        role = str(message.get("role") or payload.get("role") or item.get("role") or item.get("speaker") or "").casefold()
        text = (
            _text_content(message.get("content"))
            or _text_content(payload.get("content"))
            or _text_content(payload.get("text"))
            or _text_content(payload.get("parts"))
        )

        event_type = str(item.get("type") or payload.get("type") or "").casefold()
        if source == "codex" and event_type == "user_message":
            role = "user"
            text = text or _text_content(payload.get("message"))
        elif source == "codex" and event_type == "assistant_message":
            role = "assistant"
            text = text or _text_content(payload.get("message"))
        elif source == "claude-code" and event_type in {"user", "assistant"}:
            role = role or event_type
            text = text or _text_content(item.get("message"))
        elif hook_name in {"userpromptsubmit", "beforesubmitprompt"}:
            role = "user"
            text = text or _text_content(item.get("prompt") or item.get("user_prompt"))
        elif source == "copilot" and not text:
            log_line = item.get("line") or item.get("content")
            if isinstance(log_line, str):
                match = re.search(r"(?i)(?:user prompt|prompt)\s*:\s*(.+)", log_line)
                if match:
                    role, text = "user", match.group(1)

        if role not in {"user", "human", "assistant", "agent"} or not text.strip():
            continue
        role = "user" if role == "human" else "assistant" if role == "agent" else role
        fingerprint = "\0".join((source, session_id, timestamp, role, text, str(record_index)))
        event_id = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
        event = TranscriptEvent(source, session_id, role, timestamp, text, event_id)
        if not any(existing.event_id == event_id for existing in events):
            events.append(event)
    return events


def discover_paths(source: str, home: Path = None, appdata: Path = None) -> list[Path]:
    home = Path(home or Path.home())
    appdata = Path(appdata or os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    patterns = {
        "claude-code": [str(Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")) / "projects" / "**" / "*.jsonl")],
        "codex": [str(home / ".codex" / "sessions" / "**" / "*.jsonl")],
        "cursor": [str(home / ".cursor" / "projects" / "**" / "agent-transcripts" / "**" / "*.jsonl"), str(home / ".cursor" / "projects" / "**" / "agent-transcripts" / "**" / "*.json")],
        "copilot": [str(appdata / app / path) for app in ("Code", "Code - Insiders", "VSCodium") for path in ("logs/**/GitHub.copilot-chat/**/*.log", "User/workspaceStorage/**/chatSessions/**/*.json", "User/workspaceStorage/**/chatSessions/**/*.jsonl")],
        "kiro": [str(home / ".kiro" / "sessions" / "**" / "messages.jsonl")],
        "antigravity": [str(home / ".gemini" / "antigravity" / "**" / "transcript.jsonl")],
    }
    if source not in patterns:
        raise ValueError(f"Unsupported transcript source: {source}")
    import glob
    paths = {Path(item) for pattern in patterns[source] for item in glob.glob(pattern, recursive=True) if Path(item).is_file()}
    return sorted(paths)
