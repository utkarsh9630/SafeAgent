"""Sonnet 4.6 + Extended Thinking — topology reasoning with visible chain."""
from claude_client import SONNET, call_structured
from models import TopologyOption, TopologyRequest, TopologyResponse

SYSTEM = """You are an AI agent architect. Given a use case classification, propose exactly
two contrasting multi-agent topology options for a LangGraph workflow.

Option A must be a Supervisor–Worker pattern (orchestrator delegates to specialist sub-agents).
Option B must be a single ReAct (reasoning + acting) loop agent.

For each option provide honest tradeoffs, cost estimates (labeled PREDICTION), and latency estimates.
Mark the better option for the stated use case as recommended=true.

Use your extended thinking to reason through the tradeoffs before producing the final answer.
Expose that reasoning in reasoning_chain — the UI will show it to the builder."""

SCHEMA = {
    "type": "object",
    "properties": {
        "option_a": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "enum": ["A"]},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "tradeoffs_pro": {"type": "array", "items": {"type": "string"}},
                "tradeoffs_con": {"type": "array", "items": {"type": "string"}},
                "estimated_cost_usd_low": {"type": "number"},
                "estimated_cost_usd_high": {"type": "number"},
                "estimated_latency_sec": {"type": "number"},
                "recommended": {"type": "boolean"},
                "reasoning_chain": {"type": "string"},
            },
            "required": ["id", "name", "description", "tradeoffs_pro", "tradeoffs_con",
                         "estimated_cost_usd_low", "estimated_cost_usd_high",
                         "estimated_latency_sec", "recommended", "reasoning_chain"],
        },
        "option_b": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "enum": ["B"]},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "tradeoffs_pro": {"type": "array", "items": {"type": "string"}},
                "tradeoffs_con": {"type": "array", "items": {"type": "string"}},
                "estimated_cost_usd_low": {"type": "number"},
                "estimated_cost_usd_high": {"type": "number"},
                "estimated_latency_sec": {"type": "number"},
                "recommended": {"type": "boolean"},
                "reasoning_chain": {"type": "string"},
            },
            "required": ["id", "name", "description", "tradeoffs_pro", "tradeoffs_con",
                         "estimated_cost_usd_low", "estimated_cost_usd_high",
                         "estimated_latency_sec", "recommended", "reasoning_chain"],
        },
        "thinking_summary": {
            "type": "string",
            "description": "1-2 sentence summary of the key reasoning shown in UI",
        },
    },
    "required": ["option_a", "option_b", "thinking_summary"],
}


def propose_topologies(req: TopologyRequest) -> TopologyResponse:
    user_msg = (
        f"Use case description: {req.description}\n\n"
        f"Classification: domain={req.classification.domain}, "
        f"complexity={req.classification.complexity}, "
        f"risk={req.classification.risk_profile}, "
        f"agents≈{req.classification.agent_count_estimate}, "
        f"tools≈{req.classification.tool_count_estimate}, "
        f"external_api={req.classification.has_external_api}"
    )

    raw = call_structured(
        model=SONNET,
        system=SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
        tool_schema=SCHEMA,
        tool_name="propose_topologies",
        cache_system=True,
        thinking=True,
        thinking_budget=10000,
    )

    def build_option(d: dict) -> TopologyOption:
        return TopologyOption(
            id=d["id"],
            name=d["name"],
            description=d["description"],
            tradeoffs_pro=d["tradeoffs_pro"],
            tradeoffs_con=d["tradeoffs_con"],
            estimated_cost_usd_low=d["estimated_cost_usd_low"],
            estimated_cost_usd_high=d["estimated_cost_usd_high"],
            estimated_latency_sec=d["estimated_latency_sec"],
            recommended=d["recommended"],
            reasoning_chain=(
                raw.get("__thinking__", "") + "\n\n" + d["reasoning_chain"]
            ).strip(),
        )

    return TopologyResponse(
        option_a=build_option(raw["option_a"]),
        option_b=build_option(raw["option_b"]),
        thinking_summary=raw["thinking_summary"],
    )
