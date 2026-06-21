import type {
  ClassifyResponse,
  TopologyResponse,
  TopologyOption,
  ScaffoldResponse,
  GraphBlueprint,
  HITLDecision,
  ProofData,
  AuditEvent,
} from "../types";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
// Gate service is now merged into the main backend — same base URL.
// VITE_GATE_URL can override if deployed separately, otherwise falls back to BASE.
const GATE_BASE = import.meta.env.VITE_GATE_URL ?? BASE;

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${path} → HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return res.json();
}

export const api = {
  base: () => BASE,
  health: () => get<{ status: string }>("/health"),

  classify: (description: string) =>
    post<ClassifyResponse>("/classify", { description }),

  topology: (description: string, classification: ClassifyResponse) =>
    post<TopologyResponse>("/topology", { description, classification }),

  scaffold: (
    description: string,
    classification: ClassifyResponse,
    chosen_topology: TopologyOption,
    session_id: string,
    existing_blueprint?: GraphBlueprint,
    modification_request?: string,
  ) =>
    post<ScaffoldResponse>("/scaffold", {
      description,
      classification,
      chosen_topology,
      session_id,
      existing_blueprint,
      modification_request,
    }),

  runStart: (
    session_id: string,
    blueprint: GraphBlueprint,
    builder_intent: string,
    input_data: Record<string, unknown> = {},
  ) =>
    post<{ run_id: string; stream_url: string }>("/run/start", {
      session_id,
      blueprint,
      builder_intent,
      input_data,
    }),

  runDecide: (decision: HITLDecision) =>
    post<{ ok: boolean }>("/run/decide", decision),

  // Stream URLs — consumed via EventSource in useRealtimeEvents
  streamUrl: (run_id: string) => `${BASE}/run/${run_id}/stream`,
  // Evan's Redis Pub/Sub SSE — gate events streamed directly from Railway to browser
  gateSubscribeUrl: () => `${GATE_BASE}/pubsub/subscribe`,

  exportBlueprint: (
    session_id: string,
    measured_cost_usd?: number,
    measured_latency_sec?: number,
    measured_tokens_total?: number,
  ) => {
    const params = new URLSearchParams();
    if (measured_cost_usd != null) params.set("measured_cost_usd", String(measured_cost_usd));
    if (measured_latency_sec != null) params.set("measured_latency_sec", String(measured_latency_sec));
    if (measured_tokens_total != null) params.set("measured_tokens_total", String(measured_tokens_total));
    const qs = params.toString();
    return `${BASE}/export/${session_id}${qs ? "?" + qs : ""}`;
  },

  exportCode: (session_id: string) => `${BASE}/export/${session_id}/code`,

  fetchCode: async (session_id: string): Promise<string> => {
    const r = await fetch(`${BASE}/export/${session_id}/code`);
    if (!r.ok) return "";
    return r.text();
  },

  discoverAgents: (domain: string, description: string) =>
    post<{ agents: unknown[]; source: string; query: string }>("/asi/discover", { domain, description }),

  proof: (session_id: string, predicted_cost_usd?: number) => {
    const qs = predicted_cost_usd != null ? `?predicted_cost_usd=${predicted_cost_usd}` : "";
    return get<ProofData>(`/proof/${session_id}${qs}`);
  },

  audit: (session_id: string) =>
    get<{ events: AuditEvent[] }>(`/audit/${session_id}`).catch(() => ({
      events: [] as AuditEvent[],
    })),
};

// ── Mock data (used in VITE_USE_MOCK=true mode) ───────────────────────────────

export const MOCK = {
  classify: (): ClassifyResponse => ({
    domain: "hiring",
    complexity: "medium",
    risk_profile: "High — external side effects (email) + bias risk (scoring rubric)",
    agent_count_estimate: 3,
    tool_count_estimate: 4,
    has_external_api: true,
  }),

  topology: (): TopologyResponse => ({
    thinking_summary: "Fixed sequential steps with compliance risk → Supervisor-Worker for cleaner audit trail",
    option_a: {
      id: "A",
      name: "Supervisor-Worker",
      description: "A coordinator agent delegates to three specialized sub-agents.",
      tradeoffs_pro: ["Clean per-node audit trail", "Isolated failure domains", "Compliance-friendly"],
      tradeoffs_con: ["Extra orchestration hop", "Coordinator is a SPOF"],
      estimated_cost_usd_low: 0.08,
      estimated_cost_usd_high: 0.11,
      estimated_latency_sec: 4.2,
      recommended: true,
      reasoning_chain:
        "The hiring workflow involves sequential steps with a clear hierarchy: a coordinator orchestrates resume parsing, scoring, and email dispatch. Supervisor-Worker is a better fit because each sub-agent has a discrete, bounded role and failures should be isolated. ReAct is better for open-ended research where the agent self-directs. Here, the goal is fixed and each step is deterministic. Supervisor-Worker also gives cleaner audit trails — every sub-agent decision is attributed to a named node, which matters for compliance in hiring contexts.",
    },
    option_b: {
      id: "B",
      name: "ReAct (Single Agent)",
      description: "One agent reasons and acts iteratively using all tools.",
      tradeoffs_pro: ["Lower cost (−33%)", "Less orchestration overhead"],
      tradeoffs_con: ["All actions from one agent — harder to audit", "No isolation if tool fails"],
      estimated_cost_usd_low: 0.05,
      estimated_cost_usd_high: 0.07,
      estimated_latency_sec: 3.1,
      recommended: false,
      reasoning_chain:
        "ReAct works well for open-ended research where the agent must self-direct. For a hiring pipeline with fixed steps, it loses the per-agent audit trail that compliance requires.",
    },
  }),

  scaffold: (): ScaffoldResponse => ({
    session_id: "mock-session",
    blueprint: {
      topology: "A",
      topology_name: "Supervisor-Worker",
      entry_node: "Coordinator",
      prediction: {
        cost_usd: 0.09,
        latency_sec: 4.2,
        tokens_in: 3320,
        tokens_out: 1590,
        bottleneck_agent: "Candidate Scorer",
        confidence: "medium",
      },
      edges: [
        { from_node: "Coordinator", to_node: "Resume Parser" },
        { from_node: "Coordinator", to_node: "Candidate Scorer" },
        { from_node: "Coordinator", to_node: "Email Agent" },
      ],
      agents: [
        { name: "Coordinator", role: "Orchestrates sub-agents", model: "claude-sonnet-4-6", tools: [], system_prompt: "" },
        { name: "Resume Parser", role: "Extracts structured data from resumes", model: "claude-haiku-4-5-20251001", tools: ["parse_resume"], system_prompt: "" },
        { name: "Candidate Scorer", role: "Scores candidates on merit rubric", model: "claude-haiku-4-5-20251001", tools: ["apply_scoring_rubric"], system_prompt: "" },
        { name: "Email Agent", role: "Sends shortlist notifications", model: "claude-haiku-4-5-20251001", tools: ["send_email"], system_prompt: "" },
      ],
    },
  }),

  flagPayload: () => ({
    action_id: "ab12cd34",
    misalignment: 87,
    oversight: 31,
    explanation:
      "The rubric `prestige_weighted_v2` assigns 40% weight to university prestige tier. This directly conflicts with the builder's stated intent of 'merit-based' hiring and introduces proxy discrimination. The goal was to find qualified candidates — prestige weighting selects for institutional access, not ability.",
    fix_tool_params: { rubric: "skills_merit_v1", candidates: ["alice", "bob", "charlie"] },
    fix_explanation:
      "Replace `prestige_weighted_v2` with `skills_merit_v1` which weights: (1) demonstrated technical skills 50%, (2) relevant experience 30%, (3) communication samples 20%. Remove any institution-name or graduation-year filters.",
    fix_impact_preview: "Candidate ranking changes: Alice ↑ (strong portfolio), Bob = (unchanged), Charlie ↑ (relevant experience now weighted higher)",
    fix_type: "rubric_replacement",
  }),

  proof: (): ProofData => ({
    predicted_cost_usd: 0.09,
    topology_a: {
      actual_cost_usd: 0.11,
      actual_latency_ms: 4800,
      per_agent: [
        { agent_name: "Coordinator", model: "claude-sonnet-4-6", tokens_in: 820, tokens_out: 340, latency_ms: 1100, cost_usd: 0.031, safety_score: null, topology: "A", step: 1 },
        { agent_name: "Resume Parser", model: "claude-haiku-4-5-20251001", tokens_in: 1200, tokens_out: 600, latency_ms: 800, cost_usd: 0.021, safety_score: null, topology: "A", step: 2 },
        { agent_name: "Candidate Scorer", model: "claude-haiku-4-5-20251001", tokens_in: 900, tokens_out: 450, latency_ms: 2300, cost_usd: 0.038, safety_score: 87, topology: "A", step: 3 },
        { agent_name: "Email Agent", model: "claude-haiku-4-5-20251001", tokens_in: 400, tokens_out: 200, latency_ms: 600, cost_usd: 0.02, safety_score: null, topology: "A", step: 4 },
      ],
    },
    topology_b: {
      actual_cost_usd: 0.07,
      actual_latency_ms: 3400,
      per_agent: [
        { agent_name: "ReAct Agent", model: "claude-sonnet-4-6", tokens_in: 3200, tokens_out: 1400, latency_ms: 3400, cost_usd: 0.07, safety_score: 72, topology: "B", step: 1 },
      ],
    },
    safety_drift: [
      { run: 1, misalignment: 87, oversight: 31 },
      { run: 2, misalignment: 12, oversight: 18 },
      { run: 3, misalignment: 11, oversight: 17 },
    ],
    redis_cache_hits: 3,
    redis_total_calls: 6,
    tokens_saved: 2700,
    autofix_eval_score: 0.91,
    hallucination_score: 0.96,
    prior_flags_on_pattern: 0,
    ab_winner: "B",
  }),
};
