from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any, Union

class Requirement(BaseModel):
    id: str
    statement: str
    kind: Literal["hard", "preference"]
    priority: Optional[str] = "medium"
    source: Dict[str, str] = Field(default_factory=lambda: {"who": "human", "when": ""})
    why: Optional[str] = None
    derives_from: Optional[str] = None
    status: Literal["active", "superseded", "disproven"] = "active"
    added: Optional[Literal["standard", "retroactive"]] = "standard"

class Property(BaseModel):
    key: str
    value: Any
    evidence: Literal["measured", "documented", "claimed"]

class Evaluation(BaseModel):
    req: str
    result: Literal["pass", "fail", "partial"]
    via: str

class ConsideredObject(BaseModel):
    object: str
    properties: List[Property] = Field(default_factory=list)
    evaluations: List[Evaluation] = Field(default_factory=list)
    verdict: Literal["selected", "rejected", "proposed"]

class Decision(BaseModel):
    id: str
    chosen: str
    mode: Literal["compared", "default", "forced", "taste"] = "compared"
    decided: Dict[str, str] = Field(default_factory=lambda: {"who": "unknown", "when": ""})
    considered: List[ConsideredObject] = Field(default_factory=list)
    tradeoff: Optional[str] = None
    reason: Optional[str] = None
    status: Literal["active", "needs_review", "superseded"] = "active"

class BoundaryRule(BaseModel):
    path: str
    constrains: List[str] = Field(default_factory=list)
    rule: str = "no_edit_without_approval"
    why: str
