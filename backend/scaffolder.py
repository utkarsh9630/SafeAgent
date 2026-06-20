"""Sonnet 4.6 meta-agent scaffolder — builds LangGraph blueprint with cost prediction.

Supports multi-turn edits: pass existing_blueprint + modification_request
to update the graph without full restart (Hour 14–16).
"""
from __future__ import annotations
from claude_client import SONNET, call_structured
from models import (
    AgentDefinition, CostPrediction, GraphBlueprint,
    GraphEdge, ScaffoldRequest, ScaffoldResponse,
)

SYSTEM = """You are an expert AI agent scaffolder for a LangGraph-based multi-agent system.

Given a use case description, topology choice, and classification, produce a complete
agent graph blueprint:
- List sub-agents with name, role, model tier (haiku for simple tasks, sonnet for reasoning),
  tools, and a concise system_prompt.
- List graph edges (from_node → to_node) with optional condition labels.
- Declare the entry_node.
- Produce a cost/latency prediction labeled clearly as an estimate.

Model assignment rules:
- Orchestrator/supervisor → claude-sonnet-4-6
- Scoring, reasoning, generation → claude-sonnet-4-6
- Parsing, routing, email sending, simple extraction → claude-haiku-4-5-20251001

For multi-turn edits: if an existing blueprint is provided alongside a modification_request,
update only the parts the builder asked to change. Preserve everything else."""

AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "role": {"type": "string"},
        "model": {"type": "string", "enum": ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"]},
        "tools": {"type": "array", "items": {"type": "string"}},
        "system_prompt": {"type": "string"},
    },
    "required": ["name", "role", "model", "tools", "system_prompt"],
}

SCHEMA = {
    "type": "object",
    "properties": {
        "topology_name": {"type": "string"},
        "agents": {"type": "array", "items": AGENT_SCHEMA},
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from_node": {"type": "string"},
                    "to_node": {"type": "string"},
                    "condition": {"type": "string"},
                },
                "required": ["from_node", "to_node"],
            },
        },
        "entry_node": {"type": "string"},
        "prediction": {
            "type": "object",
            "properties": {
                "cost_usd": {"type": "number"},
                "latency_sec": {"type": "number"},
                "tokens_in": {"type": "integer"},
                "tokens_out": {"type": "integer"},
                "bottleneck_agent": {"type": "string"},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["cost_usd", "latency_sec", "tokens_in", "tokens_out",
                         "bottleneck_agent", "confidence"],
        },
    },
    "required": ["topology_name", "agents", "edges", "entry_node", "prediction"],
}


def scaffold(req: ScaffoldRequest) -> ScaffoldResponse:
    user_parts = [
        f"Description: {req.description}",
        f"Chosen topology: {req.chosen_topology.name} (Option {req.chosen_topology.id})",
        f"Domain: {req.classification.domain}",
        f"Complexity: {req.classification.complexity}",
        f"Risk: {req.classification.risk_profile}",
        f"Has external API: {req.classification.has_external_api}",
    ]

    if req.existing_blueprint and req.modification_request:
        user_parts.append(
            "\n\nEXISTING BLUEPRINT (update this based on the modification request):\n"
            + req.existing_blueprint.model_dump_json(indent=2)
        )
        user_parts.append(f"\nMODIFICATION REQUEST: {req.modification_request}")

    raw = call_structured(
        model=SONNET,
        system=SYSTEM,
        messages=[{"role": "user", "content": "\n".join(user_parts)}],
        tool_schema=SCHEMA,
        tool_name="scaffold_agent_graph",
        cache_system=True,
    )

    agents = [AgentDefinition(**a) for a in raw["agents"]]
    edges = [GraphEdge(**e) for e in raw["edges"]]
    prediction = CostPrediction(**raw["prediction"])

    blueprint = GraphBlueprint(
        topology=req.chosen_topology.id,
        topology_name=raw["topology_name"],
        agents=agents,
        edges=edges,
        entry_node=raw["entry_node"],
        prediction=prediction,
    )

    return ScaffoldResponse(blueprint=blueprint, session_id=req.session_id)
