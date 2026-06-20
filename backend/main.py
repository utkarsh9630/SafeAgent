"""
SafeAgent FastAPI backend — Joseph's domain.

Routes:
  POST /classify            → Haiku pre-classifier
  POST /topology            → Sonnet + Extended Thinking topology options
  POST /scaffold            → Sonnet meta-agent scaffolder (multi-turn capable)
  POST /run/start           → Start a LangGraph run
  GET  /run/{run_id}/stream → SSE event stream for the run
  POST /run/decide          → Submit HITL decision
  POST /fix                 → Generate auto-fix (standalone)
  GET  /export/{session_id} → Download safe-agent-blueprint.json
  GET  /health
"""
from __future__ import annotations
import asyncio
import json
import uuid
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from auto_fix import generate_fix
from blueprint_export import build_export
from classifier import classify
from graph_runner import GraphRunner
from models import (
    AutoFixRequest,
    ClassifyRequest,
    HITLDecision,
    GraphBlueprint,
    RunEvent,
    RunRequest,
    ScaffoldRequest,
    TopologyRequest,
)
from scaffolder import scaffold
from topology import propose_topologies

load_dotenv()

app = FastAPI(title="SafeAgent Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session state
_runners: dict[str, GraphRunner] = {}
_session_events: dict[str, list[RunEvent]] = {}
_session_blueprints: dict[str, dict] = {}


# ── Classify ──────────────────────────────────────────────────────────────────

@app.post("/classify")
def classify_endpoint(req: ClassifyRequest):
    return classify(req).model_dump()


# ── Topology ──────────────────────────────────────────────────────────────────

@app.post("/topology")
def topology_endpoint(req: TopologyRequest):
    return propose_topologies(req).model_dump()


# ── Scaffold ──────────────────────────────────────────────────────────────────

@app.post("/scaffold")
def scaffold_endpoint(req: ScaffoldRequest):
    result = scaffold(req)
    _session_blueprints[req.session_id] = result.blueprint.model_dump()
    return result.model_dump()


# ── Auto-Fix (standalone) ─────────────────────────────────────────────────────

@app.post("/fix")
def fix_endpoint(req: AutoFixRequest):
    return generate_fix(req).model_dump()


# ── Run ───────────────────────────────────────────────────────────────────────

@app.post("/run/start")
async def run_start(req: RunRequest):
    run_id = str(uuid.uuid4())
    runner = GraphRunner(
        blueprint=req.blueprint,
        builder_intent=req.builder_intent,
        session_id=req.session_id,
        run_id=run_id,
    )
    _runners[run_id] = runner
    _session_events.setdefault(req.session_id, [])

    async def _run():
        try:
            await runner.run(req.input_data)
        except Exception as exc:
            import time
            runner.event_queue.put_nowait(RunEvent(
                event_type="run.error",
                data={"error": str(exc)},
                timestamp_ms=int(time.time() * 1000),
            ))

    asyncio.create_task(_run())
    return {"run_id": run_id, "stream_url": f"/run/{run_id}/stream"}


@app.get("/run/{run_id}/stream")
async def run_stream(run_id: str):
    runner = _runners.get(run_id)
    if not runner:
        raise HTTPException(404, "run_id not found")

    async def event_generator() -> AsyncGenerator[dict, None]:
        while True:
            try:
                event: RunEvent = await asyncio.wait_for(
                    runner.event_queue.get(), timeout=30.0
                )
                _session_events.setdefault(runner.session_id, []).append(event)
                yield {"data": event.model_dump_json(), "event": event.event_type}
                if event.event_type in ("run.completed", "run.error"):
                    break
            except asyncio.TimeoutError:
                yield {"data": json.dumps({"type": "heartbeat"}), "event": "heartbeat"}

    return EventSourceResponse(event_generator())


@app.post("/run/decide")
async def run_decide(decision: HITLDecision):
    runner = _runners.get(decision.run_id)
    if not runner:
        raise HTTPException(404, "run_id not found")
    await runner.hitl_queue.put(decision)
    return {"ok": True}


# ── Export ────────────────────────────────────────────────────────────────────

@app.get("/export/{session_id}")
def export_session(
    session_id: str,
    measured_cost_usd: float | None = None,
    measured_latency_sec: float | None = None,
    measured_tokens_total: int | None = None,
):
    blueprint_dict = _session_blueprints.get(session_id)
    if not blueprint_dict:
        raise HTTPException(404, "Session not found or not yet scaffolded")

    blueprint = GraphBlueprint(**blueprint_dict)
    events = _session_events.get(session_id, [])

    data = build_export(
        session_id=session_id,
        blueprint=blueprint,
        events=events,
        measured_cost_usd=measured_cost_usd,
        measured_latency_sec=measured_latency_sec,
        measured_tokens_total=measured_tokens_total,
    )

    return StreamingResponse(
        iter([json.dumps(data, indent=2)]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=safe-agent-blueprint.json"},
    )


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
