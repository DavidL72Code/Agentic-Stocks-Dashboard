"""Plain language: the words a reader with no finance background trips on.

"Nvidia outperformed its peer median with a 3.5% beta-adjusted excess return"
passed every check this project had - every figure grounded, two per sentence,
short - and means nothing to someone who has never invested. Asking the writer
to use plain words worked about half the time, so, like the figure check, this
is a gate: jargon found in an answer goes back to the editor with the everyday
wording to use instead, before the answer ships.

Two kinds of term:
- HARD: never acceptable to a lay reader, however explained - say the thing
  instead ("beta-adjusted excess return" -> what it did after allowing for its
  swings).
- SOFT: real names people will meet elsewhere (P/E, operating margin), allowed
  when the first use carries a plain explanation right after it - in brackets,
  or "meaning ...", or ", a measure of ...".
"""
from __future__ import annotations
import re

# Every prompt that writes for the reader carries this block - the specialists
# too, because the writer copies their wording. No braces: SYNTH_PROMPT is a
# format string.
PLAIN_RULES = """
PLAIN WORDS - the reader has never invested. Say what a number MEANS for the
company or the reader, in everyday words, and leave the analyst term out:
- beta 1.9 -> "tends to move about twice as much as the market"
- beta-adjusted excess return of -9.1 -> "once you allow for its bigger swings,
  it did about 9 points worse than its peers"
- peer median / cohort -> "the typical similar company"
- realised volatility 102% -> "its price swings a lot - often by double digits in
  a month"
- consensus strong_buy, mean price target -> "most analysts recommend buying;
  on average they expect $X in a year" (their view, not ours)
- debt-to-equity 1.71 -> "it owes about $1.71 for every $1 the business is worth
  on its books"; current ratio 1.94 -> "about $2 of short-term assets for each $1
  of bills due this year"; net cash -> "$X more cash than debt"
- co-direction 55.6% vs 70.1% baseline -> "they moved the same way on 5 of 9
  report days - less often than these two usually do (70% of ordinary days)".
  The baseline is THESE TWO stocks on normal days, never "similar companies".
- analyst mean rating 1.29 -> leave the score out; "most analysts recommend
  buying"
- realised volatility 102% -> "its price swings a lot"; never "annual price
  swings of 102%" (nobody can picture it)
- 10-year yield 5.1% -> "the interest rate on 10-year US government bonds rose
  to 5.1%"; VIX -> "the market's fear gauge"
- forward P/E 34 -> "the price is about 34 times the profit expected next
  year"; trailing P/E 137 -> "about 137 times its profit over the past year"
- percentile of its range -> "near its highest price of the past year"
- analysts keeping their ratings -> "analysts have not changed their views".
  That is ANALYSTS, not "how investors feel" - keep who holds the view.
- leave out: price-to-book, multiples, momentum, sentiment, catalyst,
  headwinds, liquidity, upside, decouple, days to cover, year-over-year,
  trailing, risk profile.
Use the plain phrase INSTEAD of the term - never the term followed by a
definition in brackets. Write natural sentences a 14-year-old could read
aloud. Never tell the reader what to feel or do.
"""

HARD: list[tuple[str, str, str]] = [
    # (label, pattern, the everyday wording to use instead)
    ("beta-adjusted excess return", r"beta[- ]adjusted(?: excess)?(?: return)?",
     "say what it means: 'after allowing for how much it usually swings with the market, it did X points better (or worse) than expected'"),
    ("excess return", r"\bexcess returns?\b", "say 'did X points better (or worse) than ...'"),
    ("beta", r"\bbeta\b", "say 'tends to move about X times as much as the market'"),
    ("volatility", r"\bvolatility\b(?! index)|\bprice swing rate\b|\brealised vol\w*|\b(?:highly |very |extremely )?volatile\b|\bannual price swings? of\b",
     "say 'big price swings' or 'its price typically moves about X% in a year'"),
    ("momentum", r"\bmomentum\b", "say which way the price has been heading"),
    ("valuation multiples", r"\bvaluation (?:multiples?|levels?)\b|\bmultiples?\b|\bre-?rating\b",
     "say 'how pricey the stock is compared with its profit'"),
    ("consensus", r"\bconsensus\b", "say 'most analysts' or 'the average analyst'"),
    ("analyst rating score", r"\bmean rating\b|\brating (?:of|score) \d", "leave the score out; say 'most analysts recommend buying'"),
    ("reiterate", r"\breiterat\w*", "say 'repeated' or 'stuck with'"),
    ("analyst rating codes", r"\boutperform rating\w*|\boverweight\b|\bunderweight\b|\bstrong buy\b",
     "say 'analysts mostly recommend buying' (as their view, not ours)"),
    ("peer median", r"\bpeer (?:median|cohort|group)\b|\bcohort\b|\bmedian\b",
     "say 'the typical similar company'"),
    ("co-direction", r"\bco-?direction\b", "say 'how often they move the same way'"),
    ("baseline", r"\bbaseline\b", "say 'on a normal day' or 'usually'"),
    ("capture of moves", r"\bcapture(?:s|d)? of\b|\bmedian capture\b", "say 'how much of the move it follows'"),
    ("net cash position", r"\bnet cash(?: position)?\b", "say 'it has $X more cash than debt'"),
    ("current ratio", r"\bcurrent ratio\b", "say 'it has $X of short-term assets for each $1 of bills due within a year'"),
    ("cash burn", r"\bcash burn\b|\bburn rate\b", "say 'spending more cash than it brings in'"),
    ("unregistered shares", r"\bunregistered (?:share|stock|securit)\w*", "say 'selling new shares directly to investors'"),
    ("sentiment", r"\bsentiment\b", "say 'how investors feel about ...'"),
    ("drawdown", r"\bdrawdown\b", "say 'drop from its peak'"),
    ("capitulation", r"\bcapitulat\w*", "say 'panic selling'"),
    ("support / resistance", r"\b(?:resistance|support) (?:level|zone)\b|\bresistance at\b",
     "say 'a price it has struggled to rise above' or 'a price where it has tended to stop falling'"),
    ("headwinds / tailwinds", r"\bheadwinds?\b|\btailwinds?\b", "say what is holding it back or helping it"),
    ("catalyst", r"\bcatalysts?\b", "say 'the next event that could move the price'"),
    ("basis points", r"\bbasis points?\b|\bbps\b", "say 'hundredths of a percent'"),
    ("year over year", r"\bYoY\b|\byear[- ]over[- ]year\b", "say 'compared with a year earlier'"),
    ("trailing", r"\bTTM\b|\btrailing\b", "say 'over the last 12 months'"),
    ("debt-funded", r"\bdebt[- ]funded\b|\bleverag\w*", "say 'paid for with borrowed money' or 'how much it borrows'"),
    ("priced in", r"\bpriced in\b|\brisk[- ]off\b|\brotation (?:out of|into)\b",
     "say 'already reflected in the price' / 'investors selling X to buy Y'"),
    ("dilution", r"\bdilut\w*", "say 'issuing new shares, which shrinks each existing share's slice'"),
    ("EPS", r"\bEPS\b", "say 'profit per share'"),
    ("price-to-book", r"\bprice[- ]to[- ]book\b", "leave it out, or say 'price compared with what the company owns minus what it owes'"),
    ("10-year yield", r"\b10-year (?:Treasury )?yield\b|\byields?\b(?= (?:rose|fell|ticked|climbed|dropped|jumped))",
     "say 'the interest rate on 10-year US government bonds'"),
    ("volatility index", r"\bvolatility index\b|\bVIX\b", "say 'the market's fear gauge (the VIX)'"),
    ("yield", r"\byields?\b", "say 'the interest rate on 10-year US government bonds'"),
    ("liquidity", r"\bliquidity\b", "say 'cash on hand to pay its bills'"),
    ("days to cover", r"\bdays to cover\b", "leave it out"),
    ("upside / downside", r"\b(?:upside|downside)(?: potential)?\b", "say 'X% above (or below) today's price'"),
    ("decouple", r"\bdecoupl\w*", "say 'moves on its own'"),
    ("percentile", r"\bpercentile\b", "say 'near its highest (or lowest) price of the past year'"),
    ("risk profile", r"\brisk[- ](?:profile|adjusted)\b|\bfactored in\b", "say what the risk is in plain words"),
    ("valuation", r"\bvaluations?\b|\bvalued at\b", "say 'how pricey the stock is'"),
    ("float", r"\bthe float\b|\bof (?:the |its )?float\b", "say 'of its shares that trade'"),
    ("correlation", r"\bcorrelat\w*", "say 'how closely their prices move together' (and leave the coefficient out)"),
    ("decelerate", r"\bdecelerat\w*|\baccelerat\w*", "say 'slowed' or 'sped up'"),
    ("fiscal year", r"\bfiscal (?:year|quarter)\b", "say 'next year' or 'the company's year'"),
    ("telling the reader what to do", r"\byou (?:do not|don't|should|shouldn't|should not) (?:need to )?(?:worry|buy|sell|hold)\b",
     "state the facts that answer it instead of telling the reader what to feel or do"),
]

SOFT: list[tuple[str, str, str]] = [
    ("forward P/E", r"\bforward (?:P/E|price[- ]to[- ]earnings)(?: ratio)?",
     "say 'its price compared with the profit expected next year' instead"),
    ("P/E", r"\bP/E(?: ratio)?\b|\bprice[- ]to[- ]earnings(?: ratio)?",
     "say 'about X times its yearly profit' instead"),
    ("profit margins", r"\b(?:operating|gross|net|profit) margins?\b",
     "say 'it keeps X cents of each $1 of sales' instead"),
    ("debt-to-equity", r"\bdebt[- ]to[- ]equity(?: ratio)?\b", "say 'it owes about $X for every $1 the business is worth on its books' instead"),
    ("moving average", r"\b(?:50|200)-day (?:moving )?average\b|\bmoving average\b",
     "say 'its average price over the last 50 days' instead"),
    ("RSI", r"\bRSI\b", "say 'it has been sold hard lately' instead"),
    ("price target", r"\b(?:mean |average )?price targets?\b", "say 'analysts on average expect $X in a year' instead"),
    ("short interest", r"\bshort interest\b", "say 'X% of its shares are bets that the price will fall' instead"),
    ("free cash flow", r"\bfree cash flow\b", "say 'cash left after running and investing in the business' instead"),
    ("market cap", r"\bmarket cap(?:italization)?\b", "say 'market value (what all its shares are worth together)'"),
    ("book value", r"\bbook value\b", "say 'what the business is worth on its books'"),
    ("earnings per share", r"\bearnings per share\b", "say 'profit per share'"),
    ("52-week high/low", r"\b52-week (?:high|low|range)\b", "say 'its highest (or lowest) price of the past year' instead"),
]

# an explanation right after the term, often after its number: "a debt-to-equity
# ratio of 0.18, meaning it relies very little on borrowed money"
_GLOSS = re.compile(r"\(|\bmeaning\b|\bwhich means\b|\bi\.e\.|\ba measure of\b|, or how\b|\bthat is,|—", re.I)
_H = [(lab, re.compile(p, re.I if not lab.isupper() else 0), hint) for lab, p, hint in HARD]
_S = [(lab, re.compile(p, re.I if lab not in ("RSI", "EPS") else 0), hint) for lab, p, hint in SOFT]


def jargon(text: str) -> list[dict]:
    """Terms a reader with no finance background would not understand, with the
    plain wording to use instead. Empty when the answer reads plainly."""
    t = text or ""
    out, seen = [], set()
    for lab, rx, hint in _H:
        m = rx.search(t)
        if m and lab not in seen:
            seen.add(lab); out.append({"term": m.group(0), "kind": "hard", "fix": hint})
    for lab, rx, hint in _S:
        m = rx.search(t)
        if not m or lab in seen:
            continue
        # explained on first use, within the next few words
        if _GLOSS.search(t[m.end(): m.end() + 70]):
            continue
        seen.add(lab); out.append({"term": m.group(0), "kind": "soft", "fix": hint})
    return out


def shaped(text: str) -> bool:
    """One headline sentence then bullets - or a one-sentence answer to a
    lookup. A multi-sentence paragraph is not the shape, and nor is a headline
    that just repeats the question back."""
    t = (text or "").strip()
    first = next((l.strip() for l in t.splitlines() if l.strip()), "")
    if first.endswith("?"):
        return False
    if any(l.strip().startswith(("- ", "• ")) for l in t.splitlines()):
        return True
    return len([s for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]) <= 1


def _norm(x: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()


def tidy(text: str) -> str:
    """Deterministic clean-up the writer and its editor kept missing:
    - a first line that is a question (the question repeated back) goes, and
      the first bullet becomes the headline;
    - a bullet that repeats the headline or an earlier bullet goes.
    It only removes or moves text, so every figure stays grounded."""
    lines = (text or "").strip().split("\n")
    first = next((i for i, l in enumerate(lines) if l.strip()), None)
    if first is not None and lines[first].strip().endswith("?"):
        lines.pop(first)
        k = next((i for i, l in enumerate(lines) if l.strip()), None)
        if k is not None and lines[k].lstrip().startswith(("- ", "• ")):
            lines[k] = lines[k].lstrip()[2:]
            if k + 1 < len(lines) and lines[k + 1].strip():
                lines.insert(k + 1, "")              # headline, blank line, bullets
    seen, out = set(), []
    for l in lines:
        key = _norm(l.lstrip("-• "))
        if l.lstrip().startswith(("- ", "• ")) and key in seen:
            continue                                  # a repeated point
        if key:
            seen.add(key)
        out.append(l)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def report(text: str) -> dict:
    j = jargon(text)
    return {"jargon": j, "shaped": shaped(text), "ok": not j and shaped(text)}
