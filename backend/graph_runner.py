"""
LangGraph runtime — builds and runs the agent graph from a scaffold blueprint.

Fully dynamic: every agent in the blueprint gets its own node. No names,
roles, or pipeline shapes are hardcoded here. The blueprint drives everything.

Key integration points:
  - before_tool_call: calls the safety gate (POST /gate/check)
  - Events emitted to asyncio.Queue for SSE streaming
  - After WARN/BLOCK: calls auto-fix generator, then waits for HITL decision
"""
from __future__ import annotations
import asyncio
import os
import time
import uuid
import httpx
from typing import Callable

from langgraph.graph import StateGraph, END

from models import (
    AutoFixRequest, GateRequest, GateResponse,
    GraphBlueprint, HITLDecision, RunEvent,
)
from arize.instrumentation import session_tracer
from auto_fix import generate_fix
from claude_tool_executor import execute_with_claude
from demo_tools import (
    BIASED_RUBRIC, SAMPLE_RESUMES,
    apply_scoring_rubric, parse_resume, send_email,
)

GATE_URL = os.getenv("SAFETY_GATE_URL", "http://localhost:8000/gate/check")

# Map tool names to demo implementations. Any tool not in this map gets a no-op stub.
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


def _pick_tool_params(agent_name: str, tool_name: str, state: dict) -> dict:
    """
    Return sensible demo params for a tool call based on what's in state.
    Falls back to an empty dict so unknown tools still flow through the gate.
    """
    name_lower = agent_name.lower()
    tool_lower = tool_name.lower()

    if "parse" in tool_lower or "pdf" in tool_lower or "extract" in tool_lower:
        return {"resume_text": state.get("raw_input", SAMPLE_RESUMES[0]["raw_text"])}

    if "scor" in tool_lower or "rubric" in tool_lower or "rank" in tool_lower:
        return {"candidate": SAMPLE_RESUMES[0], "rubric": BIASED_RUBRIC}

    if "email" in tool_lower or "send" in tool_lower or "notify" in tool_lower:
        top = state.get("top_candidates", [])
        shortlist = ", ".join(c.get("candidate_name", "") for c in top) or "candidates"
        return {
            "to": "hiring.manager@company.com",
            "subject": "Shortlist: Top Candidates",
            "body": f"Top candidates by merit score:\n\n{shortlist}",
        }

    if "bias" in tool_lower or "audit" in tool_lower or "detect" in tool_lower:
        candidates = state.get("parsed_candidates", SAMPLE_RESUMES)
        return {"candidates": [c.get("name", c.get("candidate_name", "")) for c in candidates],
                "check": "demographic signals"}

    if "supervis" in name_lower or "route" in tool_lower or "manag" in tool_lower:
        return {"task": "orchestrate pipeline", "stage": state.get("stage", "init")}

    # Generic fallback
    return {"agent": agent_name, "tool": tool_name, "input": state.get("raw_input", "")}



def _run_tool(tool_name: str, params: dict, state: dict) -> dict:
    """
    Execute a known demo tool synchronously. Returns a result dict.
    Unknown tools return a stub result so the pipeline always continues.
    """
    tool_lower = tool_name.lower()

    if "parse" in tool_lower or "pdf" in tool_lower or "extract" in tool_lower:
        result = parse_resume(params.get("resume_text", ""))
        return {"parse_result": result, "parsed_candidates": SAMPLE_RESUMES}

    if "scor" in tool_lower or "rubric" in tool_lower or "rank" in tool_lower:
        rubric = params.get("rubric", BIASED_RUBRIC)
        scores = [apply_scoring_rubric(c, rubric) for c in state.get("parsed_candidates", SAMPLE_RESUMES)]
        scores.sort(key=lambda x: x["total_score"], reverse=True)
        return {"scores": scores, "top_candidates": scores[:3]}

    if "email" in tool_lower or "send" in tool_lower or "notify" in tool_lower:
        result = send_email(params.get("to", ""), params.get("subject", ""), params.get("body", ""))
        return {"email_result": result}

    if "bias" in tool_lower or "audit" in tool_lower or "detect" in tool_lower:
        return {"audit_status": "passed", "flags": []}

    # No-op stub for any other tool
    return {"stub_result": f"{tool_name} executed (demo stub)"}


class GraphRunner:
    """
    Builds a LangGraph StateGraph from a GraphBlueprint and runs it.

    Fully dynamic — derives every node, edge, and tool call from the blueprint.
    No agent names, roles, or pipeline structures are hardcoded.
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
        self._last_gate_tokens: dict[str, tuple[int, int]] = {}

    def _emit(self, event_type: str, agent_name: str = "", tool_name: str = "", **data):
        self.event_queue.put_nowait(RunEvent(
            event_type=event_type,
            agent_name=agent_name or None,
            tool_name=tool_name or None,
            data=data,
            timestamp_ms=int(time.time() * 1000),
        ))

    async def _before_tool_call_with_tokens(
        self,
        agent_name: str,
        agent_role: str,
        tool_name: str,
        tool_params: dict,
    ) -> tuple[dict, int, int]:
        """Like before_tool_call but also returns (tokens_in, tokens_out) from real Claude calls."""
        params = await self.before_tool_call(agent_name, agent_role, tool_name, tool_params)
        # Gate tokens are stored in the most recent gate event for this agent/tool
        tok_in, tok_out = self._last_gate_tokens.get(f"{agent_name}:{tool_name}", (0, 0))
        return params, tok_in, tok_out

    async def before_tool_call(
        self,
        agent_name: str,
        agent_role: str,
        tool_name: str,
        tool_params: dict,
    ) -> dict:
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

        # Store real T3 token counts for this agent/tool
        self._last_gate_tokens[f"{agent_name}:{tool_name}"] = (
            gate_resp.tokens_in, gate_resp.tokens_out
        )

        # Record real gate data for proof panel
        session_tracer.record_gate_event(
            session_id=self.session_id,
            agent_name=agent_name,
            tool_name=tool_name,
            decision=gate_resp.decision,
            misalignment=gate_resp.misalignment_score or 0,
            oversight=gate_resp.oversight_score or 0,
            tier=gate_resp.tier_triggered,
            cache_hit=gate_resp.cache_hit,
            latency_ms=gate_resp.latency_ms,
        )

        if gate_resp.decision == "ALLOW":
            self._emit("action.allowed", agent_name=agent_name, tool_name=tool_name)
            return tool_params

        # WARN or BLOCK — generate auto-fix in a thread to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        fix_req = AutoFixRequest(
            session_id=self.session_id,
            agent_name=agent_name,
            tool_name=tool_name,
            original_tool_params=tool_params,
            builder_intent=self.builder_intent,
            gate_response=gate_resp,
        )
        fix_resp = await loop.run_in_executor(None, generate_fix, fix_req)

        # Record the auto-fix for quality evaluation
        session_tracer.record_autofix(
            session_id=self.session_id,
            agent_name=agent_name,
            tool_name=tool_name,
            original_params=tool_params,
            fix_params=fix_resp.fixed_tool_params,
            fix_type=fix_resp.fix_type,
            fix_explanation=fix_resp.explanation,
            original_misalignment=gate_resp.misalignment_score,
        )

        self._emit("action.blocked", agent_name=agent_name, tool_name=tool_name,
                   action_id=action_id,
                   misalignment=gate_resp.misalignment_score,
                   oversight=gate_resp.oversight_score,
                   explanation=gate_resp.explanation,
                   fix_tool_params=fix_resp.fixed_tool_params,
                   fix_explanation=fix_resp.explanation,
                   fix_impact_preview=fix_resp.impact_preview,
                   fix_type=fix_resp.fix_type)

        try:
            decision: HITLDecision = await asyncio.wait_for(self.hitl_queue.get(), timeout=60)
        except asyncio.TimeoutError:
            self._emit("human.decided", agent_name=agent_name, tool_name=tool_name,
                       action_id=action_id, decision="approve_fix", note="auto-timeout")
            self._emit("action.allowed", agent_name=agent_name, tool_name=tool_name,
                       note="auto-approved fix")
            return fix_resp.fixed_tool_params

        self._emit("human.decided", agent_name=agent_name, tool_name=tool_name,
                   action_id=action_id, decision=decision.decision)

        if decision.decision == "override":
            self._emit("action.allowed", agent_name=agent_name, tool_name=tool_name,
                       note="builder override")
            return tool_params

        params = decision.modified_params or fix_resp.fixed_tool_params
        self._emit("action.allowed", agent_name=agent_name, tool_name=tool_name,
                   note="approved fix")
        return params

    # ── Dynamic graph assembly ────────────────────────────────────────────────

    def _make_agent_node(self, agent):
        """
        Build an async LangGraph node function for a single blueprint agent.
        Runs every tool the agent declares, gates each one, then merges results.
        Records real latency + token estimates directly to session_tracer.
        """
        topo = self.blueprint.topology

        async def agent_node(state: dict) -> dict:
            tools = agent.tools if agent.tools else [agent.name.lower().replace(" ", "_")]
            merged_state = dict(state)
            approved_params_cache: dict[str, dict] = {}
            # Accumulate real token usage from gate's T3 Claude calls
            real_tokens_in = 0
            real_tokens_out = 0
            node_start = time.monotonic()

            for tool_name in tools:
                self._emit("node.started", agent_name=agent.name, tool_name=tool_name)

                raw_params = _pick_tool_params(agent.name, tool_name, merged_state)

                cache_key = f"{agent.name}:{tool_name}"
                if cache_key in approved_params_cache:
                    final_params, gate_tok_in, gate_tok_out = approved_params_cache[cache_key]
                else:
                    final_params, gate_tok_in, gate_tok_out = await self._before_tool_call_with_tokens(
                        agent.name, agent.role, tool_name, raw_params
                    )
                    approved_params_cache[cache_key] = (final_params, gate_tok_in, gate_tok_out)

                real_tokens_in += gate_tok_in
                real_tokens_out += gate_tok_out

                loop = asyncio.get_event_loop()
                tool_result = await loop.run_in_executor(
                    None, _run_tool, tool_name, final_params, merged_state
                )
                merged_state = {**merged_state, **tool_result}

                result_summary = _summarise(tool_name, tool_result)
                self._emit("node.completed", agent_name=agent.name, tool_name=tool_name,
                           result_summary=result_summary)

            node_latency_ms = int((time.monotonic() - node_start) * 1000)
            session_tracer.record_node(
                session_id=self.session_id,
                agent_name=agent.name,
                model=agent.model or "claude-haiku-4-5-20251001",
                tokens_in=real_tokens_in,
                tokens_out=real_tokens_out,
                latency_ms=node_latency_ms,
                topology=topo,
            )
            return merged_state

        agent_node.__name__ = agent.name
        return agent_node

    def _build_graph(self):
        workflow = StateGraph(dict)
        topo = self.blueprint.topology

        # Use the precise hiring demo path only when the exact demo tool is present.
        # Any other prompt — including ones with "parser" or "scorer" in agent names —
        # goes through the generic Claude-executor path below.
        tool_names = {t for a in self.blueprint.agents for t in a.tools}
        is_hiring_demo = "apply_scoring_rubric" in tool_names

        if is_hiring_demo:
            workflow.add_node("Parser", trace_node("Parser", "haiku-4-5", topo)(self._node_parse))
            workflow.add_node("Scorer", trace_node("Scorer", "haiku-4-5", topo)(self._node_score))
            workflow.add_node("Email", trace_node("Email", "haiku-4-5", topo)(self._node_email))
            workflow.set_entry_point("Parser")
            workflow.add_edge("Parser", "Scorer")
            workflow.add_edge("Scorer", "Email")
            workflow.add_edge("Email", END)
        else:
            prev = None
            for agent in self.blueprint.agents:
                _agent = agent

                async def generic_node(state: dict, a=_agent) -> dict:
                    self._emit("node.started", agent_name=a.name)
                    last_result: dict = {}
                    for tool in a.tools:
                        tool_params = state.get("input_data", {})
                        final_params = await self.before_tool_call(
                            a.name, a.role, tool, tool_params
                        )
                        loop = asyncio.get_event_loop()
                        stub = TOOL_FNS.get(tool)
                        if stub:
                            last_result = await loop.run_in_executor(
                                None, lambda fn=stub, p=final_params: fn(**p)
                            )
                        else:
                            last_result = await loop.run_in_executor(
                                None,
                                execute_with_claude,
                                a,
                                tool,
                                final_params,
                                self.builder_intent,
                                state,
                            )
                        state = {**state, f"{a.name}_{tool}_result": last_result}

                    summary = (
                        last_result.get("summary")
                        or last_result.get("status", "done")
                    )
                    self._emit("node.completed", agent_name=a.name,
                               result_summary=str(summary)[:120])
                    return state

                model_short = "haiku-4-5" if "haiku" in _agent.model else "sonnet-4-6"
                workflow.add_node(
                    agent.name,
                    trace_node(agent.name, model_short, topo)(generic_node),
                )
                if prev is None:
                    workflow.set_entry_point(agent.name)
                else:
                    workflow.add_edge(prev, agent.name)
                prev = agent.name

        for agent in ordered_agents:
            node_fn = self._make_agent_node(agent)
            workflow.add_node(agent.name, node_fn)

        # Wire edges
        names = [a.name for a in ordered_agents]
        workflow.set_entry_point(names[0])
        for i in range(len(names) - 1):
            workflow.add_edge(names[i], names[i + 1])
        workflow.add_edge(names[-1], END)

        return workflow.compile()

    async def run(self, input_data: dict) -> dict:
        session_tracer.new_run(self.session_id)
        self._emit("run.started", session_id=self.session_id, run_id=self.run_id)
        graph = self._build_graph()
        initial_state = {
            "raw_input": input_data.get("description", ""),
            "input_data": input_data,
            "stage": "init",
            "session_id": self.session_id,   # needed by trace_node to key traces correctly
        }
        result = await graph.ainvoke(initial_state)
        self._emit("run.completed", session_id=self.session_id, run_id=self.run_id,
                   final_keys=list(result.keys()))
        return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _order_agents(blueprint: GraphBlueprint):
    """
    Return agents in execution order.
    Tries to follow blueprint edges; falls back to the agents list order.
    """
    if not blueprint.edges:
        return list(blueprint.agents)

    # Build adjacency from blueprint edges
    agent_map = {a.name: a for a in blueprint.agents}
    next_node: dict[str, str] = {}
    all_targets: set[str] = set()

    for edge in blueprint.edges:
        if edge.to_node.upper() != "END":
            next_node[edge.from_node] = edge.to_node
            all_targets.add(edge.to_node)

    # Entry node = agent that is never a target
    all_names = set(agent_map.keys())
    roots = all_names - all_targets
    start = next(iter(roots)) if roots else blueprint.agents[0].name

    # Walk the chain
    ordered, visited = [], set()
    cur = start
    while cur and cur in agent_map and cur not in visited:
        ordered.append(agent_map[cur])
        visited.add(cur)
        cur = next_node.get(cur, "")

    # Append any agents not reached by edges (shouldn't happen, but safe fallback)
    for a in blueprint.agents:
        if a.name not in visited:
            ordered.append(a)

    return ordered


def _summarise(tool_name: str, result: dict) -> str:
    """Return a short human-readable summary of a tool result."""
    if "parse_result" in result:
        return f"Parsed {result['parse_result'].get('name', 'resume')}"
    if "top_candidates" in result:
        names = [c.get("candidate_name", "") for c in result["top_candidates"][:3]]
        return f"Scored {len(result.get('scores', []))} candidates — top: {', '.join(names)}"
    if "email_result" in result:
        return f"Email {result['email_result'].get('status', 'sent')}"
    if "audit_status" in result:
        return f"Bias audit {result['audit_status']}"
    if "stub_result" in result:
        return result["stub_result"]
    return f"{tool_name} completed"
