"""Context graph loading and safe YAML record updates for the local GUI."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import StringIO
from pathlib import Path
import re

from ruamel.yaml import YAML

from konman.engine import ContextEngine
from konman.models import (
    BOUNDARY_RELATIONSHIP_FIELDS,
    BoundaryRule,
    Change,
    ContextObject,
    Decision,
    Evidence,
    Question,
    RELATED_NODE_TYPES,
    Requirement,
    Risk,
)
from konman.storage import atomic_write_yaml, create_new_bytes


CONTEXT_NODE_CONFIG = {
    "requirement": ("R", "requirements", Requirement, "statement"),
    "decision": ("D", "decisions", Decision, "chosen"),
    "boundary": ("B", "boundaries", BoundaryRule, "path"),
    "evidence": ("E", "evidence", Evidence, "excerpt"),
    "change": ("C", "changes", Change, "summary"),
    "question": ("Q", "questions", Question, "question"),
    "risk": ("X", "risks", Risk, "statement"),
    "object": ("O", "objects", ContextObject, "name"),
}

TYPE_TITLES = {
    "requirement": "Requirements",
    "decision": "Decisions",
    "boundary": "Boundaries",
    "evidence": "Sources",
    "change": "Changes",
    "question": "Questions",
    "risk": "Risks",
    "object": "Components",
}

TEMPLATES = {
    "requirement": {"statement": "Describe the constraint", "kind": "hard", "status": "active", "evidence_ids": []},
    "decision": {"chosen": "Chosen option", "mode": "default", "considered": [], "status": "active", "evidence_ids": []},
    "boundary": {"path": "src/path", "rule": "no_edit_without_approval", "constrains": [], "risks": [], "questions": [], "status": "active", "evidence_ids": []},
    "evidence": {"source_type": "human", "excerpt": "Supporting source", "related_nodes": [], "status": "active"},
    "change": {"summary": "Describe the change", "files": [], "implements": [], "affects": [], "evidence": [], "status": "proposed"},
    "question": {"question": "What remains unknown?", "requirements": [], "decisions": [], "objects": [], "evidence": [], "status": "open"},
    "risk": {"statement": "Describe the risk", "requirements": [], "decisions": [], "changes": [], "evidence": [], "status": "open"},
    "object": {"name": "Component name", "properties": [], "evidence": [], "status": "active"},
}

REFERENCE_FIELDS = {
    ("requirement", "evidence_ids"): ("evidence", "Source"),
    ("decision", "evidence_ids"): ("evidence", "Source"),
    ("boundary", "evidence_ids"): ("evidence", "Source"),
    ("evidence", "related_nodes"): ("any", "Context node"),
    ("change", "implements"): ("decision", "Decision"),
    ("change", "affects"): ("requirement", "Requirement"),
    ("change", "evidence"): ("evidence", "Source"),
    ("question", "requirements"): ("requirement", "Requirement"),
    ("question", "decisions"): ("decision", "Decision"),
    ("question", "objects"): ("object", "Component"),
    ("question", "evidence"): ("evidence", "Source"),
    ("risk", "requirements"): ("requirement", "Requirement"),
    ("risk", "decisions"): ("decision", "Decision"),
    ("risk", "changes"): ("change", "Change"),
    ("risk", "evidence"): ("evidence", "Source"),
    ("object", "evidence"): ("evidence", "Source"),
}

for _field, _target_type in BOUNDARY_RELATIONSHIP_FIELDS.items():
    REFERENCE_FIELDS[("boundary", _field)] = (_target_type, TYPE_TITLES[_target_type][:-1])
for _node_type in RELATED_NODE_TYPES:
    REFERENCE_FIELDS[(_node_type, "related_nodes")] = ("related", "Context node")


class ContextDataError(ValueError):
    """Invalid or unsafe context data update."""


class ConcurrentEditError(ContextDataError):
    """The backing file changed after the editor loaded it."""


@dataclass
class ContextSnapshot:
    records: dict[str, dict[str, dict]]
    tokens: dict[tuple[str, str], str]
    errors: list[str]


class ContextWorkspace:
    """Load, validate, and atomically update project context records."""

    def __init__(self, engine: ContextEngine):
        self.engine = engine
        self.yaml = YAML()
        self.yaml.preserve_quotes = True

    @staticmethod
    def _token(path: Path) -> str:
        if not path.exists():
            return ""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _boundary_values(self) -> list[dict]:
        path = self.engine.ctx_dir / "boundaries.yaml"
        if not path.exists():
            return []
        values = self.yaml.load(path.read_text(encoding="utf-8")) or []
        values = [values] if isinstance(values, dict) else values
        if not isinstance(values, list):
            raise ContextDataError("boundaries.yaml must contain a list or mapping.")
        if any(not isinstance(item, dict) for item in values):
            raise ContextDataError("Each boundaries.yaml entry must be a mapping.")
        return values

    def load(self) -> ContextSnapshot:
        records = {node_type: {} for node_type in CONTEXT_NODE_CONFIG}
        tokens: dict[tuple[str, str], str] = {}
        errors = []
        for node_type, (prefix, folder, model, label_field) in CONTEXT_NODE_CONFIG.items():
            if node_type == "boundary":
                path = self.engine.ctx_dir / "boundaries.yaml"
                if not path.exists():
                    continue
                try:
                    values = self._boundary_values()
                except Exception as error:
                    errors.append(f"Invalid .context/boundaries.yaml: {error}")
                    continue
                token = self._token(path)
                for index, record in enumerate(values):
                    node_id = record.get("id") or f"B-UNASSIGNED-{index + 1:04d}"
                    records[node_type][node_id] = record
                    tokens[(node_type, node_id)] = token
                    try:
                        model.model_validate(record)
                    except Exception as error:
                        errors.append(f"Boundary {node_id} failed validation: {error}")
                continue

            directory = self.engine.ctx_dir / folder
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.yaml")):
                try:
                    record = self.yaml.load(path.read_text(encoding="utf-8"))
                    if not isinstance(record, dict):
                        raise ContextDataError("record must be a YAML mapping")
                    node_id = record.get("id") or path.stem
                    if node_id in records[node_type]:
                        errors.append(f"Duplicate {TYPE_TITLES[node_type]} ID {node_id}.")
                        continue
                    records[node_type][node_id] = record
                    tokens[(node_type, node_id)] = self._token(path)
                    model.model_validate(record)
                except Exception as error:
                    errors.append(f"Invalid {path.relative_to(self.engine.base_dir)}: {error}")
        return ContextSnapshot(records=records, tokens=tokens, errors=errors)

    def allocate_id(self, node_type: str, snapshot: ContextSnapshot | None = None) -> str:
        if node_type not in CONTEXT_NODE_CONFIG:
            raise ContextDataError(f"Unknown node type: {node_type}")
        snapshot = snapshot or self.load()
        prefix = CONTEXT_NODE_CONFIG[node_type][0]
        numbers = [
            int(match.group(1))
            for node_id in snapshot.records[node_type]
            if (match := re.fullmatch(rf"{prefix}-(\d+)", node_id))
        ]
        return f"{prefix}-{max(numbers, default=0) + 1:03d}"

    def save(
        self,
        node_type: str,
        record: dict,
        *,
        node_id: str | None = None,
        expected_token: str | None = None,
    ) -> tuple[str, list[str]]:
        if node_type not in CONTEXT_NODE_CONFIG:
            raise ContextDataError(f"Unknown node type: {node_type}")
        if not isinstance(record, dict):
            raise ContextDataError("A context record must be a YAML mapping.")

        prefix, folder, model, _ = CONTEXT_NODE_CONFIG[node_type]
        snapshot = self.load()
        is_new = node_id is None
        original_node_id = node_id
        if is_new:
            node_id = self.allocate_id(node_type, snapshot)
            if "id" in record and record["id"] != node_id:
                raise ContextDataError(f"New records must use the next available ID {node_id}.")
            record = dict(record)
            record["id"] = node_id
        else:
            if node_id not in snapshot.records[node_type]:
                raise ContextDataError(f"No {node_type} record with ID {node_id} exists.")
            if expected_token is None:
                raise ContextDataError("An edit requires a saved-file token; reload the record and try again.")
            if snapshot.tokens.get((node_type, node_id)) != expected_token:
                raise ConcurrentEditError(f"{node_id} changed on disk. Reload it before saving.")
            if node_type == "boundary" and node_id.startswith("B-UNASSIGNED-"):
                if record.get("id") not in (None, node_id):
                    raise ContextDataError("A record ID cannot be changed while editing.")
                record = dict(record)
                record["id"] = self.allocate_id(node_type, snapshot)
                node_id = record["id"]
            elif record.get("id") != node_id:
                raise ContextDataError("A record ID cannot be changed while editing.")

        if not re.fullmatch(rf"{prefix}-\d+", str(node_id)):
            raise ContextDataError(f"ID must use the form {prefix}-001.")
        try:
            model.model_validate(record)
        except Exception as error:
            raise ContextDataError(f"{node_type.title()} failed schema validation: {error}") from error

        self._validate_references(node_type, record, snapshot, node_id, is_new)
        if node_type == "boundary":
            path = self.engine.ctx_dir / "boundaries.yaml"
            boundaries = self._boundary_values()
            if is_new:
                if any(item.get("id") == node_id or (item.get("id") is None and item.get("path") == record.get("path")) for item in boundaries):
                    raise ContextDataError(f"Boundary {node_id} or path {record.get('path')} already exists.")
                boundaries.append(record)
            else:
                selected_id = original_node_id
                if selected_id not in snapshot.records["boundary"]:
                    raise ContextDataError(f"No boundary with ID {selected_id} exists.")
                if selected_id.startswith("B-UNASSIGNED-"):
                    index = int(selected_id.rsplit("-", 1)[1]) - 1
                else:
                    index = next(i for i, item in enumerate(boundaries) if item.get("id") == selected_id)
                if any(i != index and item.get("path") == record.get("path") for i, item in enumerate(boundaries)):
                    raise ContextDataError(f"Boundary path {record.get('path')} already exists.")
                boundaries[index] = record
            atomic_write_yaml(path, boundaries, self.yaml)
            target_path = path
        else:
            target_path = self.engine.ctx_dir / folder / f"{node_id}.yaml"
            if is_new:
                serialized = StringIO()
                self.yaml.dump(record, serialized)
                try:
                    create_new_bytes(target_path, serialized.getvalue().encode("utf-8"))
                except FileExistsError as error:
                    raise ContextDataError(f"{node_id} was created by another editor. Refresh and try again.") from error
            else:
                atomic_write_yaml(target_path, record, self.yaml)

        notices = []
        try:
            self.engine.compile_agents_md()
        except Exception as error:
            notices.append(f"Record saved, but AGENTS.md could not be refreshed: {error}")
        return node_id, notices

    @staticmethod
    def _validate_references(
        node_type: str,
        record: dict,
        snapshot: ContextSnapshot,
        current_id: str,
        is_new: bool,
    ) -> None:
        collections = snapshot.records
        for (owner_type, field), (target_type, target_title) in REFERENCE_FIELDS.items():
            if owner_type != node_type:
                continue
            references = record.get(field, [])
            if not isinstance(references, list):
                raise ContextDataError(f"{field} must be a list of node IDs.")
            for reference in references:
                if not isinstance(reference, str):
                    raise ContextDataError(f"{field} entries must be node ID strings.")
                if target_type == "any":
                    exists = any(reference in nodes for nodes in collections.values())
                elif target_type == "related":
                    target_node_type = next(
                        (kind for kind, records in collections.items() if reference in records), None
                    )
                    exists = target_node_type in RELATED_NODE_TYPES.get(owner_type, frozenset())
                else:
                    exists = reference in collections[target_type]
                if reference == current_id and not is_new and target_type != "related":
                    exists = True
                if reference == current_id and target_type == "related":
                    raise ContextDataError("related_nodes cannot reference the current node.")
                if not exists:
                    raise ContextDataError(f"{field} references missing {target_title.lower()} '{reference}'.")
        if node_type == "requirement" and record.get("derives_from"):
            if record["derives_from"] not in collections["requirement"]:
                raise ContextDataError(
                    f"derives_from references missing requirement '{record['derives_from']}'."
                )
        if node_type == "decision":
            for considered in record.get("considered", []) or []:
                if not isinstance(considered, dict):
                    continue
                object_id = considered.get("object_id")
                if object_id and object_id not in collections["object"]:
                    raise ContextDataError(f"considered object_id references missing object '{object_id}'.")
                for evaluation in considered.get("evaluations", []) or []:
                    if not isinstance(evaluation, dict):
                        continue
                    requirement_id = evaluation.get("req")
                    if requirement_id and requirement_id not in collections["requirement"]:
                        raise ContextDataError(f"evaluation references missing requirement '{requirement_id}'.")
                    object_id = evaluation.get("object_id")
                    if object_id and object_id not in collections["object"]:
                        raise ContextDataError(f"evaluation references missing object '{object_id}'.")
                    requirement = collections["requirement"].get(requirement_id, {})
                    if (
                        requirement.get("status") in {"superseded", "disproven"}
                        and record.get("status") != "needs_review"
                    ):
                        raise ContextDataError(
                            f"decision evaluates stale requirement '{requirement_id}' and must remain needs_review."
                        )


def build_graph(snapshot: ContextSnapshot) -> tuple[list[dict], list[dict]]:
    """Build canvas-ready nodes and typed edges from explicit stored relationships."""
    nodes = []
    edges_by_key = {}
    id_to_type = {
        node_id: node_type
        for node_type, records in snapshot.records.items()
        for node_id in records
    }
    for node_type, records in snapshot.records.items():
        _, _, _, label_field = CONTEXT_NODE_CONFIG[node_type]
        for node_id, record in records.items():
            label = str(record.get(label_field) or node_id)
            status = str(record.get("status", "active"))
            nodes.append({
                "id": node_id,
                "type": node_type,
                "label": label,
                "status": status,
                "record": record,
            })

    def link(source, target, label):
        if target not in id_to_type or source not in id_to_type:
            return
        edge_id = f"{source}|{target}|{label}"
        edges_by_key[edge_id] = {
            "id": edge_id,
            "source": source,
            "target": target,
            "label": label,
        }

    def links_from(node_id, record, fields, label):
        for field in fields:
            for target in record.get(field, []) or []:
                link(node_id, target, label)

    for node_type, records in snapshot.records.items():
        for node_id, record in records.items():
            if node_type in {"requirement", "decision", "boundary"}:
                links_from(node_id, record, ("evidence_ids",), "supported by")
            if node_type == "requirement" and record.get("derives_from"):
                link(node_id, record["derives_from"], "derived from")
            elif node_type == "decision":
                for considered in record.get("considered", []) or []:
                    if not isinstance(considered, dict):
                        continue
                    if considered.get("object_id"):
                        link(node_id, considered["object_id"], "considers")
                    for evaluation in considered.get("evaluations", []) or []:
                        if isinstance(evaluation, dict):
                            link(node_id, evaluation.get("req"), f"evaluates: {evaluation.get('result', 'unknown')}")
                            if evaluation.get("object_id"):
                                link(node_id, evaluation["object_id"], "evaluates object")
            elif node_type == "boundary":
                for field in BOUNDARY_RELATIONSHIP_FIELDS:
                    links_from(node_id, record, (field,), "constrains")
            elif node_type == "evidence":
                for target in record.get("related_nodes", []) or []:
                    link(node_id, target, "evidence for")
            elif node_type == "change":
                links_from(node_id, record, ("implements",), "implements")
                links_from(node_id, record, ("affects",), "affects")
                links_from(node_id, record, ("evidence",), "verified by")
            elif node_type == "question":
                links_from(node_id, record, ("requirements",), "asks about")
                links_from(node_id, record, ("decisions",), "asks about")
                links_from(node_id, record, ("objects",), "asks about")
                links_from(node_id, record, ("evidence",), "raised by")
            elif node_type == "risk":
                links_from(node_id, record, ("requirements",), "threatens")
                links_from(node_id, record, ("decisions",), "threatens")
                links_from(node_id, record, ("changes",), "threatens")
                links_from(node_id, record, ("evidence",), "supported by")
            elif node_type == "object":
                links_from(node_id, record, ("evidence",), "described by")
            if node_type in RELATED_NODE_TYPES and node_type != "evidence":
                links_from(node_id, record, ("related_nodes",), "related to")

    return nodes, list(edges_by_key.values())
