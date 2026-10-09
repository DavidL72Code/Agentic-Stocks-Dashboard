"""LLM client. The data plane must work with NO api key at all - only the
agent plane needs one. Missing key raises a clear, catchable error."""
from __future__ import annotations
import asyncio, collections, itertools, json, os, re, time
from dataclasses import dataclass
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_openai import ChatOpenAI

# Models are fixed here rather than read from the env: a host whose env had no
# model variable silently ran a default this key can no longer use.
#
# Every call except tool selection alternates between the two Flash-Lite
# models, so each carries half of that load - and half of each free-tier daily
# cap. On one model, 500 requests a day ran out by noon.
#
# Tool selection runs on 3.5 Flash-Lite. It was on Gemma 4 for Gemma's larger
# free quota, but Gemma thinks before it answers and that cannot be switched
# off over this API: picks took 12-24s each and were ~39s of a 48s run. On
# Flash-Lite a pick is under a second. The trade: 3.5 now carries more than
# half the calls, so its daily cap is the one to watch.
POOL = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
SELECT_MODEL = "gemini-3.5-flash-lite"
MODEL = POOL[0]                     # what /api/health reports as "model"
_turn = itertools.count()
_served: collections.Counter = collections.Counter()
# A tool pick is a few hundred tokens; one that has not come back in 15s is
# stuck, and the specialist falls back rather than wait on it.
TIMEOUT = {"select": 15.0}


def chain_for(role: str) -> list[str]:
    """The models to try for one call, in order: the one whose turn it is,
    then the other. Selection tries Gemma first, then both Flash-Lites."""
    i = next(_turn) % len(POOL)
    pair = [POOL[i], POOL[1 - i]]
    if role != "select":
        return pair
    return [SELECT_MODEL] + [m for m in POOL if m != SELECT_MODEL]
BASE_URL = os.environ.get("LLM_BASE_URL",
                          "https://generativelanguage.googleapis.com/v1beta/openai/")


class NoAPIKey(RuntimeError):
    pass


def api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")


# Sized for Gemini's free tier, whose limits are PER MODEL - so each model gets
# its own limiter, and three models are not squeezed through one budget. Per
# process: two servers on one key get twice this between them.
_RPS = float(os.environ.get("LLM_RPS", "0.5"))
_limiters: dict[str, InMemoryRateLimiter] = {}
_clients: dict[tuple[str, float, int], ChatOpenAI] = {}


def client(model: str, timeout: float | None = None, retries: int = 2) -> ChatOpenAI:
    t = timeout or float(os.environ.get("LLM_TIMEOUT", "45"))
    if (model, t, retries) not in _clients:
        k = api_key()
        if not k:
            raise NoAPIKey("Set GEMINI_API_KEY to use the agent. "
                           "The dashboard works without it.")
        if model not in _limiters:
            lim = InMemoryRateLimiter(requests_per_second=_RPS, check_every_n_seconds=0.1,
                                      max_bucket_size=30)
            # The bucket starts EMPTY, so the first question after a restart -
            # every Render wake-up - queued its parallel tool picks two seconds
            # apart. Start with a small burst; the refill rate is unchanged.
            lim.available_tokens = 8.0
            _limiters[model] = lim
        lim = _limiters[model]
        _clients[(model, t, retries)] = ChatOpenAI(model=model, api_key=k, base_url=BASE_URL,
                                                   temperature=0, max_retries=retries,
                                                   timeout=t, rate_limiter=lim,
                                                   stream_usage=True)
    return _clients[(model, t, retries)]


@dataclass
class LLMReply:
    text: str
    tokens: int
    latency_ms: int
    model: str = ""           # the model that actually answered, after any fallback


_RETRY_IN = re.compile(r"retry in ([\d.]+)s", re.I)


def _rate_wait(e: Exception, attempt: int) -> float | None:
    """Seconds to wait before retrying a 429, or None if it will not clear soon.

    A per-minute limit clears within the minute, and the client's own two quick
    retries are not long enough to see it clear - the router then fell back and
    the user got a price summary instead of an answer. A per-DAY limit will not
    clear, so it fails at once rather than hanging the request."""
    if "429" not in str(e) and "RateLimit" not in type(e).__name__:
        return None
    msg = str(e)
    if "PerDay" in msg or "per day" in msg.lower():
        return None
    m = _RETRY_IN.search(msg)
    wait = float(m.group(1)) if m else 4.0 * (2 ** attempt)
    return wait if wait <= 30 else None


_RETRY_LONG = re.compile(r"retry in ((?:\d+h)?(?:\d+m)?[\d.]*s?)", re.I)


def friendly(e: Exception) -> str:
    """One readable line for a failed model call. These reach the screen, and
    a 900-character 429 payload is not something a reader can act on."""
    msg = str(e)
    if "429" in msg or "RateLimit" in type(e).__name__:
        if "PerDay" in msg or "per day" in msg.lower():
            m = _RETRY_LONG.search(msg)
            return ("the model's daily free-tier quota is used up"
                    + (f" (resets in about {m.group(1).split('m')[0]}m)" if m and "h" in m.group(1) else ""))
        return "the model is rate-limited right now; try again in a minute"
    if "Timeout" in type(e).__name__ or "timed out" in msg.lower():
        return "the model took too long to reply"
    if "503" in msg or "overloaded" in msg.lower() or "high demand" in msg.lower():
        return "the model is overloaded right now"
    return f"the model call failed ({type(e).__name__})"


# A model that answered "out of quota for the day" or "not available" will say
# the same thing for hours. Skip it until then instead of paying a failed round
# trip on every call.
_dead_until: dict[str, float] = {}


def _gone(e: Exception) -> float | None:
    """Seconds a model should be skipped for, or None if the error is transient."""
    msg = str(e)
    if ("429" in msg or "RateLimit" in type(e).__name__) and (
            "PerDay" in msg or "per day" in msg.lower()):
        return 1800.0
    if "404" in msg or "no longer available" in msg.lower() or "not found" in msg.lower():
        return 3600.0
    return None


def _moves_on(e: Exception) -> bool:
    """Worth trying the next model: quota, missing model, overload, timeout."""
    msg = str(e).lower()
    return (_gone(e) is not None or "503" in msg or "500" in msg or "internal" in msg
            or "overloaded" in msg
            or "high demand" in msg or "timeout" in type(e).__name__.lower()
            or "timed out" in msg or "429" in msg)


async def _invoke(m: str, msgs, timeout: float | None, retries: int = 2):
    t0 = time.time()
    for attempt in range(3):
        try:
            return await client(m, timeout, retries).ainvoke(msgs)
        except NoAPIKey:
            raise
        except Exception as e:
            wait = _rate_wait(e, attempt)
            if wait is None or attempt == 2 or time.time() - t0 + wait > 50:
                raise
            await asyncio.sleep(wait)


async def call(system: str, user: str, fast: bool = False,
               model: str | None = None, role: str = "main") -> LLMReply:
    """One model call. role="select" is tool selection; anything else takes
    the next turn in the 50/50 rotation. `model` pins an exact one (the
    eval judge does this) with no fallback; `fast=True` means role="select"."""
    t0 = time.time()
    role = "select" if fast else role
    chain = [model] if model else chain_for(role)
    msgs = [SystemMessage(content=system), HumanMessage(content=user)]
    live = [x for x in chain if _dead_until.get(x, 0) < time.time()] or chain[-1:]
    err: Exception | None = None
    for m in live:
        try:
            # a timed-out tool pick is not retried on the same model: the
            # client's own retries turned one 45s wait into 135s. Keyed on the
            # ROLE - the select model also serves the router and the writer.
            slow = role == "select" and not model
            r = await _invoke(m, msgs, TIMEOUT["select"] if slow else None, 0 if slow else 2)
        except NoAPIKey:
            raise
        except Exception as e:
            err = e
            hold = _gone(e)
            if hold:
                _dead_until[m] = time.time() + hold
            if m != live[-1] and _moves_on(e):
                continue
            raise
        usage = getattr(r, "usage_metadata", None) or {}
        tok = usage.get("total_tokens") or (
            (getattr(r, "response_metadata", None) or {}).get("token_usage") or {}
        ).get("total_tokens", 0)
        _served[m] += 1
        return LLMReply(str(r.content), int(tok or 0), int((time.time() - t0) * 1000), m)
    raise err or RuntimeError("no model available")


class AnswerTap:
    """Pull the value of "answer" out of a JSON reply while it is still arriving.

    The writer replies {"gap": ..., "followups": [...], "answer": "..."}, so the
    text a reader wants is a JSON string inside a stream of chunks. This decodes
    that one string incrementally - escapes included, and holding back an escape
    split across two chunks - and hands each new piece to on_text."""

    _KEY = re.compile(r'"answer"\s*:\s*"')
    _ESC = {"n": "\n", "t": "\t", "r": "", "b": "", "f": "", '"': '"', "\\": "\\", "/": "/"}

    def __init__(self, on_text):
        self.on_text, self.buf, self.pos, self.done = on_text, "", None, False

    def feed(self, chunk: str) -> None:
        if self.done or not chunk:
            return
        self.buf += chunk
        if self.pos is None:
            m = self._KEY.search(self.buf)
            if not m:
                return
            self.pos = m.end()
        out, i, b = [], self.pos, self.buf
        while i < len(b):
            c = b[i]
            if c == '"':
                self.done = True
                break
            if c == "\\":
                if i + 1 >= len(b):
                    break                                  # the escaped char is in the next chunk
                e = b[i + 1]
                if e == "u":
                    if i + 6 > len(b):
                        break
                    try:
                        out.append(chr(int(b[i + 2:i + 6], 16)))
                    except ValueError:
                        pass
                    i += 6
                    continue
                out.append(self._ESC.get(e, e))
                i += 2
                continue
            out.append(c)
            i += 1
        self.pos = i
        if out:
            self.on_text("".join(out))


async def stream_call(system: str, user: str, role: str = "main", on_text=None) -> LLMReply:
    """call(), streamed: the same models, fallbacks and rate-limit waits, with
    the reply's "answer" field handed to on_text piece by piece as it arrives.
    A model that fails before its first token hands over to the next one; once
    text has gone out, a failure is raised rather than restarted mid-sentence."""
    t0 = time.time()
    chain = chain_for(role)
    msgs = [SystemMessage(content=system), HumanMessage(content=user)]
    live = [x for x in chain if _dead_until.get(x, 0) < time.time()] or chain[-1:]
    err: Exception | None = None
    for m in live:
        for attempt in range(3):
            tap = AnswerTap(on_text) if on_text else None
            text, tok, started = "", 0, False
            try:
                async for ch in client(m).astream(msgs):
                    piece = ch.content if isinstance(ch.content, str) else ""
                    if piece:
                        started = True
                        text += piece
                        if tap:
                            tap.feed(piece)
                    um = getattr(ch, "usage_metadata", None) or {}
                    if um.get("total_tokens"):
                        tok = um["total_tokens"]
                _served[m] += 1
                return LLMReply(text, int(tok), int((time.time() - t0) * 1000), m)
            except NoAPIKey:
                raise
            except Exception as e:
                err = e
                if started:
                    raise
                wait = _rate_wait(e, attempt)
                if wait is not None and attempt < 2 and time.time() - t0 + wait <= 50:
                    await asyncio.sleep(wait)
                    continue
                hold = _gone(e)
                if hold:
                    _dead_until[m] = time.time() + hold
                break
        if err is not None and not _moves_on(err):
            raise err
    raise err or RuntimeError("no model available")


def status() -> dict:
    """Which model serves each role, and which are being skipped right now."""
    now = time.time()
    return {"alternating": list(POOL), "tool_selection": SELECT_MODEL,
            "calls_served": dict(_served),
            "skipping": {m: int(t - now) for m, t in _dead_until.items() if t > now}}


_THOUGHT = re.compile(r"<(thought|think|thinking)>.*?</\1>", re.DOTALL | re.I)
_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_json(text: str) -> dict | None:
    """The model's JSON object, from whatever it wrapped it in.

    Some models put reasoning first (<thought>...</thought>) and a fenced block
    after it; reasoning can itself contain braces, so a greedy {.*} from the
    first brace swallowed prose and failed. Strip reasoning, prefer a fenced
    block, then fall back to the LAST balanced object that parses.
    """
    t = _THOUGHT.sub("", text or "").strip()
    for cand in [m.group(1) for m in _FENCE.finditer(t)][::-1] + [t]:
        try:
            v = json.loads(cand)
            if isinstance(v, dict):
                return v
        except Exception:
            pass
    ends = [i for i, c in enumerate(t) if c == "}"]
    for end in reversed(ends):
        depth = 0
        for start in range(end, -1, -1):
            depth += t[start] == "}"
            depth -= t[start] == "{"
            if depth == 0:
                try:
                    v = json.loads(t[start:end + 1])
                    if isinstance(v, dict):
                        return v
                except Exception:
                    pass
                break
    return None
