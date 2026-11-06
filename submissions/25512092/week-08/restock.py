"""Restock hook — the kit runs it every 60 s in Round 3:  python restock.py --state .market

1. Refreshes market.db / market_stats.json (at most once per 5 minutes, market_db.REFRESH_S).
2. Records the units my shop holds in market.db (my_stock: cost and the market average when they arrived).
3. Cash snapshot (market_db.record_cash), hourly/daily sales reports (sales_report.py), forum posts (forum_post.py).
4. Buys more of what sells fast across the market, only from cash above CUSHION, only while stock at cost is
   under MAX_STOCK_COST, never in the last 36 h of the round. Low-price SKUs (unit cost <= 100k) as before;
   high-price SKUs (100k-500k) in busy categories, one unit each, within the policy's share and unit cap.
Last line: {"buy": [{"sku": ..., "qty": ...}, ...]} (the kit buys at most 10 lines per run).
Departments (depts/): the plan is depts/purchasing.py; reports dept_reports.py; policy policy.json.
"""
import argparse
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import alerts  # noqa: E402
import decisions  # noqa: E402
import dept_reports  # noqa: E402
from depts import ceo_policy  # noqa: E402
import policy  # noqa: E402
import forum_post  # noqa: E402
import pricing  # noqa: E402
import strategy  # noqa: E402
import sales_report  # noqa: E402
from depts.purchasing import (CUSHION, MAX_STOCK_COST, SPEND_SHARE, busy_categories, cap_record,  # noqa: E402,F401
                              make_plan, my_sold_30m, spend_share)
from market_db import ME, connect, load_stats, price_of, record_cash, record_stock, refresh  # noqa: E402
from sales_report import HIGH_MAX, HIGH_MIN  # noqa: E402

# the plan itself (purchasing department) is depts/purchasing.py; this file is the minute scheduler


def log(msg):
    print(f"[restock] {msg}", flush=True)
    if " failed" in msg and not msg.startswith("market_db refresh"):     # refresh blips: qc's refresh-age check
        try:
            import alerts
            alerts.send("urgent", "restock:" + msg.split(" failed")[0][:40], msg[:300])
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=".market")
    state = ap.parse_args().state
    try:
        refresh(log=log)
    except Exception as e:
        log(f"market_db refresh failed: {e}")
    try:
        with open(os.path.join(state, "inventory.json"), encoding="utf-8") as f:
            inv = json.load(f)
        with open(os.path.join(state, "catalog.json"), encoding="utf-8") as f:
            catalog = json.load(f)
    except (OSError, ValueError) as e:
        log(f"no inventory/catalog yet: {e}")
        print(json.dumps({"buy": []}))
        return
    units = inv.get("units", [])
    try:
        record_stock(units, log=log)
    except Exception as e:
        log(f"record_stock failed: {e}")

    try:
        record_cash(inv, log=log)
    except Exception as e:
        log(f"record_cash failed: {e}")
    try:
        strategy.tick(inv, log=log)
    except Exception as e:
        log(f"strategy tick failed: {e}")
    try:
        sales_report.tick(inv, catalog, log=log)
    except Exception as e:
        log(f"sales report failed: {e}")
    try:
        forum_post.run(state, inv, catalog, log=log)
    except Exception as e:
        log(f"forum post failed: {e}")
    try:
        dept_reports.tick(inv, catalog, log=log)        # reports/dept/*.json every 5 min (read-only)
    except Exception as e:
        log(f"dept reports failed: {e}")
    try:
        ceo_policy.tick(inv, catalog, log=log)          # CEO: policy proposals (shadow) or policy.json (live)
    except Exception as e:
        log(f"ceo failed: {e}")
    try:
        alerts.watch(dept_reports.load(), log=log)     # urgent issues, kit restarts -> file, console, Telegram
    except Exception as e:
        print(f"[restock] alerts watch: {type(e).__name__}", flush=True)

    case = strategy.shop_case(inv)
    r = inv.get("restock") or {}
    now = time.time()
    soon = r.get("open") or (r.get("opens_at") or now) - now <= 60
    if case in ("cash_low", "overstock") or pricing.restock_stopped():
        if (inv.get("restock") or {}).get("open"):
            log(f"case {case}{', last 36 h' if pricing.restock_stopped() else ''}: no restock")
            decisions.record("purchasing", "no_restock", case, 0, f"shop case {case}"
                             + (", last 36 h" if pricing.restock_stopped() else ""), limit_hit={"overstock": "STOCK_CAP", "cash_low": "CASH_RESERVE"}.get(case, "RESTOCK_STOP_H"))
        if case == "overstock" and not pricing.restock_stopped() and soon:
            safe(cap_record, inv, units, catalog, 0, [], case)    # log only: what the cap kept from buying
        print(json.dumps({"buy": []}))
        return
    if not soon:
        print(json.dumps({"buy": []}))           # window not open soon: nothing to plan yet
        return

    held_cost = pricing.held_cost(inv)
    budget = min((inv.get("balance", 0) - CUSHION) * spend_share(), MAX_STOCK_COST - held_cost)
    if budget <= 0:
        log(f"cash {inv.get('balance', 0):,} leaves nothing above the {CUSHION:,} reserve: no restock")
        decisions.record("purchasing", "no_restock", case, 0, f"budget {int(budget):,}: cash "
                         f"{inv.get('balance', 0):,}, stock at cost {held_cost:,}", limit_hit="CASH_RESERVE/STOCK_CAP")
        safe(cap_record, inv, units, catalog, 0, [], case)
        print(json.dumps({"buy": []}))
        return
    lines = []

    def plan_log(m):
        log(m)
        lines.append(m)
    plan = make_plan(inv, units, catalog, budget, plan_log)
    for m in lines:                                  # one decision per planned / skipped / merged line
        kind = ("sofa_trial" if m.startswith("[sofa trial]") else "dedup" if m.startswith("[dedup]")
                else "skip" if m.endswith("-> skip") else "buy" if " -> buy " in m else None)
        if kind:
            decisions.record("purchasing", kind, m.split(":")[0][:60], m.rsplit("-> ", 1)[-1], m[:300])
    safe(cap_record, inv, units, catalog, budget, plan, case)
    print(json.dumps({"buy": plan}))


def safe(fn, *a):
    """Logging helpers must never cost the run its buy line."""
    try:
        fn(*a)
    except Exception as e:
        log(f"{fn.__name__} failed: {e}")


if __name__ == "__main__":
    main()
