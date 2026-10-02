"""LLM client. The data plane must work with NO api key at all - only the
agent plane needs one. Missing key raises a clear, catchable error."""
from __future__ import annotations
import json, os, re, time
from dataclasses import dataclass
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_openai import ChatOpenAI

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
FAST_MODEL = os.environ.get("GEMINI_FAST_MODEL", MODEL)
BASE_URL = os.environ.get("LLM_BASE_URL",
                          "https://generativelanguage.googleapis.com/v1beta/openai/")


class NoAPIKey(RuntimeError):
    pass


def api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")


_limiter = InMemoryRateLimiter(requests_per_second=0.5, check_every_n_seconds=0.1,
                               max_bucket_size=30)
_clients: dict[str, ChatOpenAI] = {}


def client(model: str) -> ChatOpenAI:
    if model not in _clients:
        k = api_key()
        if not k:
            raise NoAPIKey("Set GEMINI_API_KEY to use the agent. "
                           "The dashboard works without it.")
        _clients[model] = ChatOpenAI(model=model, api_key=k, base_url=BASE_URL,
                                     temperature=0, max_retries=2, timeout=45,
                                     rate_limiter=_limiter)
    return _clients[model]


@dataclass
class LLMReply:
    text: str
    tokens: int
    latency_ms: int


async def call(system: str, user: str, fast: bool = False) -> LLMReply:
    t0 = time.time()
    m = FAST_MODEL if fast else MODEL
    r = await client(m).ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    usage = getattr(r, "usage_metadata", None) or {}
    tok = usage.get("total_tokens") or (
        (getattr(r, "response_metadata", None) or {}).get("token_usage") or {}
    ).get("total_tokens", 0)
    return LLMReply(str(r.content), int(tok or 0), int((time.time() - t0) * 1000))


def parse_json(text: str) -> dict | None:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None
