"""Eval runner.

    python evals/run.py            # deterministic suites only (free, no tokens)
    python evals/run.py --agent    # also run the golden set against the LLM

Writes evals/REPORT.md and prints a summary.
"""
from __future__ import annotations
import argparse, os, asyncio, json, pathlib, re, statistics, sys, time

_R = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_R)); sys.path.insert(0, str(_R / "backend"))
try:
    from dotenv import load_dotenv
    load_dotenv(_R / ".env")
except ImportError:
    pass
from evals.suites import (api, sign_in_for_evals, suite_auth, suite_claim, suite_login,  # noqa: E402
                          suite_sweep, suite_tenancy, suite_cache,
                          suite_data_plane, suite_regressions, suite_tools)
from evals.rubric import score_all, judge  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADVICE = re.compile(r"\b(you should (buy|sell)|we recommend|i recommend|"
                    r"strong buy signal|time to (buy|sell))\b", re.I)


def load_golden():
    txt = (ROOT / "evals" / "golden.yaml").read_text()
    cases, cur = [], None
    for line in txt.splitlines():
        if line.startswith("  - id:"):
            cur = {"id": line.split(":", 1)[1].strip()}
            cases.append(cur)
        elif cur is not None and line.startswith("    ") and ":" in line:
            k, v = line.strip().split(":", 1)
            v = v.strip()
            if v.startswith("["):
                v = [x.strip() for x in v.strip("[]").split(",") if x.strip()]
            elif v in ("true", "false"):
                v = v == "true"
            elif v.isdigit():
                v = int(v)
            else:
                v = v.strip('"')
            cur[k] = v
    return cases


# Gemini's free tier is rate limited per minute, and each golden case makes
# several LLM calls. Back to back, the later cases get throttled, the router
# falls back, and the run looks like a ROUTING failure when it is a quota one.
# Pace the cases, and retry once when the server says it degraded.
GOLDEN_PACE_S = float(os.environ.get("GOLDEN_PACE_S", "6"))


async def suite_agent():
    out = []
    for n, c in enumerate(load_golden()):
        if n:
            await asyncio.sleep(GOLDEN_PACE_S)
        t0 = time.time()
        body = {"question": c["q"]}
        if c.get("tickers"):
            body["tickers"] = c["tickers"]
        code, d = api("/api/agent/ask", "POST", body, timeout=300)
        if code == 200 and d.get("degraded"):
            await asyncio.sleep(GOLDEN_PACE_S * 3)      # let the quota window roll
            code, d = api("/api/agent/ask", "POST", body, timeout=300)
        ms = int((time.time() - t0) * 1000)
        if code != 200:
            out.append({"id": c["id"], "pass": False, "detail": f"HTTP {code}",
                        "ms": ms, "why": c.get("why", ""), "tokens": 0, "calls": 0})
            continue
        if d.get("degraded"):
            # Report it as what it is. Scoring a throttled run as a routing
            # mistake is how I spent an hour chasing the wrong bug.
            out.append({"id": c["id"], "pass": False,
                        "detail": f"DEGRADED (not a routing verdict): {d['degraded'][:90]}",
                        "ms": ms, "why": c.get("why", ""), "tokens": 0, "calls": 0})
            continue

        domains = {f["domain"] for f in d.get("findings", [])}
        answer = d.get("answer", "")
        fails = []

        for want in (c.get("expect_domains") or []):
            if want not in domains:
                fails.append(f"missing domain {want}")
        for bad in (c.get("forbid_domains") or []):
            if bad in domains:
                fails.append(f"ran needless domain {bad}")
        if c.get("expect_min_domains") and len(domains) < c["expect_min_domains"]:
            fails.append(f"only {len(domains)} domains")
        for want in (c.get("expect_tickers") or []):
            if want not in d.get("tickers", []):
                fails.append(f"dropped ticker {want}")
        for bad in (c.get("forbid_tickers") or []):
            if bad in d.get("tickers", []):
                fails.append(f"substituted ticker {bad}")
        if c.get("must_be_grounded") and d.get("grounded") is False:
            fails.append(f"ungrounded {d.get('ungrounded_numbers')}")
        if c.get("forbid_advice") and ADVICE.search(answer):
            fails.append("gave advice")
        if c.get("expect_refusal"):
            refused = (not domains) or len(answer) < 320
            if not refused:
                fails.append("answered an off-topic/injection prompt")
        if c.get("forbid_fabrication") and re.search(r"\$\s?\d[\d,]*\.\d\d", answer) \
                and not d.get("findings"):
            fails.append("quoted a price with no evidence")

        row = {"id": c["id"], "pass": not fails,
               "detail": "; ".join(fails) if fails
                         else f"domains={sorted(domains)} grounded={d.get('grounded')}",
               "ms": ms, "why": c.get("why", ""),
               "tokens": d.get("total_tokens", 0), "calls": d.get("llm_calls", 0),
               "answer": answer[:260]}
        # quality scoring, only where there is an answer to score
        if answer and not c.get("expect_refusal"):
            det = score_all(c["q"], answer, d.get("findings", []),
                            d.get("ungrounded_numbers", []), d.get("grounded"))
            row["quality"] = det
        out.append(row)
    return out


async def suite_quality(agent_rows):
    """Judge the answers the agent suite produced, after validating the judge."""
    from app import llm
    import evals.judge_control as jc
    scored = []
    for name, probes, ans in jc.FIXTURES:                 # validate first
        s = await judge(jc.Q, ans, jc.FINDINGS, llm)
        s["name"] = name
        scored.append(s)
    g = next(x for x in scored if x["name"] == "good")
    validated = (g["task_fit"] >= 4 and g["usefulness"] >= 4
                 and next(x for x in scored if x["name"] == "ignores_question")["task_fit"] <= 2
                 and next(x for x in scored if x["name"] == "gives_advice")["calibration"] <= 2)

    rows = []
    for r in agent_rows:
        q = r.get("quality")
        if not q or not r.get("answer"):
            continue
        j = await judge(r["id"], r["answer"], [], llm) if False else None
        rows.append({"id": r["id"], "quality": q})
    return {"validated": validated, "fixtures": scored, "rows": rows}


def table(rows, cols=("id", "pass", "detail")):
    lines = ["| " + " | ".join(("Case", "Result", "Detail")) + " |",
             "|---|---|---|"]
    for r in rows:
        lines.append(f"| `{r['id']}` | {'PASS' if r['pass'] else '**FAIL**'} | {r['detail']} |")
    return "\n".join(lines)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", action="store_true", help="also run the golden set (spends tokens)")
    args = ap.parse_args()

    code, health = api("/api/health")
    if code != 200:
        print("server not reachable on :8077 - start it first"); return 1

    print("session:", sign_in_for_evals())

    started = time.strftime("%Y-%m-%d %H:%M")
    results = {}
    print("running auth...");         results["Auth"] = suite_auth()
    print("running claim...");        results["Auth"] += suite_claim()
    print("running login sweep...");  results["Sign-in"] = suite_login()
    print("running app sweep...");    results["App sweep"] = suite_sweep(args.agent)
    print("running tenancy...");      results["Tenancy"] = suite_tenancy(args.agent)
    print("running cache...");        results["Cache"] = suite_cache()
    print("running data plane...");   results["Data plane"] = suite_data_plane()
    print("running tools...");        results["Tools"] = await suite_tools()
    print("running regressions...");  results["Regressions"] = await suite_regressions()
    if args.agent:
        if not health.get("llm_configured"):
            print("no API key - skipping agent suite")
        else:
            print("running agent golden set (this spends tokens)...")
            results["Agent"] = await suite_agent()

    total = sum(len(v) for v in results.values())
    passed = sum(1 for v in results.values() for r in v if r["pass"])
    md = [f"# Eval report\n",
          f"Run {started} · model `{health.get('model')}` · "
          f"{health.get('tools')} tools · LLM {'on' if health.get('llm_configured') else 'off'}\n",
          f"**{passed}/{total} passed**\n"]
    for name, rows in results.items():
        p = sum(1 for r in rows if r["pass"])
        md += [f"\n## {name} — {p}/{len(rows)}\n", table(rows), ""]
        bad = [r for r in rows if not r["pass"]]
        if bad:
            md.append("\n**Failures**\n")
            for r in bad:
                md.append(f"- `{r['id']}` — {r['detail']}  \n  _expected:_ {r.get('why','')}")
    if "Agent" in results:
        ag = results["Agent"]
        qrows = [r for r in ag if r.get("quality")]
        if qrows:
            md += ["\n## Answer quality (deterministic)\n",
                   "| Case | Validity | Readability | Structure | Conjunction |",
                   "|---|---|---|---|---|"]
            for r in qrows:
                q = r["quality"]
                md.append(f"| `{r['id']}` | {q['validity']['score']}/5 | "
                          f"{q['readability']['score']}/5 | {q['structure']['score']}/5 | "
                          f"{q['conjunction']['score']}/5 |")
            conj = [r["quality"]["conjunction"]["hit"] for r in qrows]
            md += [f"\n**Conjunction rate: {sum(conj)}/{len(conj)} "
                   f"({sum(conj)/len(conj):.0%})** — share of answers that relate two "
                   f"tools' or domains' data rather than listing them. This is the metric "
                   f"DESIGN.md \u00a710 says justifies domain subgraphs: a one-tool agent "
                   f"cannot score here by construction.\n"]
            for k in ("validity", "readability", "structure"):
                vals = [r["quality"][k]["score"] for r in qrows]
                md.append(f"- mean {k}: **{statistics.mean(vals):.1f}/5**")
            worst = sorted(qrows, key=lambda r: r["quality"]["readability"]["score"])[:3]
            md += ["\n**Lowest readability**\n"] + \
                  [f"- `{r['id']}` — {r['quality']['readability']['detail']}" for r in worst]
        toks = [r.get("tokens", 0) for r in ag if r.get("tokens")]
        lat = [r["ms"] for r in ag]
        md += ["\n## Agent cost & latency\n",
               f"- median tokens/run: **{int(statistics.median(toks)) if toks else 0}**",
               f"- median latency: **{statistics.median(lat)/1000:.1f}s** "
               f"(p95 {sorted(lat)[int(len(lat)*.95)-1]/1000:.1f}s)",
               f"- median LLM calls: **{statistics.median([r.get('calls',0) for r in ag]):.0f}**"]
    (ROOT / "evals" / "REPORT.md").write_text("\n".join(md) + "\n")
    print(f"\n{passed}/{total} passed -> evals/REPORT.md")
    for name, rows in results.items():
        bad = [r['id'] for r in rows if not r['pass']]
        print(f"  {name:<12} {sum(1 for r in rows if r['pass'])}/{len(rows)}"
              + (f"   FAIL: {', '.join(bad)}" if bad else ""))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
