# SafeAgent Backend — Shared Interfaces

Backend runs on `http://localhost:8000`

---

## For Evan (Safety Gate integration)

Your gate runs at `http://localhost:8001/gate/check` (configure in `.env` → `SAFETY_GATE_URL`).

**Input my graph runner sends to your gate:**
```json
{
  "session_id": "string",
  "agent_name": "Resume Scorer",
  "tool_name": "apply_scoring_rubric",
  "tool_params": { "candidate": {...}, "rubric": {...} },
  "builder_intent": "Build a merit-based hiring agent...",
  "agent_role": "Scores candidates based on rubric"
}
```

**Output I expect back from your gate:**
```json
{
  "decision": "BLOCK",
  "tier_triggered": 3,
  "misalignment_score": 87,
  "oversight_score": 31,
  "explanation": "Rubric weights university tier at 35%...",
  "fix_draft": "Consider reweighting to emphasize experience...",
  "cache_hit": false,
  "latency_ms": 342
}
```

- `decision`: `"ALLOW"` → executes, `"WARN"` or `"BLOCK"` → pauses for auto-fix + HITL
- If gate is down, the runner **fails open** (logs the miss, continues)

---

## For Utkarsh (Frontend / Arize)

### REST flow

```
POST /classify        { description: str }
POST /topology        { description, classification }
POST /scaffold        { description, classification, chosen_topology, session_id }
POST /run/start       { session_id, blueprint, builder_intent, input_data }
  → returns { run_id, stream_url }
GET  /run/{run_id}/stream   SSE stream of RunEvent objects
POST /run/decide      { session_id, run_id, action_id, decision, modified_params? }
GET  /export/{session_id}?measured_cost_usd=0.11&...  → safe-agent-blueprint.json
GET  /health
```

### SSE event types

| `event_type`        | Key fields in `data`                                                |
|---------------------|---------------------------------------------------------------------|
| `run.started`       | session_id, run_id                                                  |
| `node.started`      | agent_name, tool_name                                               |
| `action.requested`  | agent_name, tool_name, action_id, params                            |
| `safety.scored`     | misalignment, oversight, decision, tier, cache_hit, latency_ms      |
| `action.blocked`    | action_id, misalignment, oversight, explanation, fix_tool_params, fix_explanation, fix_impact_preview, fix_type |
| `human.decided`     | action_id, decision                                                 |
| `action.allowed`    | agent_name, tool_name, note                                         |
| `node.completed`    | agent_name, tool_name, result_summary                               |
| `run.completed`     | session_id, run_id                                                  |
| `run.error`         | error                                                               |
| `heartbeat`         | (keepalive — ignore)                                                |

### HITL decision payload

```json
{
  "session_id": "abc",
  "run_id": "xyz",
  "action_id": "8chr-id",
  "decision": "approve_fix",
  "modified_params": null
}
```
`decision` ∈ `"approve_fix"` | `"modify"` | `"override"`

### Blueprint export

```
GET /export/{session_id}?measured_cost_usd=0.11&measured_latency_sec=10.8&measured_tokens_total=5847
```
Returns `safe-agent-blueprint.json` as file download.
