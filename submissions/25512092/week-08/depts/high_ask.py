"""High-price first asks against the market average (person's decision 11/08 ~17:00), switched by high_ask.json
(read on every call; the seller hooks load at a restart).

  cap      a high-price unit (cost > qc.HIGH_MIN) never asks first above the market average (market_db.price_of, the
           same average the buyers' market shows); the floor does not change, so the ask is max(floor, min(ask, avg))
  clear    listed SKUs (G3e0d6c67, G53b150b5, bought 13:44-13:46 and unsold) ask first at share x the average
           (0.98); their floor is lowered to that ask when it is higher, never under the unit's cost
  buy      depts/purchasing: a high-price SKU whose expected first ask (the same floor / first-ask code on a unit at
           the expected cost, then the cap) is above the market average is not bought (decision high_price_above_avg)
"""
import json
import os
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(HERE, "high_ask.json")


def rules():
    try:
        with open(RULES, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _high(u):
    from depts.qc import HIGH_MIN
    return (u.get("cost") or 0) > HIGH_MIN


def floor(u, avg, reserve):
    """The floor for this unit: lowered for a cleared SKU to its clearance ask, never under cost."""
    r = rules()
    share = (r.get("clear") or {}).get(u.get("sku"))
    if not r.get("enabled") or share is None or not avg:
        return reserve
    return max(int(u["cost"]), min(reserve, int(avg * share)))


def first_ask(u, avg, reserve, ask):
    """(ask, why) after the cap / the clearance; why is None when nothing changed."""
    r = rules()
    if not r.get("enabled") or not avg or not _high(u):
        return ask, None
    share = (r.get("clear") or {}).get(u.get("sku"))
    if share is not None:
        new = max(int(u["cost"]), reserve, int(avg * share))
        return new, f"clear {share:.0%} of avg {int(avg):,}"
    if r.get("cap") and ask > avg:
        new = max(reserve, int(avg))
        return new, f"cap at avg {int(avg):,}" if new != ask else None
    return ask, None


def expected_first_ask(sku, c, cost, avg, case, now=None):
    """The first ask the seller would name for a unit of this SKU bought now at the expected cost (floor and first ask
    by depts/sales, then this module's cap); (ask, floor)."""
    import pricing
    now = now or time.time()
    u = {"sku": sku, "cost": int(cost), "list_price": c.get("list_price"), "kind": c.get("kind", "goods"),
         "grade": "A", "category": c.get("category"), "supplied_at": now, "expires_at": None, "name": c.get("name")}
    reserve, rule = pricing.floor(u, avg, case, now)
    ask = pricing.first_ask(u, avg, reserve, rule, {"key": None, "variant": None})
    ask, _ = first_ask(u, avg, reserve, ask)
    return ask, reserve


def buy_ok(sku, c, cost, avg, case):
    """(ok, ask, floor): False when the expected first ask is above the market average."""
    r = rules()
    if not r.get("enabled") or not r.get("buy_filter") or not avg:
        return True, None, None
    ask, reserve = expected_first_ask(sku, c, cost, avg, case)
    return ask <= avg, ask, reserve
