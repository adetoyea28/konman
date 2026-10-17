import os
import glob
import re
from pathlib import Path
from ruamel.yaml import YAML
from konman.storage import atomic_write_text, atomic_write_yaml, ensure_raw_ignored, is_raw_ignored
from konman.models import (
    BOUNDARY_RELATIONSHIP_FIELDS, RELATED_NODE_TYPES, BoundaryRule, Change, ContextObject,
    Decision, Evidence, Question, Requirement, Risk,
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
            "risks": node.get("risks", []),
            "questions": node.get("questions", []),
        }
        type_by_prefix = {
            "R": "requirement", "D": "decision", "B": "boundary", "E": "evidence",
            "C": "change", "Q": "question", "X": "risk", "O": "object",
        }
        collection_by_type = {
            "requirements": "requirement", "decisions": "decision", "boundaries": "boundary",
            "evidence": "evidence", "changes": "change", "questions": "question",
            "risks": "risk", "objects": "object",
        }
        owner_id = node.get("id")
        owner_type = type_by_prefix.get(owner_id[:1]) if isinstance(owner_id, str) else None
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
                    target_type = collection_by_type[collection]
                    allowed = RELATED_NODE_TYPES.get(owner_type, frozenset())
                    if owner_type == "evidence":
                        allowed = frozenset(collection_by_type.values()) - {"evidence"}
                    if target_type not in allowed:
                        violations.append(f"{owner} cannot link to related node '{reference}'.")
                continue
            if not isinstance(ids, list):
                violations.append(f"{owner} has malformed {collection_name} references.")
                continue
            for reference in ids:
                if reference not in collections.get(collection_name, {}):
                    singular = {
                        "requirements": "requirement", "decisions": "decision",
                        "objects": "object", "changes": "change", "evidence": "evidence",
                        "risks": "risk", "questions": "question",
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
            "requirement": ("requirements", Requirement),
            "decision": ("decisions", Decision),
            "boundary": ("boundaries", BoundaryRule),
            "evidence": ("evidence", Evidence),
            "change": ("changes", Change),
            "question": ("questions", Question),
            "risk": ("risks", Risk),
            "object": ("objects", ContextObject),
        }
        if not node_types or any(node_type not in schemas for node_type in node_types):
            raise ValueError("node_types must contain supported context node types.")
        linkable_types = {
            "requirement": "requirements", "decision": "decisions", "change": "changes",
            "question": "questions", "risk": "risks", "object": "objects",
        }
        known_nodes = {node_type: [] for node_type in linkable_types}
        for node_type, folder in linkable_types.items():
            directory = self.ctx_dir / folder
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.yaml")):
                try:
                    record = self.yaml.load(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(record, dict) and isinstance(record.get("id"), str):
                    label_field = schemas[node_type][1].model_fields
                    label = next((record.get(field) for field in ("statement", "chosen", "summary", "question", "name") if field in label_field), "")
                    known_nodes[node_type].append({"id": record["id"], "label": str(label or "")[:160]})
        known_context_nodes = dict(known_nodes)
        for node_type, folder, label_field in (
            ("boundary", "boundaries", "path"), ("evidence", "evidence", "excerpt"),
        ):
            known_context_nodes[node_type] = []
            path = self.ctx_dir / f"{folder}.yaml" if node_type == "boundary" else self.ctx_dir / folder
            paths = [path] if node_type == "boundary" and path.is_file() else (
                sorted(path.glob("*.yaml")) if path.is_dir() else []
            )
            for record_path in paths:
                try:
                    values = self.yaml.load(record_path.read_text(encoding="utf-8")) or []
                except Exception:
                    continue
                values = [values] if isinstance(values, dict) else values
                if not isinstance(values, list):
                    continue
                known_context_nodes[node_type].extend(
                    {"id": item["id"], "label": str(item.get(label_field) or "")[:160]}
                    for item in values if isinstance(item, dict) and isinstance(item.get("id"), str)
                )
        ids_by_type = {
            node_type: [item["id"] for item in values]
            for node_type, values in known_context_nodes.items()
        }
        all_known_ids = [node_id for values in ids_by_type.values() for node_id in values]
        schema_link_targets = {
            "requirement": {
                "related_nodes": RELATED_NODE_TYPES["requirement"], "derives_from": {"requirement"},
                "evidence_ids": {"evidence"},
            },
            "decision": {"related_nodes": RELATED_NODE_TYPES["decision"], "evidence_ids": {"evidence"}},
            "boundary": {
                **{field: {target_type} for field, target_type in BOUNDARY_RELATIONSHIP_FIELDS.items()},
                "evidence_ids": {"evidence"},
            },
            "evidence": {"related_nodes": RELATED_NODE_TYPES["evidence"]},
            "change": {
                "implements": {"decision"}, "affects": {"requirement"}, "evidence": {"evidence"},
                "related_nodes": RELATED_NODE_TYPES["change"],
            },
            "question": {
                "requirements": {"requirement"}, "decisions": {"decision"}, "objects": {"object"},
                "evidence": {"evidence"},
                "related_nodes": RELATED_NODE_TYPES["question"],
            },
            "risk": {
                "requirements": {"requirement"}, "decisions": {"decision"}, "changes": {"change"},
                "evidence": {"evidence"},
                "related_nodes": RELATED_NODE_TYPES["risk"],
            },
            "object": {"evidence": {"evidence"}, "related_nodes": RELATED_NODE_TYPES["object"]},
        }
        output_properties = {}
        definitions = {}
        for node_type in node_types:
            output_key, model = schemas[node_type]
            node_schema = model.model_json_schema()
            definitions.update(node_schema.pop("$defs", {}))
            node_schema["properties"].pop("id", None)
            node_schema["properties"]["status"] = {
                "type": "string", "enum": ["proposed"], "default": "proposed",
            }
            node_schema["properties"]["evidence_quote"] = {
                "type": "string",
                "description": "A short verbatim quote from human-authored source text supporting this candidate.",
            }
            for field_name, target_types in schema_link_targets[node_type].items():
                field_schema = node_schema["properties"].get(field_name)
                if field_schema is None:
                    continue
                target_ids = [node_id for target_type in target_types for node_id in ids_by_type.get(target_type, [])]
                if field_name == "derives_from":
                    field_schema["enum"] = target_ids
                else:
                    field_schema["items"]["enum"] = target_ids
            node_schema["required"] = [
                field for field in node_schema.get("required", []) if field != "id"
            ]
            node_schema["required"] = list(dict.fromkeys(
                [*node_schema["required"], "status", "evidence_quote"]
            ))
            node_schema["additionalProperties"] = False
            output_properties[output_key] = {
                "type": "array", "items": node_schema,
            }

        for definition in definitions.values():
            for field_name in ("status", "verdict"):
                field_schema = definition.get("properties", {}).get(field_name)
                if field_schema is not None:
                    field_schema.update({"type": "string", "enum": ["proposed"], "default": "proposed"})
        if "ConsideredObject" in definitions:
            object_id_schema = definitions["ConsideredObject"].get("properties", {}).get("object_id")
            if object_id_schema is not None:
                object_id_schema["enum"] = ids_by_type["object"]
        if "Evaluation" in definitions:
            evaluation_properties = definitions["Evaluation"].get("properties", {})
            if "req" in evaluation_properties:
                evaluation_properties["req"]["enum"] = ids_by_type["requirement"]
            if "object_id" in evaluation_properties:
                evaluation_properties["object_id"]["enum"] = ids_by_type["object"]
        output_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": output_properties,
            "required": list(output_properties),
            "additionalProperties": False,
        }
        if definitions:
            output_schema["$defs"] = definitions
        system_prompt = (
            "You are the extraction engine for konman (Context Manager).\n"
            "Read human prompts, development logs, and transcripts to identify architectural context.\n"
            "Infer candidate requirements, decisions, objects, risks, questions, and boundaries when the human-authored evidence supports the inference. "
            "Use why, reason, description, mitigation, or question fields to make the inference and its uncertainty clear.\n"
            "Link ordinary nodes with related_nodes using only existing, allowed node IDs shown below. Requirements, decisions, changes, questions, risks, and objects may link to one another. Evidence related_nodes means 'evidence for' and may target any non-evidence node.\n"
            "Boundaries are human-set and authoritative: only a boundary may link to requirements, risks, and questions, using constrains, risks, and questions respectively. Ordinary nodes cannot link to boundaries.\n"
            "Boundaries are human-set and authoritative: only a boundary may link outward, using constrains for requirements, risks for risks, and questions for questions. Never create a link from another node to a boundary.\n"
            f"Existing context nodes available for linking: {json.dumps(known_context_nodes, ensure_ascii=False)}\n"
            "Never invent source facts, entities, decisions, or file paths. A boundary needs a concrete path supported by the source and a stated or clearly implied constraint.\n"
            "Changes must describe an explicitly stated change; do not assume code was modified. Only return node types requested in the schema.\n"
            "Every returned node is only a candidate for human review: set every status to proposed and every decision considered-item verdict to proposed. "
            "Never imply that a decision, requirement, risk, or boundary has been approved or is active.\n"
            "Include a short exact quote from human-authored text in evidence_quote for each node. Do not use assistant-authored text as evidence.\n"
            "Return raw JSON only, without markdown fences, matching this JSON Schema:\n"
            f"{json.dumps(output_schema, ensure_ascii=False, indent=2)}"
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
