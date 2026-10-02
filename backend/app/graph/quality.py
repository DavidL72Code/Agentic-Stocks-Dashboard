"""Deterministic prose checks used inside the graph.

The prompts ask for short sentences and few figures. A model complies most of
the time and occasionally returns a 134-word sentence with 48 figures in it.
Prompting cannot fix variance - so the output is measured, and repaired when it
fails. Mirrors the metric in evals/rubric.py so the graph and the evals agree.
"""
from __future__ import annotations
import re

_SENT = re.compile(r"(?<=[.!?])\s+")
_NUM = re.compile(r"(?<![\w.-])-?\d[\d,]*(?:\.\d+)?%?(?![\w-])")
_MONTHS = ("january|february|march|april|may|june|july|august|september|october|"
           "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")
# digits that name rather than measure
_NAMING = [
    re.compile(rf"\b(?:{_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*\d{{0,4}}", re.I),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\bQ[1-4]\s*(?:FY)?\s*\d{0,4}\b", re.I),
    re.compile(r"\b(?:S&P|Russell|FTSE|Nasdaq|Dow|CAC|DAX|Nikkei)\s*\d+\b", re.I),
    re.compile(r"\b\d+\s*-\s*(?:year|week|day|month|quarter|session)\b", re.I),
]

MAX_FIGURES_PER_SENTENCE = 3
MAX_WORDS_PER_SENTENCE = 36


def _figures(text: str) -> list[str]:
    for pat in _NAMING:
        text = pat.sub(" ", text)
    return _NUM.findall(text)


def density_report(text: str) -> dict:
    sents = [s for s in _SENT.split((text or "").strip()) if s.strip()]
    if not sents:
        return {"ok": True, "worst_figures": 0, "worst_words": 0, "why": ""}
    figs = [len(_figures(s)) for s in sents]
    words = [len(s.split()) for s in sents]
    wf, ww = max(figs), max(words)
    why = []
    if wf > MAX_FIGURES_PER_SENTENCE:
        why.append(f"{wf} figures in one sentence")
    if ww > MAX_WORDS_PER_SENTENCE:
        why.append(f"a {ww}-word sentence")
    return {"ok": not why, "worst_figures": wf, "worst_words": ww,
            "why": " and ".join(why)}


def too_dense(text: str) -> bool:
    return not density_report(text)["ok"]
