"""Market research collector for choo-chu (Round 4). Read-only: public market APIs, the chain RPC, and the agent's
own logs. It never reads key files or tokens and never writes outside analysis/data/.

    python analysis/collector.py            every 10 minutes until Ctrl-C
    python analysis/collector.py --once     one pass, then exit

Writes analysis/data/<endpoint>-YYYYMMDD.jsonl (ledger, forum, demand, village, inventory),
analysis/data/inquiries.jsonl, analysis/data/collector_status.txt (last successful pass) and
analysis/data/collector_state.json (where each source was read up to).
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

MARKET = "https://market.ourolabs.ai"
RPC = "https://rpc-testnet.maroo.io"
SHOP = "choo-chu"
WALLET = "0x943805646864aa174e90c330b795019b16E1D262"
CREDIT_WEI = 10 ** 15
EVERY = 600
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # submissions/25512092/round-4
DATA = HERE / "data"
STATE = DATA / "collector_state.json"
UA = {"user-agent": "Mozilla/5.0 (compatible; market-research)"}


def get(path):
    req = urllib.request.Request(MARKET + path, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers=dict(UA, **{"content-type": "application/json"}))
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["result"]


def day_file(name):
    return DATA / f"{name}-{time.strftime('%Y%m%d')}.jsonl"


def append(path, rows):
    if not rows:
        return 0
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def collect_ledger(st, now):
    """New ledger entries since the last seq (deduplicated by seq). Returns all entries read, for the stock summary."""
    after, new = int(st.get("ledger_seq", 0)), []
    while True:
        page = get(f"/api/ledger?after={after}")
        if not page:
            break
        new += page
        after = page[-1]["seq"]
        if len(page) < 500:
            break
    append(day_file("ledger"), [dict(e, collected=now) for e in new])
    st["ledger_seq"] = after
    return new


def collect_forum(st, now):
    seen = set(st.get("forum_ids", []))
    posts = [p for p in get("/api/forum") if p.get("id") not in seen]
    append(day_file("forum"), [dict(p, collected=now) for p in posts])
    st["forum_ids"] = sorted(seen | {p.get("id") for p in posts})[-5000:]


def collect_snapshot(name, path, now):
    append(day_file(name), [{"ts": now, name: get(path)}])


def collect_inventory(st, new_ledger, now):
    """Our stock from the public ledger (units supplied to us minus units settled) and the wallet balance."""
    held = st.setdefault("our_units", {})                  # unit -> sku
    for e in new_ledger:
        d = e.get("data") or {}
        if e.get("kind") == "supply" and d.get("shop") == SHOP:
            for u in d.get("units") or []:
                held[u] = d.get("sku")
        if e.get("kind") == "settle" and d.get("unit") in held:
            held.pop(d["unit"], None)
            st["our_settles"] = st.get("our_settles", 0) + 1
    by_sku = {}
    for sku in held.values():
        by_sku[sku] = by_sku.get(sku, 0) + 1
    row = {"ts": now, "units": len(held), "skus": by_sku, "settles": st.get("our_settles", 0)}
    try:
        row["balance_credits"] = int(rpc("eth_getBalance", [WALLET, "latest"]), 16) // CREDIT_WEI
    except Exception as e:
        row["balance_error"] = type(e).__name__
    append(day_file("inventory"), [row])


def read_new_lines(path, st, key):
    """Lines appended to a log since the last pass (byte offset kept in the state)."""
    if not path.exists():
        return []
    size, pos = path.stat().st_size, int(st.get(key, 0))
    if pos > size:
        pos = 0
    with open(path, "rb") as f:
        f.seek(pos)
        chunk = f.read()
    end = chunk.rfind(b"\n") + 1                           # leave a half-written last line for next time
    st[key] = pos + end
    out = []
    for line in chunk[:end].decode("utf-8", "replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def short(x, n=300):
    return str(x or "")[:n]


def collect_inquiries(st, now):
    rows = []
    for d in read_new_lines(ROOT / "logs" / "react.jsonl", st, "react_pos"):
        a, act, obs = d.get("args") or {}, d.get("action"), short(d.get("observation"), 500)
        base = {"ts": d.get("ts"), "collected": now, "source": "react", "kind": act}
        if act == "reply":
            rows.append(dict(base, msg_id=a.get("to"), our_reply=short(a.get("text")), state=a.get("state"),
                             sent=obs.startswith("sent"), has_checkout="checkout_jwt" in json.dumps(a.get("data") or {}),
                             thought=short(d.get("thought"), 200)))
        elif act == "offer":
            rows.append(dict(base, customer=a.get("customer_key"), sku=a.get("sku"), price=a.get("price"),
                             offer_ok='"ok": true, "sku"' in obs, result=obs))
        elif act in ("ledger_log", "shop_handler"):
            rows.append(dict(base, customer=a.get("customer") or a.get("claimed_from"),
                             message=short(a.get("message") or a.get("text")), result=obs))
        elif act in ("stock", "sku_lookup"):
            rows.append(dict(base, query=a.get("query") or a.get("skus"), result=obs))
    for d in read_new_lines(ROOT / "ledger.jsonl", st, "ledger_pos"):
        if d.get("result") == "checkout_issued":
            rows.append({"ts": d.get("ts"), "collected": now, "source": "handler", "kind": "checkout_issued",
                         "customer": d.get("customer_key") or d.get("customer"), "sku": d.get("sku"),
                         "unit": d.get("unit"), "price": d.get("price") or d.get("final_price")})
    append(DATA / "inquiries.jsonl", rows)


def one_pass():
    DATA.mkdir(parents=True, exist_ok=True)
    st, now, ok = load_state(), int(time.time()), []
    new_ledger = []
    steps = [
        ("ledger", lambda: new_ledger.extend(collect_ledger(st, now))),
        ("forum", lambda: collect_forum(st, now)),
        ("demand", lambda: collect_snapshot("demand", "/api/demand", now)),
        ("village", lambda: collect_snapshot("village", "/api/village", now)),
        ("inventory", lambda: collect_inventory(st, new_ledger, now)),
        ("inquiries", lambda: collect_inquiries(st, now)),
    ]
    for name, step in steps:
        try:
            step()
            ok.append(name)
        except Exception as e:                             # one source failing never stops the others
            print(time.strftime("%H:%M:%S"), f"{name} failed: {type(e).__name__}: {short(e, 160)}", flush=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    if ok:
        (DATA / "collector_status.txt").write_text(
            time.strftime("%Y-%m-%d %H:%M:%S") + " ok: " + ", ".join(ok) + "\n", encoding="utf-8")
    print(time.strftime("%H:%M:%S"), "pass done:", ", ".join(ok), flush=True)


def main():
    while True:
        try:
            one_pass()
        except Exception as e:
            print(time.strftime("%H:%M:%S"), f"pass failed: {type(e).__name__}", flush=True)
        if "--once" in sys.argv:
            return
        time.sleep(EVERY)


if __name__ == "__main__":
    main()
