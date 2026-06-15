"""YOUR mitigation + observability layer. The simulator calls mitigate() around the
opaque agent (a REAL LLM) for every request. This is the ONLY place observability can
live -- the agent is silent. Legal moves: retry / cache / route / guardrail / sanitize
/ fallback / session-reset / PROMPT ROUTING, plus your own logging/tracing/metrics.
Illegal: hardcoding answers, importing the agent internals, reading instructor files,
network exfiltration.

  call_next(question, config) -> result   # the only way to reach the black box
  context = {"session_id","turn_index","qid","cache": <shared dict>, "cache_lock": <Lock>}
  result  = {"answer","status","steps","trace","meta":{latency_ms,usage,...}}

PROMPT ROUTING: you can override the agent's system prompt PER REQUEST by setting it in
the config you pass to call_next, e.g.:
    conf = dict(config); conf["system_prompt"] = my_better_prompt
    result = call_next(question, conf)
(Or just edit solution/prompt.txt for a single static prompt used on every request.)
"""
from __future__ import annotations
import os
import time

# You may reuse the Day 13 toolkit, e.g.:
from telemetry.logger import logger
from telemetry.cost import cost_from_usage
from telemetry.redact import redact

# --- AUTOMATIC .ENV LOADING ---
def load_dotenv():
    # Load .env file from the project root directory
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root_dir, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    # Strip quotes if present
                    if val.startswith(('"', "'")) and val.endswith(('"', "'")):
                        val = val[1:-1]
                    os.environ[key] = val

# Load .env when wrapper is imported
load_dotenv()

def mitigate(call_next, question, config, context):
    # --- 1. SET ENVIRONMENT & OVERRIDE CONFIG FROM .ENV ---
    conf = dict(config)
    
    # Map .env configurations dynamically to system environment and runtime config
    llm_provider = os.environ.get("LLM_PROVIDER")
    if llm_provider == "mistral":
        conf["provider"] = "local"
        conf["model"] = os.environ.get("MISTRAL_MODEL", "mistral-medium-latest")
        
        # Route to Mistral API
        mistral_api_key = os.environ.get("MISTRAL_API_KEY")
        mistral_base_url = os.environ.get("MISTRAL_BASE_URL")
        if mistral_api_key:
            os.environ["OPENAI_API_KEY"] = mistral_api_key
        if mistral_base_url:
            os.environ["LOCAL_BASE_URL"] = mistral_base_url
            os.environ["OPENAI_BASE_URL"] = mistral_base_url

    # --- 2. INPUT SANITIZATION (PROMPT INJECTION DEFENSE) ---
    sanitized_question = question
    # Check if the question contains an order note injection (e.g. GHI CHÚ, Ghi chu, Note)
    # Strip dangerous instruction keywords inside notes but keep the plain product details.
    if "GHI CHÚ" in question or "ghi chú" in question.lower() or "note" in question.lower():
        # A simple defense: if order notes contain system directives, clean them or remove instructions
        import re
        # Remove common instruction words in notes to prevent command overrides
        directives = [
            r"hãy\b", r"hay\b", r"bỏ qua\b", r"bo qua\b", r"không được\b", r"khong duoc\b",
            r"chỉ\b", r"chi\b", r"phải\b", r"phai\b", r"system\b", r"override\b", r"ignore\b"
        ]
        note_part = ""
        for marker in ["GHI CHÚ:", "ghi chú:", "Ghi chú:", "Note:", "note:"]:
            if marker in question:
                parts = question.split(marker, 1)
                note_part = parts[1]
                for pattern in directives:
                    note_part = re.sub(pattern, "", note_part, flags=re.IGNORECASE)
                sanitized_question = parts[0] + marker + note_part
                break

    # --- 3. CACHING LAYER ---
    cache = context.get("cache")
    cache_lock = context.get("cache_lock")
    
    if cache is not None:
        with cache_lock:
            if sanitized_question in cache:
                return cache[sanitized_question]

    # --- 4. CALL AGENT WITH RETRY ---
    max_retries = 3
    result = None
    
    for attempt in range(max_retries):
        t0 = time.time()
        result = call_next(sanitized_question, conf)
        wall_ms = int((time.time() - t0) * 1000)
        
        # Retry if loop or wrapper_error status occurs
        if result.get("status") in ["wrapper_error", "loop"] and attempt < max_retries - 1:
            time.sleep(0.1 * (attempt + 1))
            continue
        break

    # --- 5. OBFUSCATE & REDACT PII ON OUTPUT ---
    answer = result.get("answer") or ""
    redacted_answer, pii_count = redact(answer)
    if pii_count > 0:
        result["answer"] = redacted_answer

    # --- 6. OBSERVE & LOG TELEMETRY ---
    meta = result.get("meta", {})
    usage = meta.get("usage", {})
    if logger:
        logger.log_event("AGENT_CALL", {
            "qid": context.get("qid"),
            "session_id": context.get("session_id"),
            "turn_index": context.get("turn_index"),
            "status": result.get("status"),
            "reported_latency_ms": meta.get("latency_ms"),
            "wall_ms": wall_ms,
            "tokens": usage,
            "cost_usd": cost_from_usage(meta.get("model", ""), usage),
            "pii_detected": pii_count > 0,
            "tools_used": meta.get("tools_used", []),
            "steps": result.get("steps")
        })

    # --- 7. SAVE TO CACHE ---
    if result.get("status") == "ok" and cache is not None:
        with cache_lock:
            cache[sanitized_question] = result

    return result
