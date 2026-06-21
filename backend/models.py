"""Shared data models — interfaces agreed with Evan (gate) and Utkarsh (UI)."""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel


# ── Classifier ────────────────────────────────────────────────────────────────

class ClassifyRequest(BaseModel):
    description: str

class ClassifyResponse(BaseModel):
    domain: str
    complexity: Literal["low", "medium", "high"]
    risk_profile: str
    agent_count_estimate: int
    tool_count_estimate: int
    has_external_api: bool


# ── Topology ──────────────────────────────────────────────────────────────────

class TopologyOption(BaseModel):
    id: Literal["A", "B"]
    name: str
    description: str
    tradeoffs_pro: list[str]
    tradeoffs_con: list[str]
    estimated_cost_usd_low: float
    estimated_cost_usd_high: float
    estimated_latency_sec: float
    recommended: bool
    reasoning_chain: str  # Extended Thinking output — shown in UI

class TopologyRequest(BaseModel):
    description: str
    classification: ClassifyResponse

class TopologyResponse(BaseModel):
    option_a: TopologyOption
    option_b: TopologyOption
    thinking_summary: str  # condensed reasoning for UI badge


# ── Scaffolder ────────────────────────────────────────────────────────────────

class AgentDefinition(BaseModel):
    name: str
    role: str
    model: Literal["claude-haiku-4-5-20251001", "claude-sonnet-4-6"]
    tools: list[str]
    system_prompt: str

class CostPrediction(BaseModel):
    cost_usd: float
    latency_sec: float
    tokens_in: int
    tokens_out: int
    bottleneck_agent: str
    confidence: Literal["low", "medium", "high"]

class GraphEdge(BaseModel):
    from_node: str
    to_node: str
    condition: Optional[str] = None

class GraphBlueprint(BaseModel):
    topology: Literal["A", "B"]
    topology_name: str
    agents: list[AgentDefinition]
    edges: list[GraphEdge]
    entry_node: str
    prediction: CostPrediction

class ScaffoldRequest(BaseModel):
    description: str
    classification: ClassifyResponse
    chosen_topology: TopologyOption
    session_id: str
    # Multi-turn edits (Hour 14–16)
    existing_blueprint: Optional[GraphBlueprint] = None
    modification_request: Optional[str] = None

class ScaffoldResponse(BaseModel):
    blueprint: GraphBlueprint
    session_id: str


# ── Safety Gate interface (agreed with Evan) ──────────────────────────────────

class GateRequest(BaseModel):
    session_id: str
    agent_name: str
    tool_name: str
    tool_params: dict
    builder_intent: str
    agent_role: str

class GateResponse(BaseModel):
    decision: Literal["BLOCK", "ALLOW", "WARN"]
    tier_triggered: Literal[1, 2, 3]
    misalignment_score: Optional[int] = None
    oversight_score: Optional[int] = None
    explanation: str
    fix_draft: Optional[str] = None
    cache_hit: bool
    latency_ms: int
    tokens_in: int = 0    # real tokens from T3 Claude call
    tokens_out: int = 0   # real tokens from T3 Claude call


# ── Auto-Fix ──────────────────────────────────────────────────────────────────

class AutoFixRequest(BaseModel):
    session_id: str
    agent_name: str
    tool_name: str
    original_tool_params: dict
    builder_intent: str
    gate_response: GateResponse

class AutoFixResponse(BaseModel):
    fixed_tool_params: dict
    explanation: str
    impact_preview: str
    fix_type: str


# ── Human Override (Evan's audit log — lighter than HITLDecision) ────────────

class HumanOverride(BaseModel):
    session_id:      str
    agent_name:      str
    tool_name:       str
    decision:        Literal["approve_fix", "modify", "override"]
    modified_params: Optional[dict] = None


# ── Pub/Sub Event (Evan → frontend SSE) ──────────────────────────────────────

class PubSubEvent(BaseModel):
    event_type: str
    agent_name: str
    status:     str
    timestamp:  float
    score:      Optional[int] = None


# ── Human Decision (HITL) ─────────────────────────────────────────────────────

class HITLDecision(BaseModel):
    session_id: str
    run_id: str
    action_id: str
    decision: Literal["approve_fix", "modify", "override"]
    modified_params: Optional[dict] = None


# ── Graph Run ─────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    session_id: str
    blueprint: GraphBlueprint
    builder_intent: str
    input_data: dict = {}

class RunEvent(BaseModel):
    event_type: str
    agent_name: Optional[str] = None
    tool_name: Optional[str] = None
    data: dict = {}
    timestamp_ms: int


# ── Blueprint Export ──────────────────────────────────────────────────────────

class BlueprintExport(BaseModel):
    session_id: str
    blueprint: GraphBlueprint
    run_events: list[RunEvent]
    prediction: CostPrediction
    measured_cost_usd: Optional[float] = None
    measured_latency_sec: Optional[float] = None
    measured_tokens_total: Optional[int] = None
