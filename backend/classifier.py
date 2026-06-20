"""Haiku 4.5 pre-classifier — fast domain + complexity triage."""
from claude_client import HAIKU, call_structured
from models import ClassifyRequest, ClassifyResponse

SYSTEM = """You are a fast use-case classifier for an AI agent builder.
Analyze a builder's plain-English description and classify the use case.
Be concise and accurate. Risk profile should mention the key risk vectors."""

SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {
            "type": "string",
            "description": "Short domain label, e.g. 'HR / Recruiting', 'Customer Support', 'Research'"
        },
        "complexity": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "Agent graph complexity"
        },
        "risk_profile": {
            "type": "string",
            "description": "1-sentence risk summary, e.g. 'High — scoring bias + outbound email'"
        },
        "agent_count_estimate": {
            "type": "integer",
            "description": "Estimated number of sub-agents needed"
        },
        "tool_count_estimate": {
            "type": "integer",
            "description": "Estimated number of distinct tools"
        },
        "has_external_api": {
            "type": "boolean",
            "description": "True if the workflow calls external APIs (email, CRM, etc.)"
        },
    },
    "required": ["domain", "complexity", "risk_profile", "agent_count_estimate",
                 "tool_count_estimate", "has_external_api"],
}


def classify(req: ClassifyRequest) -> ClassifyResponse:
    raw = call_structured(
        model=HAIKU,
        system=SYSTEM,
        messages=[{"role": "user", "content": req.description}],
        tool_schema=SCHEMA,
        tool_name="classify_use_case",
    )
    return ClassifyResponse(
        domain=raw["domain"],
        complexity=raw["complexity"],
        risk_profile=raw["risk_profile"],
        agent_count_estimate=raw["agent_count_estimate"],
        tool_count_estimate=raw["tool_count_estimate"],
        has_external_api=raw["has_external_api"],
    )
