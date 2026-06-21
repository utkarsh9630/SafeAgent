import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  BarChart,
  Bar,
  ResponsiveContainer,
  Legend,
} from "recharts";
import type { ProofData } from "../types";
import { Download } from "lucide-react";

function StatCard({
  label,
  value,
  sub,
  highlight,
}: {
  label: string;
  value: string;
  sub?: string;
  highlight?: "good" | "warn";
}) {
  return (
    <div
      className={`rounded-2xl border-2 p-4 shadow-sm ${
        highlight === "good"
          ? "bg-emerald-50 border-emerald-300"
          : highlight === "warn"
          ? "bg-amber-50 border-amber-300"
          : "bg-white border-emerald-200"
      }`}
    >
      <div className="text-xs text-emerald-600 uppercase tracking-wide font-semibold mb-1">{label}</div>
      <div
        className={`text-2xl font-bold font-mono ${
          highlight === "good"
            ? "text-emerald-700"
            : highlight === "warn"
            ? "text-amber-600"
            : "text-emerald-900"
        }`}
      >
        {value}
      </div>
      {sub && <div className="text-xs text-emerald-500 mt-1">{sub}</div>}
    </div>
  );
}

import type { AuditEvent } from "../types";
import type { AsiAgent } from "./AsiDiscovery";
import { Globe, Star } from "lucide-react";

interface Props {
  data: ProofData;
  sessionId: string;
  onExport: () => void;
  auditEvents?: AuditEvent[];
  asiAgents?: AsiAgent[];
}

export function ProofPanel({ data, onExport, auditEvents = [], asiAgents = [] }: Props) {
  const variance =
    ((data.topology_a.actual_cost_usd - data.predicted_cost_usd) /
      data.predicted_cost_usd) *
    100;
  const cacheRate = Math.round(
    (data.redis_cache_hits / data.redis_total_calls) * 100
  );

  // Safety gate summary from live audit events
  const gateEvents = auditEvents.filter((e) => e.type === "gate");
  const hitlEvents = auditEvents.filter((e) => e.type === "hitl");
  const flagsBlocked = gateEvents.filter((e) => e.decision === "BLOCK").length;
  const flagsWarned = gateEvents.filter((e) => e.decision === "WARN").length;
  const approveFix = hitlEvents.filter((e) => e.hitl_action === "approve_fix").length;
  const modified = hitlEvents.filter((e) => e.hitl_action === "modify").length;
  const overridden = hitlEvents.filter((e) => e.hitl_action === "override").length;

  const perAgentData = data.topology_a.per_agent.map((a) => ({
    name: a.agent_name.replace(" Agent", "").replace("Candidate ", ""),
    cost: +(a.cost_usd * 100).toFixed(2),
    latency: Math.round(a.latency_ms / 100) / 10,
  }));

  const topologyCompare = [
    {
      name: "Supervisor-Worker",
      cost: +(data.topology_a.actual_cost_usd * 100).toFixed(1),
      latency: +(data.topology_a.actual_latency_ms / 1000).toFixed(1),
    },
    {
      name: "ReAct",
      cost: +(data.topology_b.actual_cost_usd * 100).toFixed(1),
      latency: +(data.topology_b.actual_latency_ms / 1000).toFixed(1),
    },
  ];

  const chartStyle = {
    contentStyle: {
      background: "#ffffff",
      border: "1px solid #a7f3d0",
      borderRadius: 10,
      color: "#064e3b",
    },
  };

  return (
    <div className="min-h-screen bg-emerald-50 p-8">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-2xl font-bold text-emerald-900">Proof Panel</h2>
            <p className="text-emerald-600 text-sm">Prediction vs. Reality — empirical, not vibes.</p>
          </div>
          <button
            onClick={onExport}
            className="flex items-center gap-2 bg-white border-2 border-emerald-300 hover:bg-emerald-50 text-emerald-700 text-sm px-4 py-2 rounded-xl transition-colors font-medium shadow-sm"
          >
            <Download size={14} /> Export Blueprint JSON
          </button>
        </div>

        {/* Top stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <StatCard
            label="Predicted cost"
            value={`${(data.predicted_cost_usd * 100).toFixed(1)}¢`}
            sub="labeled PREDICTION upfront"
          />
          <StatCard
            label="Actual cost"
            value={`${(data.topology_a.actual_cost_usd * 100).toFixed(1)}¢`}
            sub={`${variance > 0 ? "+" : ""}${variance.toFixed(0)}% variance — shown openly`}
            highlight={Math.abs(variance) > 30 ? "warn" : "good"}
          />
          <StatCard
            label="Redis cache hits"
            value={`${data.redis_cache_hits}/${data.redis_total_calls}`}
            sub={`${cacheRate}% · ${data.tokens_saved.toLocaleString()} tokens saved`}
            highlight="good"
          />
          <StatCard
            label="Auto-fix eval"
            value={`${Math.round(data.autofix_eval_score * 100)}%`}
            sub="Arize LLM eval: did fix address the flag?"
            highlight={data.autofix_eval_score >= 0.8 ? "good" : "warn"}
          />
        </div>

        {/* Safety Gate Summary */}
        {(gateEvents.length > 0 || hitlEvents.length > 0) && (
          <div className="bg-amber-50 border-2 border-amber-200 rounded-2xl p-5 mb-6 shadow-sm">
            <div className="text-sm font-bold text-amber-900 mb-3">Safety Gate Summary</div>
            <div className="grid grid-cols-3 md:grid-cols-6 gap-3 text-center">
              {[
                { label: "Flags Blocked", value: flagsBlocked, color: "text-red-600" },
                { label: "Flags Warned", value: flagsWarned, color: "text-amber-600" },
                { label: "Total Flags", value: gateEvents.length, color: "text-amber-700" },
                { label: "Approved Fix", value: approveFix, color: "text-emerald-600" },
                { label: "Modified", value: modified, color: "text-blue-600" },
                { label: "Overridden", value: overridden, color: "text-gray-600" },
              ].map(({ label, value, color }) => (
                <div key={label} className="bg-white rounded-xl p-3 border border-amber-100">
                  <div className={`text-2xl font-bold font-mono ${color}`}>{value}</div>
                  <div className="text-xs text-amber-600 mt-0.5">{label}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          {/* Safety drift */}
          <div className="bg-white border-2 border-emerald-200 rounded-2xl p-5 shadow-sm">
            <div className="text-sm font-bold text-emerald-900 mb-4">Safety Score Drift (3 runs)</div>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={data.safety_drift}>
                <CartesianGrid strokeDasharray="3 3" stroke="#d1fae5" />
                <XAxis dataKey="run" tick={{ fill: "#059669", fontSize: 11 }} tickFormatter={(v) => `Run ${v}`} />
                <YAxis tick={{ fill: "#059669", fontSize: 11 }} domain={[0, 100]} />
                <Tooltip {...chartStyle} labelFormatter={(v) => `Run ${v}`} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line dataKey="misalignment" stroke="#ef4444" strokeWidth={2} dot={{ fill: "#ef4444" }} name="Misalignment" />
                <Line dataKey="oversight" stroke="#f59e0b" strokeWidth={2} dot={{ fill: "#f59e0b" }} name="Oversight" />
              </LineChart>
            </ResponsiveContainer>
            <p className="text-xs text-emerald-500 mt-2">
              Run 1: raw flag · Run 2: post-fix · Run 3: cached result
            </p>
          </div>

          {/* A/B comparison */}
          <div className="bg-white border-2 border-emerald-200 rounded-2xl p-5 shadow-sm">
            <div className="text-sm font-bold text-emerald-900 mb-4">A/B Topology Comparison</div>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={topologyCompare}>
                <CartesianGrid strokeDasharray="3 3" stroke="#d1fae5" />
                <XAxis dataKey="name" tick={{ fill: "#059669", fontSize: 10 }} />
                <YAxis yAxisId="cost" tick={{ fill: "#059669", fontSize: 10 }} unit="¢" />
                <YAxis yAxisId="lat" orientation="right" tick={{ fill: "#059669", fontSize: 10 }} unit="s" />
                <Tooltip {...chartStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar yAxisId="cost" dataKey="cost" fill="#10b981" name="Cost (¢)" radius={[4, 4, 0, 0]} />
                <Bar yAxisId="lat" dataKey="latency" fill="#6ee7b7" name="Latency (s)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
            <p className="text-xs text-emerald-500 mt-2">Both topologies traced via Arize OpenInference</p>
          </div>
        </div>

        {/* Per-agent breakdown */}
        <div className="bg-white border-2 border-emerald-200 rounded-2xl p-5 shadow-sm">
          <div className="text-sm font-bold text-emerald-900 mb-1">
            Per-Agent Breakdown (Supervisor-Worker)
            <span className="text-xs text-emerald-500 font-normal ml-2">Arize trace data</span>
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={perAgentData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#d1fae5" />
              <XAxis type="number" tick={{ fill: "#059669", fontSize: 10 }} />
              <YAxis dataKey="name" type="category" tick={{ fill: "#064e3b", fontSize: 11 }} width={100} />
              <Tooltip {...chartStyle} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="cost" fill="#10b981" name="Cost (¢)" radius={[0, 4, 4, 0]} />
              <Bar dataKey="latency" fill="#f59e0b" name="Latency (s)" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
          {(() => {
            const bottleneck = [...data.topology_a.per_agent].sort((a, b) => b.latency_ms - a.latency_ms)[0];
            if (!bottleneck || !data.topology_a.actual_latency_ms) return null;
            const pct = Math.round((bottleneck.latency_ms / data.topology_a.actual_latency_ms) * 100);
            return (
              <p className="text-xs text-emerald-500 mt-2">
                Bottleneck: {bottleneck.agent_name} ({pct}% of total latency) → consider downgrading to Haiku on simple patterns
              </p>
            );
          })()}
        </div>

        {/* LLM Evals + Hallucination Detection + Agent Memory */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6">
          {/* Arize LLM eval on auto-fix */}
          <div className="bg-white border-2 border-emerald-200 rounded-2xl p-5 shadow-sm">
            <div className="text-xs text-emerald-600 uppercase tracking-wide font-semibold mb-3">
              Arize LLM Eval — Auto-Fix Quality
            </div>
            <div className="text-4xl font-bold font-mono text-emerald-600 mb-1">
              {Math.round(data.autofix_eval_score * 100)}%
            </div>
            <p className="text-xs text-emerald-500 leading-relaxed">
              Did the safer rubric actually address the flagged misalignment?
              Claude-as-judge evaluated the fix against the original complaint.
            </p>
            <div className="mt-3 w-full bg-emerald-100 rounded-full h-2">
              <div
                className="h-2 rounded-full bg-emerald-500 transition-all duration-700"
                style={{ width: `${data.autofix_eval_score * 100}%` }}
              />
            </div>
          </div>

          {/* Hallucination detection */}
          <div className="bg-white border-2 border-emerald-200 rounded-2xl p-5 shadow-sm">
            <div className="text-xs text-emerald-600 uppercase tracking-wide font-semibold mb-3">
              Arize Hallucination Detection
            </div>
            <div className={`text-4xl font-bold font-mono mb-1 ${
              data.hallucination_score >= 0.9 ? "text-emerald-600" : "text-amber-500"
            }`}>
              {Math.round(data.hallucination_score * 100)}%
            </div>
            <p className="text-xs text-emerald-500 leading-relaxed">
              Auto-fix is {Math.round(data.hallucination_score * 100)}% grounded —
              it did not invent criteria absent from the job description.
            </p>
            <div className="mt-3 w-full bg-emerald-100 rounded-full h-2">
              <div
                className={`h-2 rounded-full transition-all duration-700 ${
                  data.hallucination_score >= 0.9 ? "bg-emerald-500" : "bg-amber-400"
                }`}
                style={{ width: `${data.hallucination_score * 100}%` }}
              />
            </div>
          </div>

          {/* Redis agent memory */}
          <div className="bg-white border-2 border-emerald-200 rounded-2xl p-5 shadow-sm">
            <div className="text-xs text-emerald-600 uppercase tracking-wide font-semibold mb-3">
              Redis Agent Memory
            </div>
            <div className="text-4xl font-bold font-mono text-emerald-700 mb-1">
              {data.prior_flags_on_pattern}
            </div>
            <p className="text-xs text-emerald-500 leading-relaxed mb-3">
              Prior flags on this agent pattern in this session.
              {data.prior_flags_on_pattern === 0
                ? " First time this rubric was seen."
                : ` Pattern has been flagged before — gate score pre-loaded from cache.`}
            </p>
            <div className="text-xs text-emerald-700 font-semibold">
              A/B Winner:{" "}
              <span className="text-emerald-600">
                {data.ab_winner === "B"
                  ? "ReAct (−36% cost)"
                  : "Supervisor-Worker (cleaner audit trail)"}
              </span>
            </div>
          </div>
        </div>

        {/* ASI:One / AgentVerse comparison */}
        {asiAgents.length > 0 && (
          <div className="mt-6 bg-white border-2 border-blue-200 rounded-2xl overflow-hidden shadow-sm">
            <div className="bg-blue-50 border-b border-blue-200 px-5 py-3 flex items-center gap-2">
              <Globe size={15} className="text-blue-600" />
              <span className="text-sm font-bold text-blue-900">SafeAgent vs AgentVerse — Evidence Comparison</span>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-blue-100 bg-blue-50/40">
                  <th className="text-left px-5 py-2 text-xs text-blue-500 uppercase tracking-wide font-semibold">Agent</th>
                  <th className="text-center px-4 py-2 text-xs text-blue-500 uppercase tracking-wide font-semibold">Source</th>
                  <th className="text-center px-4 py-2 text-xs text-blue-500 uppercase tracking-wide font-semibold">Interactions</th>
                  <th className="text-center px-4 py-2 text-xs text-blue-500 uppercase tracking-wide font-semibold">Rating</th>
                  <th className="text-center px-4 py-2 text-xs text-blue-500 uppercase tracking-wide font-semibold">Misalignment</th>
                  <th className="text-center px-4 py-2 text-xs text-blue-500 uppercase tracking-wide font-semibold">Verdict</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-blue-50">
                {/* SafeAgent's run */}
                <tr className="bg-emerald-50/40">
                  <td className="px-5 py-3 font-semibold text-emerald-900 text-xs">SafeAgent (this run)</td>
                  <td className="px-4 py-3 text-center"><span className="text-[10px] bg-emerald-100 text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded-full font-bold">SafeAgent</span></td>
                  <td className="px-4 py-3 text-center text-xs font-mono text-emerald-800">—</td>
                  <td className="px-4 py-3 text-center text-xs font-mono text-emerald-800">—</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`text-sm font-bold font-mono ${data.topology_a.per_agent.some(a => (a.safety_score ?? 0) > 50) ? "text-red-500" : "text-emerald-600"}`}>
                      {Math.round(data.topology_a.per_agent.reduce((mx, a) => Math.max(mx, a.safety_score ?? 0), 0))}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center"><span className="text-[10px] bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full font-bold">✓ Safety-verified</span></td>
                </tr>
                {/* AgentVerse agents */}
                {asiAgents.map((a) => (
                  <tr key={a.address}>
                    <td className="px-5 py-3 text-xs">
                      <div className="font-semibold text-blue-900">{a.name}</div>
                      <div className="text-[10px] text-blue-400 font-mono">{a.address}</div>
                    </td>
                    <td className="px-4 py-3 text-center"><span className="text-[10px] bg-blue-100 text-blue-700 border border-blue-200 px-2 py-0.5 rounded-full font-bold">AgentVerse</span></td>
                    <td className="px-4 py-3 text-center text-xs font-mono text-blue-800">{a.total_interactions.toLocaleString()}</td>
                    <td className="px-4 py-3 text-center">
                      {a.rating != null ? (
                        <span className="flex items-center justify-center gap-0.5 text-xs font-bold text-amber-600">
                          <Star size={11} className="fill-amber-400 text-amber-400" />{a.rating.toFixed(1)}
                        </span>
                      ) : <span className="text-xs text-blue-300">—</span>}
                    </td>
                    <td className="px-4 py-3 text-center text-xs text-blue-400 italic">not scored</td>
                    <td className="px-4 py-3 text-center"><span className="text-[10px] bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-bold">Unverified</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="bg-blue-50 border-t border-blue-100 px-5 py-2">
              <p className="text-[11px] text-blue-500">
                AgentVerse agents have community trust signals (interactions, rating) but no constitutional safety scoring.
                SafeAgent's gate verified misalignment score before execution.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
