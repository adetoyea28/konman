import json
import os
import subprocess
import tempfile
from io import StringIO
from pathlib import Path


IGNORE_START = "# >>> konman managed ignores"
IGNORE_END = "# <<< konman managed ignores"


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, content.encode(encoding))


def atomic_write_json(path: Path, payload) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def atomic_write_yaml(path: Path, payload, yaml) -> None:
    serialized = StringIO()
    yaml.dump(payload, serialized)
    atomic_write_text(path, serialized.getvalue())


def create_new_bytes(path: Path, content: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def ensure_raw_ignored(project_dir: Path) -> bool:
    path = Path(project_dir) / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if IGNORE_START in existing and IGNORE_END in existing:
        start = existing.index(IGNORE_START)
        end = existing.index(IGNORE_END, start) + len(IGNORE_END)
        block = f"{IGNORE_START}\n.context/.raw/\n{IGNORE_END}"
        updated = existing[:start] + block + existing[end:]
    elif ".context/.raw/" in existing.splitlines():
        return False
    else:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        block = f"{IGNORE_START}\n.context/.raw/\n{IGNORE_END}\n"
        updated = existing + separator + block
    if updated != existing:
        atomic_write_text(path, updated)
        return True
    return False


def is_raw_ignored(project_dir: Path) -> bool:
    project_dir = Path(project_dir)
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", ".context/.raw/konman-probe"],
            cwd=project_dir,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return True
    except OSError:
        pass
    ignore_file = project_dir / ".gitignore"
    ignore_lines = ignore_file.read_text(encoding="utf-8").splitlines() if ignore_file.exists() else []
    return ".context/.raw/" in ignore_lines or ".context/.raw" in ignore_lines