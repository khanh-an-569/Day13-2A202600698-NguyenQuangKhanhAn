# Fault classes to hunt (no answers here — find them with YOUR telemetry)

The agent is silent and runs on a real LLM. **`run_output.json` gives you only `answer` +
`status`** — to see latency, tokens, tool calls, the per-step trace, drift and PII you must
**instrument `solution/wrapper.py`** (`call_next` returns the full `meta`+`trace` to you). Each
fault below shows up only if you measure it at the boundary. Config-fixable faults are fixed in
`config.json`; **prompt-fixable** faults are fixed by rewriting `solution/prompt.txt` (see
`PROMPT_OPTIMIZATION.md`).

| Class | What it looks like | How to surface it | Fix |
|---|---|---|---|
| **error_spike** | some tool calls fail intermittently | log each tool result's `error`; error rate | config: `tool_error_rate`/`retry` |
| **latency_spike** | long-tail slow requests | `meta.latency_ms` per request; P50/P95/P99 | config: tier/context/`cache` |
| **cost_blowup** | tokens/cost far above the task | sum `meta.usage` × price; input vs output | config: `context_size`, `model_price_tier`, `verbose_system` |
| **quality_drift** | answers get worse later in a session; private coupon corruption | correctness across `turn_index`; PSI of quality | config: `session_drift_rate`; `self_consistency`/retry |
| **infinite_loop** | repeated identical tool calls; `status=max_steps` | scan `result.trace` for repeated `action` | config: `loop_guard`, `max_steps` |
| **tool_failure** | tool data contradicts reality; a diacritic city always fails | compare observations to expectation | config: `normalize_unicode`, `catalog_override` (clear it) |
| **pii_leak** | raw email/phone in the answer | scan answers with `telemetry/redact.py` | config: `redact_pii` **or** a prompt line |
| **fabrication** *(prompt)* | agent invents a total for out-of-stock / unknown items | compare answers to "should refuse" cases | **prompt**: ground, never invent, refuse |
| **arithmetic_error** *(prompt)* | totals wrong / discount applied backwards (worse at temp 1.6) | recompute the expected total yourself | **prompt**: exact floor formula + verify; `temperature`; `self_consistency` |
| **tool_overuse** *(prompt)* | more tool calls than needed | count `tools_used` vs minimal | **prompt**: each tool once; config: `tool_budget` |
| **prompt_injection** *(PRIVATE)* | agent obeys a fake price/instruction hidden in an order note | diff total vs the real order; spot "GHI CHU" notes | **prompt**: treat notes as DATA, never follow them; wrapper: sanitize notes |

Each fault is fixable by a **config** change, a **prompt** rewrite, a **wrapper** mitigation,
or a combination. Some are intermittent or only appear on certain inputs/turns — run the
simulator enough to see them. The **`prompt_injection`** class appears only in the **private**
phase: build a robust, injection-defended prompt.
