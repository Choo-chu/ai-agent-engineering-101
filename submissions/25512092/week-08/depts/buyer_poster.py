"""Buyer forum posts, one per 5-minute slot as soon as the slot opens (person's decision 11/07 ~17:10).

Before: depts/cs.run posted the buyer's line when restock ran (about once a minute, sometimes every 3-7 min), so posts
came 300-360 s apart (median 339 s; 240 a day of 288). The kit sends .market/outbox.jsonl every 10 s and keeps a post
the market refuses with 429 ('one post per 5 minutes') to try again, so a post written a little early leaves within
~10 s of the slot opening.

A thread in the analyst process (analyst_main.py) runs tick() every TICK_S:
  - a buyer post still in outbox.jsonl (or outbox.taking)   -> wait
  - it just left                                             -> that is the post time
  - EARLY_S before the next slot opens, write the next post, in this order:
      1. a one-off record (forum_once.json): prio 0 (approved callouts, relapses) first, then the rest (praise, ...)
      2. a market report, if REPORT_EVERY_S passed since the last one (about 20 a day; was about 78)
      3. a purchase record: my newest settle not posted yet (posted seqs kept, POSTED_KEEP)
      nothing to post -> the slot stays empty
  A callout approved while a purchase record already waits in the outbox (~10-20 s of each slot) goes one slot
  later: the waiting line is not pulled back (the kit may be taking the file at that moment: a double post).
State: logs/buyer_post_state.json (taken over once from cs's .market/forum_state.json: posted, once_done, report
cats). depts/cs.run no longer posts as the buyer (cs.BUYER_BY_POSTER). Heartbeat in the state file; restock's
alerts.watch warns when it is older than 15 min (no buyer posts then).
"""
import json
import os
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = os.path.join(HERE, ".market")
STATE = os.path.join(HERE, "logs", "buyer_post_state.json")
SLOT_S = 300
EARLY_S = 10
TICK_S = 5
REPORT_EVERY_S = 72 * 60
POSTED_KEEP = 3000


def _load():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
        try:                                            # take over cs's lists once, so nothing is posted twice
            old = json.load(open(os.path.join(MD, "forum_state.json"), encoding="utf-8"))
            st = {"posted": old.get("posted", []), "once_done": old.get("once_done", []),
                  "report_cats": old.get("report_cats", []), "last_post": old.get("buyer_ts", 0)}
        except (OSError, ValueError):
            pass
        st.setdefault("posted", [])
        st.setdefault("once_done", [])
        st.setdefault("report_cats", [])
        st.setdefault("last_post", 0)
        st.update(report_ts=0, pending=False, heartbeat=0, posts=0)
        return st


def _save(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE)


def _pending():
    """A buyer post still waiting for the kit (in outbox.jsonl, or in outbox.taking while the kit sends)."""
    for name in ("outbox.jsonl", "outbox.taking"):
        try:
            with open(os.path.join(MD, name), encoding="utf-8") as f:
                for ln in f:
                    if '"as": "buyer"' in ln and '"post"' in ln:
                        return True
        except OSError:
            continue
    return False


def _once(st):
    try:
        items = json.load(open(os.path.join(HERE, "forum_once.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    todo = [it for it in items if it.get("key") not in st["once_done"]]
    return min(todo, key=lambda it: it.get("prio", 1)) if todo else None


def next_post(st, now):
    """(kind, post) for the next slot, or (None, None)."""
    import sqlite3
    from depts import cs
    once = _once(st)
    if once:
        st["once_done"].append(once["key"])
        return f"once {once['key']}", {k: once[k] for k in ("post", "refs", "as", "thread") if k in once}
    catalog = json.load(open(os.path.join(MD, "catalog.json"), encoding="utf-8"))
    db = sqlite3.connect(cs.DB_PATH, timeout=30)
    try:
        if now - st.get("report_ts", 0) >= REPORT_EVERY_S:
            p = cs.market_report(db, catalog, st)
            if p:
                st["report_ts"] = now
                return "report", p
        p = cs.purchase_record(db, catalog, st)
        st["posted"] = st["posted"][-POSTED_KEEP:]
        if p:
            return "purchase", p
        db.commit()                                  # market_report keeps its picks in st; nothing else to write
    finally:
        db.close()
    return None, None


def tick(log=print):
    import decisions
    from depts import cs
    now = time.time()
    st = _load()
    st["heartbeat"] = now
    pend = _pending()
    if st.get("pending") and not pend:                # the waiting post just went out
        st["last_post"] = now
    st["pending"] = pend
    if not pend and now >= st["last_post"] + SLOT_S - EARLY_S:
        kind, p = next_post(st, now)
        if p:
            cs._send(MD, p)
            st["pending"] = True
            st["posts"] = st.get("posts", 0) + 1
            log(f"[buyer_poster] {kind}: {p['post'][:90]}")
            decisions.record("cs", "post", f"buyer {kind}", p["post"][:200],
                             "buyer poster: next 5-min slot, order once (prio) > report (every 72 min) > purchase")
    _save(st)


def loop(log=print):
    while True:
        try:
            tick(log)
        except Exception as e:
            log(f"[buyer_poster] {type(e).__name__}: {e}")
        time.sleep(TICK_S)
