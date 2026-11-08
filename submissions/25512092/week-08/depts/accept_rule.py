"""Buyer accept rule, a 24 h experiment (person's decision 11/08 ~14:10), switched by accept_rule.json (read per
order: market_buyer.py runs once per order, no restart).

Where my buyer would end a negotiation by itself (a walk, the time limit or the turn limit), it accepts the shop's
last ask instead when that ask is at most HIGH (95%) and at least LOW (50%) of the SKU's market average and within
the negotiation's budget (the cap: at most the order's budget and the market average). Decided by code, no LLM call.
Shop-ended negotiations, injection-flagged ones (the code finishes those) and asks under 50% of the average (often a
different unit or a mistyped price) keep the old way. The grade rules, the precheck and the receipt checks
(depts/buyer_biz.judge / refuse_receipt: price, item, budget mismatches are not paid) do not change.
  11/08 replay of the last 24 h: 81 accepts (+3.0M surplus), saved ~0.404 after a day; accepting the moment a counter
  qualified instead would have closed 296 of the deals I won lower at a higher price (saved ~0.391)
Every accept: decision accept_rule_95 and one line in logs/accept_rule.jsonl (tools/accept_watch.py reads them).
"""
import json
import os
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(HERE, "accept_rule.json")
LOG = os.path.join(HERE, "logs", "accept_rule.jsonl")
LOW, HIGH = 0.50, 0.95
TAG = "accept_rule_95"


def rules():
    try:
        with open(RULES, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def on(now=None):
    r, now = rules(), now or time.time()
    return bool(r.get("enabled")) and (r.get("since") or 0) <= now < (r.get("until") or 0)


def price(ask, budget, market_avg, injection=False, now=None):
    """The price to accept at instead of ending, or None."""
    if injection or ask is None or not market_avg or not on(now):
        return None
    if LOW * market_avg <= ask <= HIGH * market_avg and ask <= budget:
        return int(ask)
    return None


def log(**kw):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(ts=round(time.time(), 1), tag=TAG, **kw), ensure_ascii=False) + "\n")
    except OSError:
        pass
