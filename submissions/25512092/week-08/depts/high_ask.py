"""High-price first asks against the market average (person's decision 11/08 ~17:00), switched by high_ask.json
(read on every call; the seller hooks load at a restart).

  cap      a high-price unit (cost > qc.HIGH_MIN) never asks first above the market average (market_db.price_of, the
           same average the buyers' market shows); the floor does not change, so the ask is max(floor, min(ask, avg))
  clear    listed SKUs (G3e0d6c67, G53b150b5, bought 13:44-13:46 and unsold) ask first at share x the average
           (0.98); their floor is lowered to that ask when it is higher, never under the unit's cost
  floor    (person's decision 11/08 ~17:30, ~17:40: on from the 20:02 check: high_ask.json floor_rule.enabled) a
           high-price unit's floor is max(cost x 1.05, the 48 h market median (depts/sofa.market) x 0.80); without a
           market median: cost x 1.05. Sofas keep their own rules (depts/sofa.applies), the endgame keeps its markdown,
           and a floor computed by an old markdown (aging, stoploss, food clearance, endgame, cash_low, overstock)
           that is lower than the new floor stays (one principle, 11/08 ~17:50). The first-ask cap above stays (the ask is never under the floor)
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


def _sofa(u):
    from depts import sofa
    return sofa.applies(u)


def _high(u):
    from depts.qc import HIGH_MIN
    return (u.get("cost") or 0) > HIGH_MIN


def high_floor(u, now=None, fr=None):
    """max(cost x 1.05, market median x 0.80) for a high-price unit."""
    fr = fr if fr is not None else (rules().get("floor_rule") or {})
    from depts import sofa
    med = sofa.market(u["sku"], now)[0]
    return max(int(u["cost"] * fr.get("cost", 1.05)), int(med * fr.get("median", 0.80)) if med else 0)


MARKDOWNS = ("aging", "stoploss", "clearance", "endgame", "cash_low", "overstock")   # the old markdowns (depts/sales
#   floor rule names); 11/08 ~17:50 (person): one principle, a markdown floor lower than the new floor is kept


def floor(u, avg, reserve, case=None, now=None, rule=None):
    """The floor for this unit: the high-price floor rule when on (not sofas, not in the endgame; a markdown floor
    (rule in MARKDOWNS) is kept when lower); then a cleared SKU's floor is lowered to its
    clearance ask, never under cost."""
    r = rules()
    if not r.get("enabled"):
        return reserve
    fr = r.get("floor_rule") or {}
    if fr.get("enabled") and _high(u) and case != "endgame" and not _sofa(u):
        new = high_floor(u, now, fr)
        reserve = min(reserve, new) if str(rule or "").startswith(MARKDOWNS) else new
    share = (r.get("clear") or {}).get(u.get("sku"))
    if share is None or not avg:
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
    reserve = floor(u, avg, reserve, case, now, rule)
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
