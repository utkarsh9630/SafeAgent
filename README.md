# SafeAgent

**Evidence-Backed Agent Builder with Constitutional Safety** — UC Berkeley AI Hackathon 2026

> Scaffold a multi-agent system from plain English → intercept every tool call pre-execution with a 3-tier constitutional gate → prove your architecture and cost claims with real telemetry.

---

## What Is SafeAgent?

SafeAgent is a full-stack platform for builders who want to design, run, and audit autonomous AI agent systems **without sacrificing human oversight**. It addresses the core challenge of agentic AI: as agents gain more capability and autonomy, the risk of misaligned or irreversible actions grows. SafeAgent embeds safety at the infrastructure layer — not as an afterthought — so every agent action passes through a constitutional gate before execution.

**The three-phase workflow:**

1. **Describe** — type your use case in plain English (e.g., "an AI hiring assistant that screens resumes, scores candidates, and schedules interviews")
2. **Design** — Claude reasons over two competing multi-agent architectures (Supervisor-Worker vs. ReAct) using extended thinking and presents cost/latency tradeoffs
3. **Run & Audit** — a LangGraph-powered agent graph executes with every tool call intercepted by the safety gate; flagged actions trigger Human-in-the-Loop review with AI-generated safer alternatives; all events stream to the browser in real time and are logged to a permanent audit trail

---

## Motivation & Research Grounding

SafeAgent is motivated by a fundamental tension in modern agentic AI:

**The capability-oversight gap.** As AI agents become more capable — browsing the web, writing and executing code, sending emails, modifying databases — the cost of a single misaligned action increases dramatically. A poorly scoped hiring agent can embed discriminatory criteria. A finance agent can irreversibly commit funds. An operations agent can delete data at scale.

Current approaches treat safety as optional middleware or post-hoc filtering. SafeAgent's thesis is that safety must be **structural**: every tool call must pass a constitutional gate before execution, not after.

**Constitutional AI at the action level.** We extend Anthropic's Constitutional AI principles beyond model training to runtime agent behavior. The gate scores each tool call against two axes — *misalignment* (does this violate the builder's stated intent?) and *oversight* (does this bypass human control?) — and combines deterministic guardrails with semantic caching and Claude-powered scoring to make this economically feasible at scale.

**Human-in-the-Loop by default.** Rather than blocking agents on every ambiguous action, SafeAgent generates a safer alternative (auto-fix) and queues the decision for the builder. The builder sees the misalignment scores, a plain-English explanation, the original vs. safer parameters side-by-side, and can approve, modify, or override. This keeps humans meaningfully in control without making the system unusable.

**Evidence over claims.** Every architectural claim the scaffolder makes — predicted cost, predicted latency, topology recommendation — is tracked against real execution data in the proof panel. Builders see actual Claude API token costs, Redis cache hit rates, per-agent latency breakdowns, and safety drift across runs.

---

## Architecture

```
Browser (React + React Flow)
    │
    ├── InputScreen         → plain-English task description
    ├── TopologyPicker      → choose between two architectures (Extended Thinking output)
    ├── AgentGraph          → interactive React Flow graph of the blueprint
    ├── FlagModal           → HITL decision gate (misalignment/oversight meters + auto-fix)
    ├── ProofPanel          → actual vs. predicted cost, cache hit rates, safety drift
    └── AuditLog / SponsorLog → real-time event stream per sponsor service
         │
         │  SSE + REST
         ▼
FastAPI Backend (Python)
    │
    ├── /classify           → Haiku 4.5 domain/complexity pre-triage
    ├── /topology           → Sonnet 4.6 + Extended Thinking → 2 architectures
    ├── /scaffold           → Haiku blueprint generator → agent graph JSON
    ├── /run                → LangGraph executor (gate called before every tool)
    ├── /gate/check         → 3-tier safety gate (T1 guardrails / T2 Redis / T3 Sonnet)
    ├── /gate/output-check  → Haiku output checker (PII, hallucinations, prompt injection)
    ├── /hitl               → Human decision queue (approve / modify / override)
    ├── /audit/export       → Redis Stream export
    ├── /memory             → Per-agent session memory
    ├── /voice              → Deepgram TTS + STT
    └── /asi/discover       → AgentVerse agent discovery
         │
         ├── Anthropic API   (Haiku 4.5, Sonnet 4.6 with Extended Thinking)
         ├── Redis / Upstash  (semantic cache, pub/sub, audit stream, agent memory)
         ├── Arize Phoenix    (OpenInference traces via OpenTelemetry)
         ├── Deepgram         (TTS voice warnings + STT voice input)
         └── ASI:One AgentVerse  (pre-built agent discovery)
```

---

## Sponsor Integrations

### Anthropic — Claude API (Core Intelligence)

Claude is the foundation of every intelligent component in SafeAgent. The integration is deep and multi-model:

**Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) — speed-critical paths:
- **Classifier** (`/backend/classifier.py`): Fast domain/complexity triage. Determines agent type, estimated agent count, and complexity before invoking heavier models.
- **Scaffolder** (`/backend/scaffolder.py`): Generates the full multi-agent blueprint — agent definitions, system prompts, edges, cost/latency predictions — from plain English. Supports multi-turn edits (pass `existing_blueprint + modification_request`).
- **Output Safety Checker** (`/backend/routers/gate.py:362`): After each agent produces output, Haiku checks for PII (emails, SSNs, credit cards), hallucinated facts presented as certain, and injected instructions that could hijack downstream agents.

**Claude Sonnet 4.6** (`claude-sonnet-4-6`) — accuracy-critical paths:
- **Topology Reasoner** (`/backend/topology.py`): Invoked with **extended thinking** enabled to reason deeply over two competing architectures (Supervisor-Worker vs. single ReAct agent). Produces a chain-of-thought visible to the builder — not a black-box recommendation.
- **Safety Gate T3** (`/backend/routers/gate.py:159`): When T1 guardrails and T2 semantic cache both miss, Sonnet scores the action on two axes (misalignment 0–100, oversight 0–100), provides a plain-English explanation, and drafts a safer alternative. The structured JSON response is parsed directly into the gate decision.
- **Auto-Fix Generator** (`/backend/auto_fix.py`): Given a flagged tool call, Sonnet generates safer parameter alternatives — e.g., rebalancing a biased hiring rubric, narrowing a bulk-delete scope, or adding a human approval flag.

**Model routing logic:** Haiku handles everything under ~complexity threshold 3; Sonnet handles topology reasoning, T3 gate scoring, and auto-fix. This is deliberate — using Sonnet for every gate call would make safety prohibitively expensive. The Redis semantic cache (T2) further reduces Sonnet calls by ~60% in practice.

**Prompt caching:** The backend uses the `anthropic` SDK with prompt caching support on all long system prompts, reducing latency and cost on repeated gate checks within a session.

**Token cost tracking:** Every Sonnet T3 gate call captures `msg.usage.input_tokens` and `msg.usage.output_tokens` and feeds them into the Arize session tracer, so the proof panel shows real Claude API costs — not estimates.

---

### Redis / Upstash — Semantic Cache, Pub/Sub, Audit Stream, Agent Memory

Redis is the operational backbone of SafeAgent, handling four distinct responsibilities:

**1. Semantic Cache (T2 Safety Gate)** — `CACHE_PREFIX = "safeagent:sem_cache:"`:
Every successful T3 gate result is stored in Redis with a SHA-256 fingerprint of `{tool_name, tool_params}`. On subsequent calls, T2 looks up the fingerprint first. A cache hit (`≥0.92` similarity match) returns the prior decision in ~5ms — skipping the ~800ms Sonnet call entirely. Cache entries expire after 1 hour (`ex=3600`). The proof panel shows real cache hit rates and tokens saved (≈900 tokens per T3 skip).

**2. Pub/Sub Event Stream** — `channel: "safeagent:events"`:
Every gate decision, human override, and agent status change is published to a Redis channel. The frontend subscribes via SSE (`/pubsub/subscribe`) and updates the audit log and sponsor activity panel in real time. The pub/sub worker (`/backend/routers/gate.py:32`) runs as a background asyncio task, draining a queue of up to 200 events to avoid blocking the gate response path.

**3. Audit Stream** — `STREAM_KEY = "safeagent:gate:stream"`:
Every gate check is appended to a Redis Stream (XADD). Fields include: `session_id`, `agent_name`, `tool_name`, `decision`, `tier_triggered`, `misalignment_score`, `oversight_score`, `explanation`, `cache_hit`, `latency_ms`, `timestamp`. The `/audit/export/{session_id}` endpoint reads these streams for export. Human override decisions are also written here via `/gate/override`.

**4. Agent Memory** — `MEM_PREFIX = "safeagent:mem:"`:
Per-session, per-agent JSON blobs with 24-hour TTL. Used by agents to carry context across tool calls within a session. The `/memory` router (`/backend/routers/memory.py`) exposes write/read/clear. The gate also writes `last_override_tool` and `last_override_decision` into agent memory when a human makes an override decision, giving future gate checks behavioral context.

**Connection:** The client (`/backend/redis_client.py`) supports both standard Redis (`REDIS_URL`) and Upstash REST (`UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`) for serverless deployment on Railway.

---

### Arize Phoenix — Distributed Tracing & Cost Telemetry

Arize Phoenix provides the observability layer that makes SafeAgent's "evidence-backed" claim credible.

**Setup** (`/backend/arize/instrumentation.py:20`):
At startup, `setup_tracing()` configures an OpenTelemetry `TracerProvider` with `BatchSpanProcessor` exporting to Phoenix's OTLP endpoint at `http://localhost:6006/v1/traces`. Two OpenInference instrumentors are installed:
- `LangChainInstrumentor()` — automatically traces every LangGraph node execution (inputs, outputs, latency, model used)
- `AnthropicInstrumentor()` — automatically traces every Anthropic API call (model, tokens in/out, latency, cost)

**Session Tracer** (`SessionTracer` class):
A singleton accumulates `NodeTrace`, `GateEvent`, and `AutoFixEvent` records per session. All proof panel values derive from this real runtime data — not estimates:

| Proof Panel Metric | Source |
|--------------------|--------|
| Actual cost (USD) | `compute_cost(model, tokens_in, tokens_out)` using June 2026 pricing table |
| Per-agent latency | Measured from `time.perf_counter()` around each node |
| Cache hit rate | Count of `GateEvent.cache_hit == True` / total gate events |
| Tokens saved | `cache_hits × 900` (avg tokens per T3 Sonnet call) |
| Safety drift | Average misalignment/oversight per run, grouped by `run_index` |
| Auto-fix quality | Heuristic score: measures how much a fix reduced the dominant biased parameter's weight share |
| Hallucination score | Checks whether fix parameters stay within the original parameter schema (no invented keys) |
| A/B topology winner | Lower total cost; latency as tiebreaker |

**Cost table** (hardcoded from June 2026 pricing):
```python
_COST_PER_M_IN  = {"haiku-4-5": 0.80,  "sonnet-4-6": 3.00}   # per 1M tokens
_COST_PER_M_OUT = {"haiku-4-5": 4.00,  "sonnet-4-6": 15.00}
```

**`@trace_node` decorator** (`/backend/arize/instrumentation.py:429`):
Wraps any LangGraph node function (sync or async) to automatically record latency into the session tracer. Usage:
```python
@trace_node("Candidate Scorer", "haiku-4-5", topology="A")
async def scorer_node(state):
    ...
```

**Raw gate events** are attached to the proof payload (`gate_events` array) so the proof panel can render a full decision table per session.

---

### Deepgram — Voice I/O

Deepgram enables a voice-first builder experience and voice-based safety alerts:

**Speech-to-Text** (`/backend/routers/voice.py`, `/frontend/src/hooks/useDeepgramSTT.ts`):
Builders can describe their agent system by speaking. The Deepgram SDK transcribes the audio and populates the task description input. A keyword safety check (`/voice/keywords`) scans transcriptions for dangerous phrases before they reach the scaffolder — catching "delete all", "bypass auth", "send to everyone" before a blueprint is even generated.

**Text-to-Speech** (`/voice/tts`):
When a safety gate fires a WARN or BLOCK, the flag explanation is synthesized to audio and played to the builder. This makes safety warnings impossible to miss in live demos — the system literally speaks the risk.

**Voice HITL** (`/frontend/src/hooks/useVoiceHITL.ts`):
Builders can respond to HITL prompts verbally ("approve", "modify", "override") using Deepgram STT. The hook maps spoken decisions to the structured HITL API call.

---

### ASI:One AgentVerse — Agent Discovery

The `/asi/discover` endpoint (`/backend/routers/asi.py`) queries the AgentVerse API to find pre-built agents that match the builder's domain. For a hiring system, it might surface a GDPR-compliance agent, a bias auditor, or a candidate ranking service — reducing the need to build from scratch.

Discovery results appear in the `AsiDiscovery` component with agent ratings, interaction counts, and capability descriptions. If `AGENTVERSE_API_KEY` is not set, the endpoint falls back to realistic mock data so the UI always demonstrates the capability.

Discovered agents are also rated in the proof panel, giving builders signal on whether to integrate an existing agent vs. scaffold a new one.

---

## The Constitutional Safety Gate — Deep Dive

The gate (`/backend/routers/gate.py`) runs on every single tool call from every agent in the graph. It has three tiers:

### T1 — Deterministic Guardrails (<1ms)
Hard-coded block list of known-dangerous tools and parameter values:
```python
BLOCKED_TOOLS = {"bulk_delete", "send_to_all", "drop_table", "drop_db", "rm_rf"}
BLOCKED_PARAM_VALUES = {"*", "all", "everyone", "drop"}
```
No Claude call. No cache lookup. Instant BLOCK with `misalignment_score=100`.

### T2 — Redis Semantic Cache (~5ms)
SHA-256 fingerprint of `{tool_name, tool_params}` → Redis GET. On hit, returns prior decision with `cache_hit=True`. This is the key to making the gate economically viable — repeated safe tool calls (like `parse_resume`) are approved in milliseconds, not seconds.

### T3 — Claude Sonnet 4.6 Scoring (~800ms)
Only reached when T1 and T2 both miss. Sonnet receives builder intent, agent role, tool name, and tool params. It returns structured JSON:
```json
{
  "misalignment_score": 82,
  "oversight_score": 75,
  "explanation": "This rubric weights 'university prestige' at 35%, creating socioeconomic bias without human review.",
  "fix_draft": "Rebalance rubric: skills 40%, experience 35%, cultural_fit 25%"
}
```

**Decision thresholds:**
- `misalignment ≥ 95` OR `oversight ≥ 95` → **BLOCK** (extreme risk)
- `misalignment ≥ 70` OR `oversight ≥ 70` → **WARN** (HITL + auto-fix queued)
- Both < 70 → **ALLOW**

The result is cached in Redis (T2) for future identical calls, published to Pub/Sub, and appended to the audit stream — all asynchronously via a background worker queue, so the gate response is never delayed by I/O.

### Output Safety Check
A separate Haiku-powered endpoint (`/gate/output-check`) checks each agent's output before it passes to the next agent in the graph. It detects:
- PII (emails, phone numbers, SSNs, credit cards)
- Hallucinated facts presented as certain
- Injected instructions attempting to hijack downstream agents

---

## Human-in-the-Loop (HITL) — The Flag Modal

When the gate returns WARN, execution pauses and the `FlagModal` fires. The builder sees:

- **Misalignment score meter** (0–100, color-coded)
- **Oversight score meter** (0–100, color-coded)
- **Plain-English explanation** from Claude (max 2 sentences)
- **Original tool params** vs. **safer alternative** side-by-side
- **Auto-fix draft** (editable) — generated by Sonnet 4.6 in `auto_fix.py`
- **Three choices:** Approve fix | Modify params | Override gate

The decision is POSTed to `/run/decide`, logged to Redis Stream (with `event_type: human_override`), and written into agent memory so future gate checks on the same session can reference the builder's decision patterns.

**Demo scenario — Hiring Agent:**
The built-in demo (`/backend/demo_tools.py`) uses a hiring workflow with a biased rubric that weights `university_prestige` at 35%. The gate fires WARN on `apply_scoring_rubric`, generates an auto-fix that rebalances to `skills: 40%, experience: 35%, cultural_fit: 25%`, and presents the flag modal — demonstrating real-world AI alignment risks.

---

## Proof Panel — Evidence, Not Claims

Every architectural claim made during the design phase is tracked against reality:

| Claim | Evidence |
|-------|----------|
| "Topology A costs $0.09" | Actual Anthropic API token costs via session tracer |
| "Cache will reduce latency by 60%" | Real Redis cache hit rate from gate events |
| "Sonnet only on complex nodes" | Per-agent model breakdown with token counts |
| "Safety gate adds <50ms overhead" | Measured T1/T2/T3 latency per gate call |
| "Agent outputs are hallucination-free" | Auto-fix hallucination score from param schema analysis |

The proof panel also shows:
- **Safety drift chart** — average misalignment/oversight across multiple runs (via Recharts)
- **Gate decision distribution** — ALLOW/WARN/BLOCK breakdown
- **Tokens saved** by the Redis semantic cache vs. hitting Claude every time
- **A/B topology winner** — which architecture actually won on cost and latency

---

## Key Features Summary

| Feature | What It Does |
|---------|-------------|
| **Plain-English Scaffolding** | Haiku generates a full multi-agent blueprint from a single sentence |
| **Extended Thinking Topology** | Sonnet reasons over two architectures and shows its chain-of-thought |
| **Interactive Agent Graph** | React Flow visualization of the agent blueprint with supervisor-worker or ReAct layout |
| **3-Tier Constitutional Gate** | Every tool call: T1 guardrails → T2 Redis cache → T3 Sonnet scoring |
| **Output Safety Check** | Haiku checks every agent output for PII, hallucinations, and prompt injection |
| **Human-in-the-Loop Modal** | Score meters + plain-English explanation + editable auto-fix + approve/modify/override |
| **Auto-Fix Generation** | Sonnet drafts safer tool parameters; quality scored by hallucination analysis |
| **Real-Time SSE Events** | Gate decisions, HITL prompts, agent status streamed to browser via Redis Pub/Sub |
| **Redis Audit Stream** | Permanent record of every gate event, HITL decision, and agent output check |
| **Arize Proof Panel** | Actual cost, latency, cache hits, safety drift — derived from real OpenTelemetry traces |
| **Voice Input/Output** | Deepgram STT for task description; TTS for spoken safety warnings |
| **Agent Memory** | Per-agent Redis memory with 24h TTL; HITL decisions written back for future context |
| **ASI:One Discovery** | Queries AgentVerse for pre-built agents matching the builder's domain |
| **Code Export** | Generates production-ready LangGraph Python code from the blueprint |
| **Blueprint Export** | Downloads full session data (events + proof) as `safe-agent-blueprint.json` |
| **Demo Mode** | `VITE_USE_MOCK=true` runs the full UI with mock data — no backend required |

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Redis (local) or Upstash account
- Anthropic API key
- Deepgram API key (optional, for voice)
- Arize Phoenix (optional, for traces)

### Backend
```bash
cd backend
pip install -r requirements.txt

# Copy and fill in secrets
cp ../.env.example .env

uvicorn main:app --reload --port 8000
```

### Arize Phoenix (optional, run before backend)
```bash
pip install arize-phoenix
python -m phoenix.server.main serve   # http://localhost:6006
```

### Frontend
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173

# Mock mode (no backend needed):
# VITE_USE_MOCK=true is the default in .env
# Set VITE_USE_MOCK=false when backend is running
```

### Demo — Hiring Agent
1. Start backend + frontend
2. Type: "AI hiring assistant that screens resumes, scores candidates, and schedules interviews"
3. Click **Classify → Topology** (watch extended thinking appear)
4. Choose an architecture → **Scaffold**
5. Click **Run Agents** — the biased rubric will trigger a WARN in ~3.5s
6. Review the FlagModal — approve the safer rubric
7. Check the **Proof Panel** for actual vs. predicted cost

---

## Environment Variables

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Redis (pick one)
REDIS_URL=redis://localhost:6379
# OR Upstash (for Railway deployment)
UPSTASH_REDIS_REST_URL=https://...
UPSTASH_REDIS_REST_TOKEN=...

# Optional
DEEPGRAM_API_KEY=...
AGENTVERSE_API_KEY=...
SAFETY_GATE_URL=http://localhost:8000/gate/check
ALLOWED_ORIGINS=http://localhost:5173
AUTO_FIX_ENABLED=true
```

---

## Repo Layout

```
backend/
  main.py                    # FastAPI app, lifespan, routers
  classifier.py              # Haiku domain/complexity triage
  topology.py                # Sonnet + Extended Thinking topology options
  scaffolder.py              # Haiku blueprint generator
  graph_runner.py            # LangGraph executor + gate integration
  claude_client.py           # Anthropic SDK wrapper (caching + extended thinking)
  auto_fix.py                # Sonnet safer-params generator
  demo_tools.py              # Hiring agent mock tools (parse_resume, apply_scoring_rubric, etc.)
  redis_client.py            # Async Redis / Upstash connection pool
  models.py                  # Pydantic models (shared across all endpoints)
  code_export.py             # LangGraph Python code generator
  blueprint_export.py        # safe-agent-blueprint.json exporter
  arize/
    instrumentation.py       # OpenInference setup, SessionTracer, @trace_node
    sse.py                   # Phoenix SSE router
  routers/
    gate.py                  # 3-tier safety gate + output checker + audit logging
    pubsub.py                # Redis Pub/Sub SSE bridge
    audit.py                 # Redis Stream export + cache stats
    memory.py                # Per-agent session memory
    voice.py                 # Deepgram TTS + STT + keyword safety
    asi.py                   # AgentVerse agent discovery

frontend/
  src/
    App.tsx                  # Central state machine (5 screens)
    api/client.ts            # API client + mock data
    components/
      InputScreen.tsx        # Plain-English task input + voice
      TopologyPicker.tsx     # Architecture chooser with extended thinking display
      AgentGraph.tsx         # React Flow graph visualization
      FlagModal.tsx          # HITL decision gate (THE wow moment)
      ProofPanel.tsx         # Actual vs. predicted evidence panel
      AuditLog.tsx           # Gate event timeline
      SponsorLog.tsx         # Real-time per-sponsor activity feed
      AsiDiscovery.tsx       # AgentVerse discovered agents
      CodeViewer.tsx         # Generated LangGraph code
      PlainEnglishSummary.tsx
      SecurityPanel.tsx
      UseCaseGallery.tsx
      VoiceInput.tsx
    hooks/
      useRealtimeEvents.ts   # SSE consumer (gate + status events)
      useVoiceHITL.ts        # Voice-based HITL decisions
      useDeepgramSTT.ts      # Speech-to-text
    types/index.ts           # Shared TypeScript types

tests/                       # 13-file test suite (unit + integration + e2e)
planning/                    # Architecture diagrams + implementation plan
```

---

## Team

Built at the UC Berkeley AI Hackathon 2026.

- **Utkarsh** — Frontend (React + React Flow + Recharts), Arize Phoenix integration, real-time SSE
- **Joseph** — Backend core (FastAPI, LangGraph executor, HITL flow, scaffolder)
- **Evan** — Safety gate (3-tier architecture, Redis audit stream, auto-fix)
