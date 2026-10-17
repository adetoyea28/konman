from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import List, Optional, Literal, Dict, Any, Union

RELATED_NODE_TYPES = {
    node_type: frozenset({"requirement", "decision", "change", "question", "risk", "object"})
    for node_type in ("requirement", "decision", "change", "question", "risk", "object")
}
RELATED_NODE_TYPES["evidence"] = frozenset({
    "requirement", "decision", "boundary", "change", "question", "risk", "object",
})
BOUNDARY_RELATIONSHIP_FIELDS = {
    "constrains": "requirement",
    "risks": "risk",
    "questions": "question",
}
BOUNDARY_TARGET_TYPES = frozenset(BOUNDARY_RELATIONSHIP_FIELDS.values())

class Requirement(BaseModel):
    id: str
    statement: str
    kind: Literal["hard", "preference"]
    priority: Optional[str] = "medium"
    source: Dict[str, Union[str, date, datetime]] = Field(default_factory=lambda: {"who": "human", "when": ""})
    why: Optional[str] = None
    derives_from: Optional[str] = None
    status: Literal["active", "proposed", "rejected", "superseded", "disproven"] = "active"
    added: Optional[Literal["standard", "retroactive"]] = "standard"
    evidence_ids: List[str] = Field(default_factory=list)
    related_nodes: List[str] = Field(default_factory=list)

class Property(BaseModel):
    key: str
    value: Any
    evidence: Literal["measured", "documented", "claimed"]

class Evaluation(BaseModel):
    req: str
    result: Literal["pass", "fail", "partial"]
    via: str
    object_id: Optional[str] = None

class ConsideredObject(BaseModel):
    object: str
    object_id: Optional[str] = None
    properties: List[Property] = Field(default_factory=list)
    evaluations: List[Evaluation] = Field(default_factory=list)
    verdict: Literal["selected", "rejected", "proposed"]

class Decision(BaseModel):
    id: str
    chosen: str
    mode: Literal["compared", "default", "forced", "taste"] = "compared"
    decided: Dict[str, Union[str, date, datetime]] = Field(default_factory=lambda: {"who": "unknown", "when": ""})
    considered: List[ConsideredObject] = Field(default_factory=list)
    tradeoff: Optional[str] = None
    reason: Optional[str] = None
    status: Literal["active", "proposed", "rejected", "needs_review", "superseded"] = "active"
    evidence_ids: List[str] = Field(default_factory=list)
    related_nodes: List[str] = Field(default_factory=list)

class BoundaryRule(BaseModel):
    id: Optional[str] = None
    path: str
    constrains: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    questions: List[str] = Field(default_factory=list)
    rule: str = "no_edit_without_approval"
    why: Optional[str] = None
    status: Literal["active", "proposed", "rejected"] = "active"
    evidence: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)

class Evidence(BaseModel):
    id: str
    source_type: Literal["human", "transcript", "commit", "document", "issue", "test", "other"]
    locator: Optional[str] = None
    excerpt: Optional[str] = None
    captured_by: Optional[str] = None
    captured_at: Optional[Union[str, date, datetime]] = None
    related_nodes: List[str] = Field(default_factory=list)
    status: Literal["active", "proposed", "rejected"] = "active"

class Change(BaseModel):
    id: str
    summary: str
    commit: Optional[str] = None
    author: Optional[str] = None
    changed_at: Optional[Union[str, date, datetime]] = None
    files: List[str] = Field(default_factory=list)
    implements: List[str] = Field(default_factory=list)
    affects: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    verification: Optional[str] = None
    status: Literal["proposed", "active", "rejected"] = "proposed"
    related_nodes: List[str] = Field(default_factory=list)

class Question(BaseModel):
    id: str
    question: str
    status: Literal["proposed", "open", "answered", "deferred", "rejected"] = "open"
    answer: Optional[str] = None
    owner: Optional[str] = None
    requirements: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    objects: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    resolution: Optional[str] = None
    related_nodes: List[str] = Field(default_factory=list)

class Risk(BaseModel):
    id: str
    statement: str
    likelihood: Optional[Literal["low", "medium", "high"]] = None
    impact: Optional[Literal["low", "medium", "high"]] = None
    mitigation: Optional[str] = None
    status: Literal["proposed", "open", "mitigated", "accepted", "closed", "rejected"] = "open"
    requirements: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    changes: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    resolution: Optional[str] = None
    related_nodes: List[str] = Field(default_factory=list)

class ContextObject(BaseModel):
    id: str
    name: str
    kind: Optional[str] = None
    description: Optional[str] = None
    properties: List[Property] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    status: Literal["proposed", "active", "retired", "rejected"] = "active"
    related_nodes: List[str] = Field(default_factory=list)
