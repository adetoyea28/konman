import os
import glob
import re
from pathlib import Path
from ruamel.yaml import YAML
from konman.storage import atomic_write_text, atomic_write_yaml, ensure_raw_ignored, is_raw_ignored
from konman.models import (
    BoundaryRule, Change, ContextObject, Decision, Evidence, Question, Requirement, Risk,
)
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
            "requirements", "decisions", "objects", "evidence", "changes", "risks",
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
        object_nodes = self._load_node_collection("objects", ContextObject, "O")
        evidence_nodes = self._load_node_collection("evidence", Evidence, "E")
        change_nodes = self._load_node_collection("changes", Change, "C")
        question_nodes = self._load_node_collection("questions", Question, "Q")
        risk_nodes = self._load_node_collection("risks", Risk, "X")
        records = {
            "requirements": nodes["requirements"],
            "decisions": nodes["decisions"],
            "objects": object_nodes,
            "evidence": evidence_nodes,
            "changes": change_nodes,
            "questions": question_nodes,
            "risks": risk_nodes,
            "boundaries": {},
        }
        for kind, collection in (
            ("objects", object_nodes),
            ("evidence", evidence_nodes),
            ("changes", change_nodes),
            ("questions", question_nodes),
            ("risks", risk_nodes),
        ):
            prefix, model = {
                "objects": ("O", ContextObject),
                "evidence": ("E", Evidence),
                "changes": ("C", Change),
                "questions": ("Q", Question),
                "risks": ("X", Risk),
            }[kind]
            folder = self.ctx_dir / kind
            if not folder.is_dir():
                continue
            seen_ids = set()
            for path in sorted(folder.glob("*.yaml")):
                try:
                    item = self.yaml.load(path.read_text(encoding="utf-8"))
                    node_id = item.get("id") if isinstance(item, dict) else None
                    if not re.fullmatch(rf"{prefix}-\d+", str(node_id or "")):
                        violations.append(f"{path.relative_to(self.base_dir)} ID must use the form {prefix}-001.")
                    if path.stem != node_id:
                        violations.append(f"{path.relative_to(self.base_dir)} filename does not match id '{node_id}'.")
                    model.model_validate(item)
                    if node_id in seen_ids:
                        violations.append(f"Duplicate {kind[:-1]} ID '{node_id}'.")
                    seen_ids.add(node_id)
                    if isinstance(item, dict) and item.get("status") == "proposed" and strict:
                        violations.append(f"{kind[:-1].title()} '{node_id}' is awaiting review.")
                except Exception as error:
                    violations.append(f"Invalid {path.relative_to(self.base_dir)}: {error}")

        if boundaries_path.exists():
            try:
                boundary_values = self.yaml.load(boundaries_path.read_text(encoding="utf-8")) or []
                boundary_values = [boundary_values] if isinstance(boundary_values, dict) else boundary_values
                if not isinstance(boundary_values, list):
                    violations.append("boundaries.yaml must contain a list or mapping.")
                else:
                    boundary_ids = set()
                    for index, boundary in enumerate(boundary_values):
                        if not isinstance(boundary, dict):
                            violations.append(f"Invalid boundary entry {index + 1}: expected a mapping.")
                            continue
                        try:
                            BoundaryRule.model_validate(boundary)
                            boundary_id = boundary.get("id")
                            if boundary_id:
                                if not re.fullmatch(r"B-\d+", boundary_id):
                                    violations.append(f"Boundary entry {index + 1} ID must use the form B-001.")
                                if boundary_id in boundary_ids:
                                    violations.append(f"Duplicate boundary ID '{boundary_id}'.")
                                boundary_ids.add(boundary_id)
                                records["boundaries"][boundary_id] = boundary
                            if boundary.get("status") == "proposed" and strict:
                                violations.append(f"Boundary '{boundary_id or boundary.get('path')}' is awaiting review.")
                            self._validate_references(
                                violations, f"Boundary '{boundary_id or boundary.get('path')}'",
                                {
                                    "requirements": boundary.get("constrains", []),
                                    "evidence": boundary.get("evidence_ids", []),
                                },
                                records,
                            )
                        except Exception as error:
                            violations.append(f"Invalid boundary entry {index + 1}: {error}")
            except Exception as error:
                violations.append(f"Invalid boundaries.yaml: {error}")
        for kind, collection in records.items():
            for node_id, node in collection.items():
                evidence_ids = node.get("evidence_ids", []) if isinstance(node, dict) else []
                if evidence_ids:
                    self._validate_references(
                        violations, f"{kind[:-1].title()} '{node_id}'",
                        {"evidence": evidence_ids}, records,
                    )
        for node_id, decision in nodes["decisions"].items():
            for considered in decision.get("considered", []) or []:
                if not isinstance(considered, dict):
                    continue
                if considered.get("object_id") and considered["object_id"] not in object_nodes:
                    violations.append(f"Decision '{node_id}' references missing object '{considered['object_id']}'.")
                for evaluation in considered.get("evaluations", []) or []:
                    if isinstance(evaluation, dict) and evaluation.get("object_id") and evaluation["object_id"] not in object_nodes:
                        violations.append(f"Decision '{node_id}' evaluation references missing object '{evaluation['object_id']}'.")
            self._validate_references(
                violations, f"Decision '{node_id}'",
                {"evidence": decision.get("evidence_ids", [])}, records,
            )
        for requirement_id, requirement in nodes["requirements"].items():
            derived_from = requirement.get("derives_from")
            if derived_from and derived_from not in nodes["requirements"]:
                violations.append(f"Requirement '{requirement_id}' references missing source requirement '{derived_from}'.")
        for kind, collection in (
            ("objects", object_nodes),
            ("evidence", evidence_nodes),
            ("changes", change_nodes),
            ("questions", question_nodes),
            ("risks", risk_nodes),
        ):
            for node_id, node in collection.items():
                self._validate_references(violations, f"{kind[:-1].title()} '{node_id}'", node, records)
        return violations

    def _load_node_collection(self, kind: str, model, prefix: str) -> dict:
        folder = self.ctx_dir / kind
        records = {}
        if not folder.is_dir():
            return records
        for path in sorted(folder.glob("*.yaml")):
            try:
                node = self.yaml.load(path.read_text(encoding="utf-8"))
                if isinstance(node, dict) and isinstance(node.get("id"), str):
                    records[node["id"]] = node
            except Exception:
                continue
        return records

    @staticmethod
    def _validate_references(violations, owner, node, collections):
        references = {
            "requirements": node.get("requirements", []),
            "decisions": node.get("decisions", []),
            "objects": node.get("objects", []),
            "changes": node.get("changes", []),
            "evidence": node.get("evidence", []),
            "related_nodes": node.get("related_nodes", []),
        }
        for collection_name, ids in references.items():
            if collection_name == "related_nodes":
                if not isinstance(ids, list):
                    violations.append(f"{owner} has malformed related_nodes references.")
                    continue
                prefixes = {
                    "R": "requirements", "D": "decisions", "B": "boundaries",
                    "E": "evidence", "C": "changes", "Q": "questions",
                    "X": "risks", "O": "objects",
                }
                for reference in ids:
                    collection = prefixes.get(reference[:1]) if isinstance(reference, str) else None
                    if collection is None or reference not in collections.get(collection, {}):
                        violations.append(f"{owner} references missing related node '{reference}'.")
                continue
            if not isinstance(ids, list):
                violations.append(f"{owner} has malformed {collection_name} references.")
                continue
            for reference in ids:
                if reference not in collections.get(collection_name, {}):
                    singular = {
                        "requirements": "requirement", "decisions": "decision",
                        "objects": "object", "changes": "change", "evidence": "evidence",
                    }[collection_name]
                    violations.append(f"{owner} references missing {singular} '{reference}'.")
        for reference in node.get("implements", []) if isinstance(node.get("implements", []), list) else []:
            if reference not in collections.get("decisions", {}):
                violations.append(f"{owner} references missing decision '{reference}'.")
        for reference in node.get("affects", []) if isinstance(node.get("affects", []), list) else []:
            if reference not in collections.get("requirements", {}):
                violations.append(f"{owner} references missing requirement '{reference}'.")

    def mine_git_history(self, count: int = 10) -> int:
        """Capture commit messages and propose Change/Evidence nodes for reasoning clues."""
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
        change_dir = self.ctx_dir / "changes"
        evidence_dir = self.ctx_dir / "evidence"
        change_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir.mkdir(parents=True, exist_ok=True)

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
                existing_change = None
                for path in change_dir.glob("C-*.yaml"):
                    try:
                        existing = self.yaml.load(path.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if isinstance(existing, dict) and existing.get("commit") == commit_hash:
                        existing_change = existing
                        break
                if existing_change is None:
                    existing_evidence = None
                    for path in evidence_dir.glob("E-*.yaml"):
                        try:
                            existing = self.yaml.load(path.read_text(encoding="utf-8"))
                        except Exception:
                            continue
                        if isinstance(existing, dict) and existing.get("locator") == commit_hash:
                            existing_evidence = existing
                            break
                    if existing_evidence is None:
                        evidence_ids = [
                            int(match.group(1))
                            for path in evidence_dir.glob("E-*.yaml")
                            if (match := re.fullmatch(r"E-(\d+)", path.stem))
                        ]
                        evidence_id = f"E-{max(evidence_ids, default=0) + 1:03d}"
                        evidence = Evidence(
                            id=evidence_id,
                            source_type="commit",
                            locator=commit_hash,
                            excerpt=message.strip(),
                            captured_by=author,
                            captured_at=date_str,
                            status="proposed",
                        ).model_dump(mode="json", exclude_none=True)
                        atomic_write_yaml(evidence_dir / f"{evidence_id}.yaml", evidence, self.yaml)
                    else:
                        evidence_id = existing_evidence["id"]

                    change_ids = [
                        int(match.group(1))
                        for path in change_dir.glob("C-*.yaml")
                        if (match := re.fullmatch(r"C-(\d+)", path.stem))
                    ]
                    change_id = f"C-{max(change_ids, default=0) + 1:03d}"
                    change = Change(
                        id=change_id,
                        summary=message.strip().splitlines()[0][:240] or f"Commit {commit_hash[:8]}",
                        commit=commit_hash,
                        author=author,
                        changed_at=date_str,
                        evidence=[evidence_id],
                        status="proposed",
                    ).model_dump(mode="json", exclude_none=True)
                    atomic_write_yaml(change_dir / f"{change_id}.yaml", change, self.yaml)

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
        node_types=("requirement", "decision", "boundary", "evidence", "change", "question", "risk", "object"),
    ) -> str:
        """Extract candidate context nodes through a supported provider API format."""
        import urllib.request
        import json

        schemas = {
            "requirement": '"requirements": [{ "statement": "...", "kind": "hard|preference", "why": "...", "evidence": "exact quote" }]',
            "decision": '"decisions": [{ "chosen": "...", "mode": "compared|default|forced|taste", "reason": "...", "evidence": "exact quote" }]',
            "boundary": '"boundaries": [{ "path": "...", "rule": "...", "why": "...", "evidence": "exact quote" }]',
            "evidence": '"evidence": [{ "source_type": "transcript", "locator": "...", "excerpt": "exact quote" }]',
            "change": '"changes": [{ "summary": "...", "files": [], "implements": [], "affects": [], "verification": "...", "evidence": "exact quote" }]',
            "question": '"questions": [{ "question": "...", "owner": "...", "evidence": "exact quote" }]',
            "risk": '"risks": [{ "statement": "...", "likelihood": "low|medium|high", "impact": "low|medium|high", "mitigation": "...", "evidence": "exact quote" }]',
            "object": '"objects": [{ "name": "...", "kind": "...", "description": "...", "evidence": "exact quote" }]',
        }
        if not node_types or any(node_type not in schemas for node_type in node_types):
            raise ValueError("node_types must contain supported context node types.")
        output_schema = ",\n".join(schemas[node_type] for node_type in node_types)
        system_prompt = (
            "You are the extraction engine for konman (Context Manager).\n"
            "Your job is to read raw development logs/transcripts and distill architectural context.\n"
            "Only create requirements explicitly stated by a human. Do not infer intent or alternatives.\n"
            "Only create requested node types. A boundary requires an explicit human instruction to protect a specific path; do not invent protected paths or constraints.\n"
            "Only extract facts supported by explicit human text. Changes must describe an explicitly stated code change, not assume that code was modified. Risks and questions must be explicit, not speculative.\n"
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

        for kind, title, status_values, default_status, label_field, detail_field in (
            ("objects", "Tracked Objects", {"active"}, "active", "name", "description"),
            ("evidence", "Evidence Sources", {"active"}, "active", "source_type", "locator"),
            ("changes", "Recent Changes", {"active"}, "proposed", "summary", "commit"),
            ("questions", "Open Questions", {"open", "deferred"}, "open", "question", "owner"),
            ("risks", "Risk Register", {"open", "mitigated", "accepted"}, "open", "statement", "mitigation"),
        ):
            folder = self.ctx_dir / kind
            if not folder.is_dir():
                continue
            values = []
            for path in sorted(folder.glob("*.yaml")):
                item = self.yaml.load(path.read_text(encoding="utf-8"))
                if item and item.get("status", default_status) in status_values:
                    status = item.get("status", default_status)
                    detail = f" — {item[detail_field]}" if item.get(detail_field) else ""
                    values.append(f"- **{item.get('id')}** [{str(status).upper()}]: {item.get(label_field)}{detail}")
            if values:
                summary.extend(["", f"### {title}", *values[:10]])

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
