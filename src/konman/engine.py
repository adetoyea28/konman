import os
import glob
import re
from pathlib import Path
from ruamel.yaml import YAML
from konman.storage import atomic_write_text, atomic_write_yaml, ensure_raw_ignored, is_raw_ignored
from konman.models import BoundaryRule, Decision, Requirement
from konman.redaction import redact_text

class ContextEngine:
    def __init__(self, target_dir: str = "."):
        self.base_dir = Path(target_dir).resolve()
        self.ctx_dir = self.base_dir / ".context"
        self.yaml = YAML()
        self.yaml.preserve_quotes = True

    def init_folders(self):
        """Scaffold the .context storage layout matrix folder database."""
        folders = [
            "requirements", "decisions", "objects", 
            "state/history", ".raw", "questions"
        ]
        for f in folders:
            (self.ctx_dir / f).mkdir(parents=True, exist_ok=True)
        ensure_raw_ignored(self.base_dir)
            
        manifest_path = self.ctx_dir / "manifest.yaml"
        if not manifest_path.exists():
            atomic_write_yaml(manifest_path, {
                "schema_version": "1.0.0",
                "tool_name": "konman"
            }, self.yaml)

    def process_staleness_propagation(self) -> int:
        """Finds any decision using a superseded requirement and flags it instantly."""
        req_dir = self.ctx_dir / "requirements"
        dec_dir = self.ctx_dir / "decisions"
        if not req_dir.exists() or not dec_dir.exists():
            return 0

        stale_reqs = set()
        for p in req_dir.glob("*.yaml"):
            with open(p, "r", encoding="utf-8") as f:
                data = self.yaml.load(f)
                if data and data.get("status") in ["superseded", "disproven"]:
                    stale_reqs.add(data.get("id"))

        updated_count = 0
        for p in dec_dir.glob("*.yaml"):
            with open(p, "r", encoding="utf-8") as f:
                dec_data = self.yaml.load(f)
            
            if not dec_data or dec_data.get("status") == "needs_review":
                continue

            needs_flag = False
            for item in dec_data.get("considered", []) or []:
                if not isinstance(item, dict):
                    continue
                for eval_item in item.get("evaluations", []) or []:
                    if not isinstance(eval_item, dict):
                        continue
                    if eval_item.get("req") in stale_reqs:
                        needs_flag = True
                        break
            
            if needs_flag:
                dec_data["status"] = "needs_review"
                atomic_write_yaml(p, dec_data, self.yaml)
                updated_count += 1
        return updated_count

    def check_graph_validity(self, strict: bool = False) -> list[str]:
        """Read-only validation of graph structure, schemas, references, and stale dependencies."""
        violations = []
        if not self.ctx_dir.is_dir():
            return ["No .context directory found; run `konman init` first."]
        for folder in ("requirements", "decisions", ".raw"):
            if not (self.ctx_dir / folder).is_dir():
                violations.append(f"Missing required .context/{folder}/ directory.")

        if not is_raw_ignored(self.base_dir):
            violations.append(".context/.raw is not ignored by the project .gitignore.")

        manifest = self.ctx_dir / "manifest.yaml"
        if manifest.exists():
            try:
                manifest_data = self.yaml.load(manifest.read_text(encoding="utf-8"))
                if not isinstance(manifest_data, dict):
                    violations.append("manifest.yaml must contain a YAML mapping.")
            except Exception as error:
                violations.append(f"Invalid manifest.yaml: {error}")
        else:
            violations.append("Missing .context/manifest.yaml.")

        nodes = {"requirements": {}, "decisions": {}}
        models = {"requirements": Requirement, "decisions": Decision}
        for kind in nodes:
            folder = self.ctx_dir / kind
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.yaml")):
                try:
                    node = self.yaml.load(path.read_text(encoding="utf-8"))
                    if not isinstance(node, dict):
                        violations.append(f"{path.relative_to(self.base_dir)} must contain a YAML mapping.")
                        continue
                    node_id = node.get("id")
                    if not isinstance(node_id, str) or not node_id.strip():
                        violations.append(f"{path.relative_to(self.base_dir)} has no valid id.")
                        continue
                    expected_prefix = "R" if kind == "requirements" else "D"
                    if not re.fullmatch(rf"{expected_prefix}-\d+", node_id):
                        violations.append(f"{path.relative_to(self.base_dir)} ID must use the form {expected_prefix}-001.")
                    if path.stem != node_id:
                        violations.append(f"{path.relative_to(self.base_dir)} filename does not match id '{node_id}'.")
                    if node_id in nodes[kind]:
                        violations.append(f"Duplicate {kind[:-1]} ID '{node_id}'.")
                    nodes[kind][node_id] = node
                    models[kind].model_validate(node)
                    if node.get("status") == "proposed" and strict:
                        violations.append(f"{kind[:-1].title()} '{node_id}' is awaiting review.")
                    if kind == "decisions" and node.get("status") == "needs_review":
                        violations.append(f"Decision '{node_id}' is flagged as needs_review.")
                except Exception as error:
                    violations.append(f"Invalid {path.relative_to(self.base_dir)}: {error}")

        requirements = nodes["requirements"]
        stale_ids = {node_id for node_id, node in requirements.items() if node.get("status") in {"superseded", "disproven"}}
        for decision_id, decision in nodes["decisions"].items():
            for item in decision.get("considered", []) or []:
                if not isinstance(item, dict):
                    violations.append(f"Decision '{decision_id}' contains a malformed considered object.")
                    continue
                for evaluation in item.get("evaluations", []) or []:
                    if not isinstance(evaluation, dict):
                        violations.append(f"Decision '{decision_id}' contains a malformed requirement evaluation.")
                        continue
                    requirement_id = evaluation.get("req")
                    if requirement_id not in requirements:
                        violations.append(f"Decision '{decision_id}' references missing requirement '{requirement_id}'.")
                    elif requirement_id in stale_ids and decision.get("status") != "needs_review":
                        violations.append(f"Decision '{decision_id}' depends on stale requirement '{requirement_id}' and needs review.")

        boundaries_path = self.ctx_dir / "boundaries.yaml"
        if boundaries_path.exists():
            try:
                boundaries = self.yaml.load(boundaries_path.read_text(encoding="utf-8")) or []
                if isinstance(boundaries, dict):
                    boundaries = [boundaries]
                if not isinstance(boundaries, list):
                    violations.append("boundaries.yaml must contain a list or mapping.")
                else:
                    boundary_ids = set()
                    for index, boundary in enumerate(boundaries):
                        if not isinstance(boundary, dict):
                            violations.append(f"Invalid boundary entry {index + 1}: expected a mapping.")
                            continue
                        try:
                            BoundaryRule.model_validate(boundary)
                            boundary_id = boundary.get("id")
                            if boundary_id and not re.fullmatch(r"B-\d+", boundary_id):
                                violations.append(f"Boundary entry {index + 1} ID must use the form B-001.")
                            if boundary_id and boundary_id in boundary_ids:
                                violations.append(f"Duplicate boundary ID '{boundary_id}'.")
                            if boundary_id:
                                boundary_ids.add(boundary_id)
                            if boundary.get("status") == "proposed" and strict:
                                violations.append(f"Boundary '{boundary_id or boundary.get('path')}' is awaiting review.")
                            for requirement_id in boundary.get("constrains", []):
                                if requirement_id not in nodes["requirements"]:
                                    violations.append(f"Boundary '{boundary_id or boundary.get('path')}' references missing requirement '{requirement_id}'.")
                        except Exception as error:
                            violations.append(f"Invalid boundary entry {index + 1}: {error}")
            except Exception as error:
                violations.append(f"Invalid boundaries.yaml: {error}")
        return violations

    def mine_git_history(self, count: int = 10) -> int:
        """Queries the local repository logs and saves structured reasoning JSON entries."""
        import subprocess
        import json
        from datetime import datetime

        raw_dir = self.ctx_dir / ".raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        ensure_raw_ignored(self.base_dir)

        if count <= 0:
            return 0

        try:
            result = subprocess.run(
                ["git", "log", "-n", str(count), "--date=short", "--format=%H%x1f%an%x1f%ad%x1f%B%x1e"],
                cwd=self.base_dir,
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
            )
            log_entries = result.stdout.split("\x1e")
        except (OSError, subprocess.CalledProcessError):
            return 0

        mined_count = 0
        keywords = ["because", "requires", "reverts", "fixes", "breaking change"]

        for entry in log_entries:
            entry = entry.strip()
            if not entry or "\x1f" not in entry:
                continue
            parts = entry.split("\x1f", 3)
            if len(parts) < 4:
                continue
            commit_hash, author, date_str, message = parts[0], parts[1], parts[2], parts[3]

            if any(kw in message.lower() for kw in keywords):
                message, redaction_count = redact_text(message)
                payload = {
                    "source": "git_history_miner",
                    "commit": commit_hash,
                    "author": author,
                    "date": date_str,
                    "extracted_text": message,
                    "redaction_count": redaction_count,
                    "timestamp_mined": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                output_file = raw_dir / f"git_mined_{commit_hash[:8]}.json"
                if not output_file.exists():
                    from konman.storage import atomic_write_json
                    atomic_write_json(output_file, payload)
                    mined_count += 1
        return mined_count

    def execute_llm_distillation(
        self,
        text_content: str,
        api_key: str = None,
        model_name: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        api_format: str = "openai-compatible",
        node_types=("requirement", "decision"),
    ) -> str:
        """Extract candidate context nodes through a supported provider API format."""
        import urllib.request
        import json

        schemas = {
            "requirement": '"requirements": [{ "statement": "...", "kind": "hard|preference", "why": "...", "evidence": "exact quote" }]',
            "decision": '"decisions": [{ "chosen": "...", "mode": "compared|default|forced|taste", "reason": "...", "evidence": "exact quote" }]',
            "boundary": '"boundaries": [{ "path": "...", "rule": "...", "why": "...", "evidence": "exact quote" }]',
        }
        if not node_types or any(node_type not in schemas for node_type in node_types):
            raise ValueError("node_types must contain supported context node types.")
        output_schema = ",\n".join(schemas[node_type] for node_type in node_types)
        system_prompt = (
            "You are the extraction engine for konman (Context Manager).\n"
            "Your job is to read raw development logs/transcripts and distill architectural context.\n"
            "Only create requirements explicitly stated by a human. Do not infer intent or alternatives.\n"
            "Only create requested node types. A boundary requires an explicit human instruction to protect a specific path; do not invent protected paths or constraints.\n"
            "Return proposed nodes, not approved facts. Include a short verbatim evidence quote for each node.\n"
            "Format output strictly as raw JSON text matching this syntax without markdown formatting backticks:\n"
            f"{{\n  {output_schema}\n}}"
        )

        try:
            root = base_url.rstrip("/")
            headers = {"Content-Type": "application/json"}
            if api_format == "openai-compatible":
                url = f"{root}/chat/completions"
                data = {
                    "model": model_name,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text_content},
                    ],
                }
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
            elif api_format == "anthropic":
                url = f"{root}/messages"
                headers.update({"anthropic-version": "2023-06-01"})
                if api_key:
                    headers["x-api-key"] = api_key
                data = {
                    "model": model_name,
                    "max_tokens": 4096,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": text_content}],
                }
            elif api_format == "gemini":
                url = f"{root}/models/{model_name}:generateContent"
                if api_key:
                    headers["x-goog-api-key"] = api_key
                data = {
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": "user", "parts": [{"text": text_content}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                }
            elif api_format == "ollama":
                url = f"{root}/api/chat"
                data = {
                    "model": model_name,
                    "stream": False,
                    "format": "json",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text_content},
                    ],
                }
            else:
                raise ValueError(f"Unsupported API format: {api_format}")

            req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as response:
                res_data = json.loads(response.read().decode("utf-8"))
            if api_format == "openai-compatible":
                content = res_data["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
                return content
            if api_format == "anthropic":
                return "".join(part.get("text", "") for part in res_data["content"] if part.get("type") == "text")
            if api_format == "gemini":
                return "".join(part.get("text", "") for part in res_data["candidates"][0]["content"]["parts"])
            return res_data["message"]["content"]
        except Exception as e:
            return json.dumps({"error": f"LLM pipeline error ({api_format}): {e}"})

    def compile_agents_md(self):
        """Refresh the Konman-managed AGENTS.md section without replacing user content."""
        agents_path = self.base_dir / "AGENTS.md"
        summary = ["## Konman Context", ""]
        req_dir = self.ctx_dir / "requirements"
        if req_dir.exists():
            for p in req_dir.glob("*.yaml"):
                with open(p, "r", encoding="utf-8") as f:
                    r = self.yaml.load(f)
                    if r and r.get("status") == "active":
                        summary.append(f"- **{r.get('id')}** [{str(r.get('kind', 'requirement')).upper()}]: {r.get('statement')}")
        if len(summary) == 2:
            summary.append("No active requirements recorded.")

        dec_dir = self.ctx_dir / "decisions"
        if dec_dir.exists():
            decisions = []
            for p in dec_dir.glob("*.yaml"):
                with open(p, "r", encoding="utf-8") as f:
                    decision = self.yaml.load(f)
                if decision and decision.get("status") in ("active", "needs_review"):
                    state = "needs review" if decision.get("status") == "needs_review" else "active"
                    decisions.append(f"- **{decision.get('id')}**: {decision.get('chosen')} ({state})")
            if decisions:
                summary.extend(["", "### Decisions", *decisions])

        boundaries_path = self.ctx_dir / "boundaries.yaml"
        if boundaries_path.exists():
            boundaries = self.yaml.load(boundaries_path.read_text(encoding="utf-8")) or []
            if isinstance(boundaries, dict):
                boundaries = [boundaries]
            boundaries = [
                item for item in boundaries
                if isinstance(item, dict) and item.get("status") not in ("proposed", "rejected")
            ]
            if boundaries:
                summary.extend(["", "### Protected Paths"])
                summary.extend(f"- **{item.get('path', 'unknown')}**: {item.get('why', item.get('rule', 'protected'))}" for item in boundaries)

        summary.extend(["", "Read `.context/` for source records and project details."])
        start_marker = "<!-- konman:context:start -->"
        end_marker = "<!-- konman:context:end -->"
        managed = f"{start_marker}\n" + "\n".join(summary) + f"\n{end_marker}"
        existing = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""

        if start_marker in existing and end_marker in existing:
            start = existing.index(start_marker)
            end = existing.index(end_marker, start) + len(end_marker)
            content = existing[:start] + managed + existing[end:]
        elif "This file is auto-generated by **`konman`**" in existing:
            content = "# Project Context\n\n" + managed + "\n"
        elif existing.strip():
            content = existing.rstrip() + "\n\n" + managed + "\n"
        else:
            content = "# Project Context\n\n" + managed + "\n"
        agents_path.write_text(content, encoding="utf-8")
