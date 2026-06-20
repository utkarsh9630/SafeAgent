"""Blueprint JSON export — safe-agent-blueprint.json (Hour 18-20)."""
from models import BlueprintExport, GraphBlueprint, CostPrediction, RunEvent


def build_export(
    session_id: str,
    blueprint: GraphBlueprint,
    events: list[RunEvent],
    measured_cost_usd: float | None = None,
    measured_latency_sec: float | None = None,
    measured_tokens_total: int | None = None,
) -> dict:
    export = BlueprintExport(
        session_id=session_id,
        blueprint=blueprint,
        run_events=events,
        prediction=blueprint.prediction,
        measured_cost_usd=measured_cost_usd,
        measured_latency_sec=measured_latency_sec,
        measured_tokens_total=measured_tokens_total,
    )
    return export.model_dump()
