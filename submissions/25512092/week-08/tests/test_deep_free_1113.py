"""Deep SKUs out of high_max (person 11/13 ~15:40: held high 208 > high_max 120 blocked the fast ones too), through
purchasing.make_plan (what restock.main calls), plain and line_rank paths:
  deep_high.json outside_high_max on -> a deep SKU's units are not counted in high_max and its line fills up to the
  deep limit whatever the room; any other high SKU keeps the 120 room; off -> as before.
Live files untouched (temp rules, policy).
    python tests/test_deep_free_1113.py"""
import contextlib
import os
import sys
import time
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _isolate import policy, tmp_json, tmp_path  # noqa: E402

policy({"purchasing": {"high_max": 120, "high_share": 0.7}})
from depts import deep_high, purchasing as PU, top_high, wide_trial as W  # noqa: E402

NOW = time.time()
CAT = "가전>TV"
DEEP = {"H1": {"limit": 5, "sold": 6, "sold_12h": 5, "median_h": 1.0, "margin": 0.12, "name": "h1"}}


def catalog():
    return {k: {"name": k.lower(), "list_price": 1_000_000, "kind": "goods", "category": CAT} for k in ("H1", "H2")}


def stats():
    return {"skus": {k: {"name": k, "avg": 700_000, "n": 50, "sold_5m": 1, "sold_30m": 3} for k in ("H1", "H2")},
            "hot": ["H1", "H2"], "wanted": [], "wanted_cats": [], "sku_break": {}, "sku_n": {}}


def units(n_h1, n_other):
    return ([{"unit": f"h{i}", "sku": "H1", "cost": 600_000, "grade": "A", "supplied_at": NOW - 3600} for i in range(n_h1)]
            + [{"unit": f"o{i}", "sku": f"O{i}", "cost": 600_000, "grade": "A", "supplied_at": NOW - 3600}
               for i in range(n_other)])


def plan_with(on, us, rank=False):
    deep_high.RULES = tmp_json(dict(deep_high.rules(), enabled=True, outside_high_max=on), "deep_high")
    W.RULES, W.LINES = tmp_json({"enabled": False}, "wide_trial"), tmp_path(f"wt-{time.time_ns()}.jsonl")
    PU.HIGH_MARGIN = tmp_json({"enabled": True, "min_margin": 0.08}, "high_margin")
    cat, st = catalog(), stats()
    P = mock.patch.object
    noop = lambda *a, **k: None
    with contextlib.ExitStack() as es:
        for obj, name, val in (
                (top_high, "last_costs", lambda *a, **k: {}), (PU, "load_stats", lambda: st),
                (PU, "price_of", lambda k, s=None: (st["skus"][k]["avg"], 50)),
                (PU, "busy_categories", lambda c, top=5: ["TV"]), (PU, "c_rules", lambda: {}),
                (PU, "excluded", lambda: {}), (PU, "guard_check", lambda *a: None), (PU, "sofa_trial", lambda *a: None),
                (deep_high, "current", lambda **k: dict(DEEP)), (PU.decisions, "record", noop),
                (PU.strategy, "current", lambda: ("normal", None))):
            es.enter_context(P(obj, name, val))
        es.enter_context(mock.patch("depts.overcost.mark", lambda units, f, log=None: set()))
        es.enter_context(mock.patch("depts.request_buy.candidates", lambda *a, **k: []))
        es.enter_context(mock.patch("depts.hot_fast.shares", lambda hot, share, log=None: {}))
        es.enter_context(mock.patch("depts.high_cost_exclude.current", lambda **k: {}))
        es.enter_context(mock.patch("depts.line_rank.on", lambda *a: rank))
        es.enter_context(mock.patch("depts.line_rank.market_24h", lambda *a: {"H1": 20, "H2": 20}))
        es.enter_context(mock.patch("depts.normal_min.active", lambda *a, **k: None))
        es.enter_context(mock.patch("depts.high_ask.buy_ok", lambda *a: (True, 0, 0)))
        es.enter_context(mock.patch("alerts.send", noop))
        logs = []
        plan = PU.make_plan({"balance": 10 ** 9, "units": us}, us, cat, 10 ** 9, logs.append, record=False)
    return {p["sku"]: p["qty"] for p in plan}, logs


def test_full_room():
    for rank in (False, True):
        # 3 H1 + 130 other high held (133 > 120): H1 (deep, limit 5) still gets 2, H2 (not deep) nothing
        plan, logs = plan_with(True, units(3, 130), rank)
        assert plan.get("H1") == 2 and "H2" not in plan, (rank, plan, logs)
        assert any("high-price units 130/120" in m for m in logs), logs
        assert any("1 deep SKUs (3 high units held) out of high_max" in m for m in logs), logs
        # off: as before - the 133 held count, no room, nothing high
        plan, logs = plan_with(False, units(3, 130), rank)
        assert "H1" not in plan and "H2" not in plan, (rank, plan)
        assert any("high-price units 133/120" in m for m in logs), logs


def test_room_left():
    for rank in (False, True):
        # 1 room left (119 other): H2 takes it, H1's 2 do not use the room
        plan, logs = plan_with(True, units(3, 119), rank)
        assert plan.get("H1") == 2 and plan.get("H2") == 1, (rank, plan, logs)
        # at the deep limit: no more H1
        plan, _ = plan_with(True, units(5, 0), rank)
        assert "H1" not in plan and plan.get("H2") == 1, (rank, plan)


if __name__ == "__main__":
    test_full_room()
    test_room_left()
    print("ok")
