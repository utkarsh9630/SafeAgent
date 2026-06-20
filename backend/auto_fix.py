"""Sonnet 4.6 auto-fix generator — produces safer tool params after a gate block."""
from claude_client import SONNET, call_structured
from models import AutoFixRequest, AutoFixResponse

SYSTEM = """You are a safety-fix generator for an AI agent system.
When an agent action is flagged as misaligned, produce a safer alternative
that preserves the builder's original intent while removing the problematic element.

Rules:
- Produce a revised version of tool_params that addresses the specific issue flagged.
- Do NOT fabricate capabilities not implied by the original params.
- Explain the fix in plain English (1-2 sentences).
- Provide a brief impact_preview (what changes for end-users).
- Classify the fix_type (e.g. rubric_rebalance, prompt_rephrase, scope_reduction)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "fixed_tool_params": {
            "type": "object",
            "description": "Revised tool parameters that address the safety flag",
        },
        "explanation": {
            "type": "string",
            "description": "Plain-English explanation of what was changed and why",
        },
        "impact_preview": {
            "type": "string",
            "description": "Brief note on practical impact",
        },
        "fix_type": {
            "type": "string",
            "description": "Short label: rubric_rebalance | prompt_rephrase | scope_reduction | other",
        },
    },
    "required": ["fixed_tool_params", "explanation", "impact_preview", "fix_type"],
}


def generate_fix(req: AutoFixRequest) -> AutoFixResponse:
    gate = req.gate_response
    user_msg = (
        f"Builder's original intent: {req.builder_intent}\n\n"
        f"Agent: {req.agent_name}\n"
        f"Tool called: {req.tool_name}\n"
        f"Original parameters:\n{req.original_tool_params}\n\n"
        f"Safety flag explanation: {gate.explanation}\n"
        f"Misalignment score: {gate.misalignment_score}/100\n"
        f"Oversight score: {gate.oversight_score}/100\n\n"
        "Produce a safer alternative to the original tool parameters."
    )

    raw = call_structured(
        model=SONNET,
        system=SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
        tool_schema=SCHEMA,
        tool_name="generate_fix",
        cache_system=True,
    )

    return AutoFixResponse(
        fixed_tool_params=raw["fixed_tool_params"],
        explanation=raw["explanation"],
        impact_preview=raw["impact_preview"],
        fix_type=raw["fix_type"],
    )
