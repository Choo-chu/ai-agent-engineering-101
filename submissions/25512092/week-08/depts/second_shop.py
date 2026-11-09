"""second_shop, plan D (person's decision 11/09 ~17:40; on at the 20:27 soft_neg check only if soft_neg went to 100%):
a soft_neg order that ended at its first shop on price (walk / turn limit), no stock or the shop ending it, with at
least 2 shops in stock, tries the next candidate shop once, the soft_neg way again (first offer 75% of the market
average, accept an ask <= the average, at most 2 offers, no LLM) - only if the try fits under the market's ~20 s
order spacing: elapsed in the buyer + TRY_S + PRE_S (kit before the buyer) + POST_S (result and ledger) <= FLOOR_S.
Switched by second_shop.json (read per order); tools/saved_guard_watch.py switches it off when my saved < the 2nd
best saved + 0.015 (depts/saved_guard.py). Tag second_shop (buyer_deals case, soft_neg.jsonl field).
  11/09 analysis (tools/order_speed2.py): one soft try 8.9 s; 57% of the soft orders qualify, ~75% of those fit
"""
import json
import os
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(HERE, "second_shop.json")
TAG = "second_shop"
FLOOR_S, TRY_S, PRE_S, POST_S = 20.0, 9.0, 1.5, 2.5
ENDS = {"walk", "turn_limit", "seller_ended"}       # price, or the shop ended it (no stock is a shop-ended reply)


def rules():
    try:
        with open(RULES, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def on(r=None, now=None):
    r = rules() if r is None else r
    return bool(r.get("enabled")) and (r.get("since") or 0) <= (now or time.time())


def qualifies(res):
    """The first shop's result is one D retries: no deal, ended on price / no stock / by the shop."""
    return (not res.get("deal") and not res.get("error") and not res.get("skip") and not res.get("injection")
            and res.get("ended") in ENDS)


def fits(elapsed, r=None):
    r = rules() if r is None else r
    return elapsed + r.get("try_s", TRY_S) + r.get("pre_s", PRE_S) + r.get("post_s", POST_S) <= r.get("floor_s", FLOOR_S)
