#!/usr/bin/env python3
"""Latency and format check of claude_shim.py through the kit's own client (agent_kit.Model.complete).

    python shim/bench.py                     4 configs (sonnet/haiku x prewarm on/off), 10 calls each
    python shim/bench.py --calls 3 --configs haiku:2

Each config starts its own shim, then plays one run the way Mind.run_once does: the kit's WORLD + FORMAT as the
system message, a context like Mind.context as the first user message, and after each answer a canned observation,
so the prompt grows turn by turn. Writes shim/bench_results.md.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUND = HERE.parent
REPO = ROUND.parents[2]
sys.path.insert(0, str(REPO / "scripts" / "round4"))
import agent_kit  # noqa: E402

GAP = 3.0           # seconds between calls, standing in for the kit running the move


def context():
    agent = json.loads((ROUND / "agent.json").read_text(encoding="utf-8"))
    ents = [("orders", "Order desk"), ("clearing", "Clearing house"), ("wholesale", "Wholesale market"),
            ("forum", "Forum"), ("board", "Scoreboard"), ("bank", "Maroo bank")]
    book = {"directory_card": "https://market.ourolabs.ai/.well-known/agent-card.json",
            "entities": [{"id": i, "name": n, "card": f"https://market.ourolabs.ai/entities/{i}/.well-known/agent-card.json"}
                         for i, n in ents],
            "conventions": {"signatures": "EIP-191 personal message over canonical JSON, base64",
                            "jwt": "alg EIP191, header.payload.signature base64url", "tokens": "Bearer, from joining"},
            "documentation": "https://github.com/Q00/agent-market/blob/main/market/ROUND4.md"}
    notes = (ROUND / "notes.md").read_text(encoding="utf-8")[-3000:]
    parts = ['You are bench-shop, one agent with these market roles: {"shop": {"wallet": "0x' + "1" * 40 + '"}, '
             '"buyer": {"wallet": "0x' + "2" * 40 + '"}}. Your Agent Card: https://bench.trycloudflare.com/.well-known/'
             'agent-card.json; any agent (shop or buyer) may write to you there, and you may write to any agent that lists a card.',
             f"Market: https://market.ourolabs.ai. Time now: {time.strftime('%Y-%m-%d %H:%M:%S')} ({int(time.time())}).",
             f"Your goal: {agent['goal']}", f"Your personality: {agent['persona']}",
             "Your Agent Card is what the kit serves from card.json in your directory (a tool with permission.write "
             "[card.json] can write it; the kit fills in the URL, your roles and wallets). Until you write it, others see a bare card.",
             "The market's entities (read their cards, then build the tools you need):\n" + json.dumps(book, ensure_ascii=False),
             "Your tools:\n(none yet)",
             "Tools your app gives you (they run in the app; you cannot change them):\n"
             "- app_show_card: show the person a card in the chat; args {title, body} (runs in the app's page)\n"
             "- app_owner_memo: The shop owner's current instructions and strategy memo. Check it before pricing or buying. (runs in the app's page)",
             "Your notes:\n" + notes]
    return "\n\n".join(parts)


OBS = [
    '{"memo": "1단계: 박리다매. 원가+수수료+5% 밑으로는 팔지 말 것. 식품은 유통기한 짧은 것부터.", "updated_at": "2026-11-24T19:05:00Z"}',
    "error: no tool 'http_get'. Fixed moves: forge_tool, read_tool, reply, write_note, sleep. Your tools: app_show_card, app_owner_memo",
    'forged read_card v1: test passed (0.4 s)',
    json.dumps({"name": "Wholesale market", "skills": [{"id": "catalog", "http": {"method": "GET", "path": "/api/catalog",
                "auth": None, "returns": "[{sku, name, category, list_price, kind}]"}}, {"id": "supply", "http": {
                "method": "POST", "path": "/api/supply", "auth": "shop token", "body": {"sku": "str", "qty": "1..20"},
                "returns": "units with certificates, or 429 {wait, opens_at, closes_at}"}}, {"id": "inventory", "http": {
                "method": "GET", "path": "/api/inventory", "auth": "shop token", "returns": "{balance, start, units, restock}"}}]},
               ensure_ascii=False),
    'forged market_get v1: test passed (0.6 s)',
    json.dumps({"balance": 5000000, "start": 5000000, "units": [], "restock": {"open": True, "opens_at": 1795000000,
                "closes_at": 1795000600}}),
    json.dumps([{"sku": f"s{i:03d}", "name": n, "category": c, "list_price": p, "kind": k} for i, (n, c, p, k) in enumerate([
        ("두부 300g", "식품>신선>두부", 2400, "food"), ("우유 1L", "식품>유제품>우유", 2900, "food"),
        ("햇반 210g x6", "식품>즉석>밥", 7800, "food"), ("물티슈 100매", "생활>위생>물티슈", 3500, "goods"),
        ("주방세제 1L", "생활>주방>세제", 6900, "goods"), ("텀블러 500ml", "생활>주방>컵", 18900, "goods")])], ensure_ascii=False),
    "error: test failed: AssertionError: run() returned None, expected a dict with 'units'",
    'forged restock_rule v1: test passed (1.1 s)',
    "saved",
]


def wait_up(port, secs=20):
    end = time.time() + secs
    while time.time() < end:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).read()
            return True
        except OSError:
            time.sleep(0.3)
    return False


def strict_ok(raw):
    try:
        obj = json.loads(raw.strip())
    except ValueError:
        return False
    return isinstance(obj, dict) and {"thought", "action", "args"} <= set(obj)


def bench(model, pool, calls, port):
    env = dict(os.environ, SHIM_MODEL=model, SHIM_POOL=str(pool), SHIM_PORT=str(port))
    shim = subprocess.Popen([sys.executable, str(HERE / "claude_shim.py")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rows = []
    try:
        if not wait_up(port):
            raise SystemExit("shim did not start")
        m = agent_kit.Model({"llm": {"base": f"http://127.0.0.1:{port}/v1", "model": "claude-shim", "key_env": "NONE"}})
        system = f"{agent_kit.WORLD}\n\n{agent_kit.FORMAT}"
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": context()}]
        if pool:
            # prime the pool for this system prompt (the kit's system prompt never changes), as the first run would
            m.complete(msgs[:1] + [{"role": "user", "content": 'Answer {"thought": "ready", "action": "sleep", "args": {"seconds": 30}}'}])
            time.sleep(8)
        for i in range(calls):
            chars = sum(len(x["content"]) for x in msgs)
            t0 = time.time()
            try:
                raw = m.complete(msgs)
                err = None
            except Exception as e:
                raw, err = "", f"{type(e).__name__}: {e}"
            dt = time.time() - t0
            move = agent_kit.parse(raw) if raw else None
            rows.append({"i": i, "s": round(dt, 2), "chars": chars, "strict": strict_ok(raw), "parsed": move is not None,
                         "action": (move or {}).get("action"), "err": err, "out_chars": len(raw)})
            print(model, pool, rows[-1], flush=True)
            msgs.append({"role": "assistant", "content": raw or "{}"})
            msgs.append({"role": "user", "content": "Observation: " + OBS[i % len(OBS)]})
            time.sleep(GAP)
    finally:
        shim.terminate()
        try:
            shim.wait(10)
        except subprocess.TimeoutExpired:
            shim.kill()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=int, default=10)
    ap.add_argument("--configs", default="sonnet:2,sonnet:0,haiku:2,haiku:0")
    a = ap.parse_args()
    results, port = [], 8911
    for c in a.configs.split(","):
        model, pool = c.split(":")
        rows = bench(model, int(pool), a.calls, port)
        port += 1
        results.append((model, int(pool), rows))
    lines = ["# claude -p shim benchmark", "", f"{time.strftime('%Y-%m-%d %H:%M')}, {a.calls} calls per config through "
             "agent_kit.Model.complete, kit WORLD+FORMAT system prompt, prompt growing turn by turn, "
             f"{GAP:.0f} s between calls.", "",
             "| model | prewarm | mean s | median s | max s | strict JSON | kit parse | errors | prompt chars (first-last) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for model, pool, rows in results:
        ok = [r["s"] for r in rows if not r["err"]]
        lines.append(f"| {model} | {'on (' + str(pool) + ')' if pool else 'off'} | "
                     f"{statistics.mean(ok):.1f} | {statistics.median(ok):.1f} | {max(ok):.1f} | "
                     f"{sum(r['strict'] for r in rows)}/{len(rows)} | {sum(r['parsed'] for r in rows)}/{len(rows)} | "
                     f"{sum(bool(r['err']) for r in rows)} | {rows[0]['chars']:,}-{rows[-1]['chars']:,} |" if ok else
                     f"| {model} | {pool} | - | - | - | - | - | {len(rows)} | |")
    lines += ["", "Per call:", "", "```"]
    for model, pool, rows in results:
        for r in rows:
            lines.append(f"{model:6} pool={pool} #{r['i']} {r['s']:6.2f}s chars={r['chars']:6} strict={r['strict']!s:5} "
                         f"parsed={r['parsed']!s:5} action={r['action']} out={r['out_chars']} {r['err'] or ''}")
    lines.append("```")
    (HERE / "bench_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:10 + len(results)]))


if __name__ == "__main__":
    main()
