# Wrapper API

`solution/wrapper.py` must define:

```python
def mitigate(call_next, question, config, context):
    # call_next(question, config) -> result   (the ONLY way to reach the agent)
    # context = {"session_id", "turn_index", "qid",
    #            "cache": <shared dict across requests>, "cache_lock": <threading.Lock>}
    # return a result dict in the same shape run_agent returns
    return call_next(question, config)
```

`result` shape:
```python
{"answer": str|None, "status": "ok|loop|max_steps|no_action|wrapper_error",
 "steps": int, "trace": [...],
 "meta": {"latency_ms": int, "usage": {"prompt_tokens","completion_tokens","total_tokens"},
          "model": str, "provider": str, "session_id": str, "turn_index": int,
          "tools_used": [...]}}
```

## Legal moves
- retry / backoff, cache (the run is concurrent — guard shared state with `context["cache_lock"]`),
  route to a cheaper/local model, input sanitize (e.g. strip injected order notes),
  output redaction, arithmetic/guardrail validation, fallback, session reset.
- **Prompt routing** — override the agent's system prompt per request:
  ```python
  conf = dict(config); conf["system_prompt"] = my_better_prompt
  result = call_next(question, conf)
  ```
- Your own logging/tracing/metrics (this IS your observability). Import only the Python
  standard library and the bundled `telemetry/` package.

## Illegal (rejected by selfcheck / scored zero)
hardcoding answers; question→answer lookup; importing `observathon_sim._*` or
`observathon_score`; reading instructor files; `socket`/`urllib`/`requests`/`__import__`.

## The agent is SILENT — `run_output.json` is lean (you must instrument)
The agent returns **only an answer + a status code**. `run_output.json` rows contain just
`qid, question, answer, status, session, turn, ts` — **no latency, no tokens, no tool calls,
no per-step trace**. That is deliberate: to observe latency, cost, tool usage, loops, quality
drift, and PII you must **build it yourself in `mitigate()`**.

The good news: `call_next(question, conf)` returns the **full** result to *you* —
`{answer, status, steps, trace, meta:{latency_ms, usage, model, tools_used, ...}}`. Capture
what you need there:
```python
import time
def mitigate(call_next, question, config, context):
    t0 = time.time()
    r = call_next(question, config)
    meta = r.get("meta", {})
    # YOUR observability — the only place these signals exist:
    # logger.log_event("CALL", {"qid": context["qid"], "wall_ms": int((time.time()-t0)*1000),
    #   "latency_ms": meta.get("latency_ms"), "usage": meta.get("usage"),
    #   "tools": meta.get("tools_used"), "steps": r.get("steps"), "trace": r.get("trace")})
    return r
```
The sim also writes a signed **`sealed`** block in `run_output.json` — that is the *scorer's*
tamper-proof copy of the binary-measured metrics (latency/tokens/tools), **not** your
observability. Editing/removing it doesn't help (it zeroes your latency/cost score).

## Note (v6)
The agent runs on a **real LLM** and is **prompt-driven** — the biggest wins come from
`solution/prompt.txt` (and config knobs like `temperature`, `self_consistency`, `tool_budget`),
not the wrapper alone. But the wrapper is now **mandatory for observability** (the only way to
see latency/cost/traces/drift/PII) plus retry/cache/redact/sanitize. The full run is concurrent
(`--concurrency`), so keep `mitigate()` thread-safe (guard `context["cache"]` with `context["cache_lock"]`).
