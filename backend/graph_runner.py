"""
LangGraph runtime — builds and runs the agent graph from a scaffold blueprint.

Key integration points:
  - before_tool_call: calls Evan's safety gate (POST /gate/check)
  - Events emitted to asyncio.Queue for SSE streaming (Utkarsh subscribes)
  - After WARN/BLOCK: calls auto-fix generator, then waits for HITL decision
"""
from __future__ import annotations
import asyncio
import os
import time
import uuid
import httpx
from typing import Callable, Optional

from langgraph.graph import StateGraph, END

from models import (
    AutoFixRequest, GateRequest, GateResponse,
    GraphBlueprint, HITLDecision, RunEvent,
)
from auto_fix import generate_fix
from demo_tools import (
    BIASED_RUBRIC, SAMPLE_RESUMES,
    apply_scoring_rubric, parse_resume, send_email,
)

GATE_URL = os.getenv("SAFETY_GATE_URL", "http://localhost:8001/gate/check")

TOOL_FNS: dict[str, Callable] = {
    "parse_resume": parse_resume,
    "apply_scoring_rubric": apply_scoring_rubric,
    "send_email": send_email,
}


async def call_gate(req: GateRequest) -> GateResponse:
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(GATE_URL, json=req.model_dump())
            resp.raise_for_status()
            return GateResponse(**resp.json())
    except Exception as exc:
        return GateResponse(
            decision="ALLOW",
            tier_triggered=1,
            explanation=f"Gate unreachable ({exc}), fail-open",
            cache_hit=False,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )


class GraphRunner:
    """
    Builds a LangGraph StateGraph from a GraphBlueprint and runs it.

    event_queue: asyncio.Queue[RunEvent] — main.py drains this for SSE.
    hitl_queue:  asyncio.Queue[HITLDecision] — /run/decide posts here.
    """

    def __init__(
        self,
        blueprint: GraphBlueprint,
        builder_intent: str,
        session_id: str,
        run_id: str,
    ):
        self.blueprint = blueprint
        self.builder_intent = builder_intent
        self.session_id = session_id
        self.run_id = run_id
        self.event_queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        self.hitl_queue: asyncio.Queue[HITLDecision] = asyncio.Queue()

    def _emit(self, event_type: str, agent_name: str = "", tool_name: str = "", **data):
        self.event_queue.put_nowait(RunEvent(
            event_type=event_type,
            agent_name=agent_name or None,
            tool_name=tool_name or None,
            data=data,
            timestamp_ms=int(time.time() * 1000),
        ))

    async def before_tool_call(
        self,
        agent_name: str,
        agent_role: str,
        tool_name: str,
        tool_params: dict,
    ) -> dict:
        """
        Called before every tool execution.
        Returns (possibly modified) tool_params to actually run.
        """
        action_id = str(uuid.uuid4())[:8]
        self._emit("action.requested", agent_name=agent_name, tool_name=tool_name,
                   action_id=action_id, params=tool_params)

        gate_resp = await call_gate(GateRequest(
            session_id=self.session_id,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_params=tool_params,
            builder_intent=self.builder_intent,
            agent_role=agent_role,
        ))

        self._emit("safety.scored", agent_name=agent_name, tool_name=tool_name,
                   misalignment=gate_resp.misalignment_score,
                   oversight=gate_resp.oversight_score,
                   decision=gate_resp.decision,
                   tier=gate_resp.tier_triggered,
                   cache_hit=gate_resp.cache_hit,
                   latency_ms=gate_resp.latency_ms)

        if gate_resp.decision == "ALLOW":
            return tool_params

        # WARN or BLOCK — generate auto-fix then wait for HITL
        fix_resp = generate_fix(AutoFixRequest(
            session_id=self.session_id,
            agent_name=agent_name,
            tool_name=tool_name,
            original_tool_params=tool_params,
            builder_intent=self.builder_intent,
            gate_response=gate_resp,
        ))

        self._emit("action.blocked", agent_name=agent_name, tool_name=tool_name,
                   action_id=action_id,
                   misalignment=gate_resp.misalignment_score,
                   oversight=gate_resp.oversight_score,
                   explanation=gate_resp.explanation,
                   fix_tool_params=fix_resp.fixed_tool_params,
                   fix_explanation=fix_resp.explanation,
                   fix_impact_preview=fix_resp.impact_preview,
                   fix_type=fix_resp.fix_type)

        decision: HITLDecision = await self.hitl_queue.get()
        self._emit("human.decided", agent_name=agent_name, tool_name=tool_name,
                   action_id=action_id, decision=decision.decision)

        if decision.decision == "override":
            self._emit("action.allowed", agent_name=agent_name, tool_name=tool_name,
                       note="builder override")
            return tool_params

        if decision.decision == "approve_fix":
            self._emit("action.allowed", agent_name=agent_name, tool_name=tool_name,
                       note="approved fix")
            return fix_resp.fixed_tool_params

        # modify
        params = decision.modified_params or fix_resp.fixed_tool_params
        self._emit("action.allowed", agent_name=agent_name, tool_name=tool_name,
                   note="builder modified")
        return params

    # ── Hiring scenario nodes ─────────────────────────────────────────────────

    def _agent_by_name(self, name: str):
        name_lower = name.lower()
        for a in self.blueprint.agents:
            if name_lower in a.name.lower():
                return a
        return None

    async def _node_parse(self, state: dict) -> dict:
        agent = self._agent_by_name("parser")
        role = agent.role if agent else "Resume Parser"
        tool_params = {"resume_text": state.get("raw_input", SAMPLE_RESUMES[0]["raw_text"])}

        self._emit("node.started", agent_name="Parser", tool_name="parse_resume")
        final_params = await self.before_tool_call("Parser", role, "parse_resume", tool_params)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, parse_resume, final_params["resume_text"])

        self._emit("node.completed", agent_name="Parser", tool_name="parse_resume",
                   result_summary=f"Parsed {result['name']}")
        return {**state, "parsed_candidates": SAMPLE_RESUMES, "parse_result": result}

    async def _node_score(self, state: dict) -> dict:
        agent = self._agent_by_name("scorer")
        role = agent.role if agent else "Resume Scorer"
        rubric = BIASED_RUBRIC  # gate catches this

        self._emit("node.started", agent_name="Scorer", tool_name="apply_scoring_rubric")

        all_scores = []
        for candidate in state.get("parsed_candidates", SAMPLE_RESUMES):
            tool_params = {"candidate": candidate, "rubric": rubric}
            final_params = await self.before_tool_call(
                "Scorer", role, "apply_scoring_rubric", tool_params
            )
            loop = asyncio.get_event_loop()
            score = await loop.run_in_executor(
                None, apply_scoring_rubric,
                final_params["candidate"], final_params["rubric"]
            )
            all_scores.append(score)
            rubric = final_params["rubric"]  # use approved rubric for remaining candidates

        all_scores.sort(key=lambda x: x["total_score"], reverse=True)
        self._emit("node.completed", agent_name="Scorer", tool_name="apply_scoring_rubric",
                   result_summary=f"Scored {len(all_scores)} candidates")
        return {**state, "scores": all_scores, "top_candidates": all_scores[:3]}

    async def _node_email(self, state: dict) -> dict:
        agent = self._agent_by_name("email")
        role = agent.role if agent else "Email Agent"
        top = state.get("top_candidates", [])
        shortlist = ", ".join(c["candidate_name"] for c in top)
        tool_params = {
            "to": "hiring.manager@company.com",
            "subject": "Shortlist: Top 3 Candidates",
            "body": f"Top 3 candidates by merit score:\n\n{shortlist}\n\nDetails: {top}",
        }

        self._emit("node.started", agent_name="Email", tool_name="send_email")
        final_params = await self.before_tool_call("Email", role, "send_email", tool_params)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, send_email,
            final_params["to"], final_params["subject"], final_params["body"]
        )

        self._emit("node.completed", agent_name="Email", tool_name="send_email",
                   result_summary=f"Email {result['status']}")
        return {**state, "email_result": result}

    # ── Graph assembly ────────────────────────────────────────────────────────

    def _build_graph(self):
        workflow = StateGraph(dict)

        agent_names = [a.name.lower() for a in self.blueprint.agents]
        is_hiring = any("parser" in n or "scorer" in n for n in agent_names)

        if is_hiring:
            workflow.add_node("Parser", self._node_parse)
            workflow.add_node("Scorer", self._node_score)
            workflow.add_node("Email", self._node_email)
            workflow.set_entry_point("Parser")
            workflow.add_edge("Parser", "Scorer")
            workflow.add_edge("Scorer", "Email")
            workflow.add_edge("Email", END)
        else:
            prev = None
            for agent in self.blueprint.agents:
                _agent = agent
                async def generic_node(state: dict, a=_agent) -> dict:
                    for tool in a.tools:
                        params = state.get("input_data", {})
                        final = await self.before_tool_call(a.name, a.role, tool, params)
                        fn = TOOL_FNS.get(tool)
                        if fn:
                            loop = asyncio.get_event_loop()
                            result = await loop.run_in_executor(None, lambda: fn(**final))
                            state = {**state, f"{a.name}_result": result}
                    return state

                workflow.add_node(agent.name, generic_node)
                if prev is None:
                    workflow.set_entry_point(agent.name)
                else:
                    workflow.add_edge(prev, agent.name)
                prev = agent.name

            if prev:
                workflow.add_edge(prev, END)

        return workflow.compile()

    async def run(self, input_data: dict) -> dict:
        self._emit("run.started", session_id=self.session_id, run_id=self.run_id)
        graph = self._build_graph()
        initial_state = {
            "raw_input": input_data.get("description", ""),
            "input_data": input_data,
        }
        result = await graph.ainvoke(initial_state)
        self._emit("run.completed", session_id=self.session_id, run_id=self.run_id,
                   final_keys=list(result.keys()))
        return result
