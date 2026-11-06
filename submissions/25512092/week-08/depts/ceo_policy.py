"""CEO: reads the department reports and sets the policy (policy.json). Rule-based; no LLM.

Runs from restock.py every RUN_EVERY_S. Mode (ceo_state.json):
  shadow  proposals are logged (decisions.jsonl, action shadow_policy) and nothing is applied
  live    proposals are written to policy.json (a new version with the reason)

Keys the CEO may set (step 7 opens only these):
  purchasing.high_share / high_max   once a day, the buying-split rule that sales_report.daily used:
        high-price units unsold > 24 h or a high-price refund -> share -10 %p (min 20%)
        else high-price profit/cost >= low-price profit/cost -> share +10 %p (max 50%), units held +1 (max 5)
  purchasing.spend_share             stock within 10% of STOCK_CAP -> no change (the cap binds anyway);
        cash < 2.5M -> 0.3; 6 h profit > 0, stock < half the cap, cash > 3M -> 0.5; else 0.4
  purchasing.perishable_trial_qty    perishable units wasted in 24 h -> 1, else 2
A key changes at most once every KEY_HOLD_S (the daily rule once a day). Hard limits are not policy keys.

Guard (live only, hourly after GUARD_MIN_H): the live window against the same hours a day earlier. Shop profit
or sales down 30% or more, stars (one mean per reviewing account, Patch 3.4) down 0.4 or more, or the buyer's
Saved (Patch 3.4) down: sum of shares kept down 30% or more, or share kept per deal down 5 %p or more (each with
enough data) -> policy.reset() (back to the version-1 values), mode shadow, urgent alert.
"""
import json
import os
import time
from datetime import datetime

import alerts
import decisions
import dept_reports
import policy
from limits import STOCK_CAP
from market_db import ME, connect

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(HERE, "ceo_state.json")
RUN_EVERY_S = 1800
KEY_HOLD_S = 3 * 3600
GUARD_EVERY_S = 3600
GUARD_MIN_H = 3
HIGH_MIN = 100_000
LIVE_KEYS = ("purchasing.high_share", "purchasing.high_max", "purchasing.spend_share",
             "purchasing.perishable_trial_qty")


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"mode": "shadow", "shadow_since": time.time(), "live_since": None, "auto_live_at": None,
                "runs": 0, "errors": 0, "last_run": 0, "last_guard": 0, "key_ts": {}, "split_day": None}


def save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def current_split(before=None):
    """The buying split in force: the CEO's policy keys when set, else the policy table (sales_report.daily's
    rule) as it stood before `before` (the daily rule adjusts the table at midnight; the CEO's daily rule starts
    from the value before that adjustment, so the two never apply the same step twice)."""
    import sales_report
    pol = sales_report.policy()
    if before is not None:
        db = connect()
        try:
            row = db.execute("SELECT high_share, high_max FROM policy WHERE ts<? ORDER BY ts DESC LIMIT 1",
                             (before,)).fetchone()
        finally:
            db.close()
        if row:
            pol = {"high_share": row[0], "high_max": row[1]}
    for k in ("high_share", "high_max"):
        if (policy.load().get("purchasing") or {}).get(k) is not None:
            pol[k] = policy.get("purchasing", k)
    return pol


def split_rule(inv, catalog, now):
    """The daily buying-split rule over yesterday (same as sales_report.daily)."""
    import sales_report
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    t1 = today.timestamp()
    t0 = t1 - 86400
    db = connect()
    try:
        s = sales_report.summarize(sales_report.my_sales(db, t0, t1), catalog)
        refunds = db.execute("""SELECT COUNT(*) FROM broken b LEFT JOIN settles s ON s.sku=b.sku AND s.buyer=b.buyer
                                AND s.shop=? LEFT JOIN my_stock m ON m.unit=s.unit
                                WHERE b.shop=? AND b.ts>=? AND b.ts<? AND b.refunded=1 AND m.cost>?""",
                             (ME, ME, t0, t1, HIGH_MIN)).fetchone()[0]
    finally:
        db.close()
    stale = [u for u in inv.get("units", []) if u.get("grade") != "expired" and u.get("cost", 0) > HIGH_MIN
             and now - (u.get("supplied_at") or now) > 24 * 3600]
    lr = sales_report.rate(s["low_profit"], s["low_cost"])
    hr = sales_report.rate(s["high_profit"], s["high_cost"])
    cur = current_split(before=t1)
    share, cap = cur["high_share"], cur["high_max"]
    if stale or refunds:
        return {"high_share": max(0.2, round(share - 0.1, 2)), "high_max": cap}, \
            f"{today - __import__('datetime').timedelta(days=1):%m-%d}: {len(stale)} high-price units unsold > 24 h, {refunds} high-price refunds"
    if hr is not None and (lr is None or hr >= lr):
        return {"high_share": min(0.5, round(share + 0.1, 2)), "high_max": min(5, cap + 1)}, \
            f"high profit/cost {sales_report.pct(hr)} >= low {sales_report.pct(lr)}"
    return None, f"no change (high {sales_report.pct(hr)}, low {sales_report.pct(lr)})"


def proposals(inv, catalog, reports, st, now):
    """[(section, key, value, reason)] that differ from the policy in force."""
    out = []
    lg = (reports.get("logistics") or {}).get("metrics") or {}
    sa = (reports.get("sales") or {}).get("metrics") or {}
    stock, cash = lg.get("stock_cost", 0), lg.get("cash", 0)

    day = datetime.now().strftime("%Y%m%d")
    if st.get("split_day") != day:
        st["split_day"] = day
        new, why = split_rule(inv, catalog, now)
        cur = current_split()
        if new:
            for k, v in new.items():
                if v != cur[k]:
                    out.append(("purchasing", k, v, f"daily buying split: {why}"))
        decisions.record("ceo", "rule", "buying_split", new, why)

    if stock >= STOCK_CAP * 0.9:
        spend, why = None, f"stock {stock:,} within 10% of STOCK_CAP: spend share does not bind"
    elif cash < 2_500_000:
        spend, why = 0.3, f"cash {cash:,} < 2,500,000"
    elif sa.get("profit", 0) > 0 and stock < STOCK_CAP / 2 and cash > 3_000_000:
        spend, why = 0.5, f"6 h profit {sa.get('profit'):,} > 0, stock {stock:,} < half the cap, cash {cash:,} > 3M"
    else:
        spend, why = 0.4, f"default (stock {stock:,}, cash {cash:,}, 6 h profit {sa.get('profit', 0):,})"
    if spend is not None and spend != policy.get("purchasing", "spend_share"):
        out.append(("purchasing", "spend_share", spend, why))

    wasted = ((lg.get("perishable_24h") or {}).get("wasted")) or 0
    trial = 1 if wasted else 2
    if trial != policy.get("purchasing", "perishable_trial_qty"):
        out.append(("purchasing", "perishable_trial_qty", trial, f"perishable wasted in 24 h: {wasted}"))

    held = []
    for sec, k, v, why in out:
        full = f"{sec}.{k}"
        if full not in LIVE_KEYS:
            continue
        if k not in ("high_share", "high_max") and now - st["key_ts"].get(full, 0) < KEY_HOLD_S:
            continue
        held.append((sec, k, v, why))
    return held


def guard(st, now, log):
    """Live window vs the same hours a day before; revert to shadow when one measure is clearly worse."""
    L = st.get("live_since")
    if st.get("mode") != "live" or not L or now - L < GUARD_MIN_H * 3600 or now - st.get("last_guard", 0) < GUARD_EVERY_S:
        return None
    st["last_guard"] = now
    from limits import STOCK_CAP_CHANGES
    crossed = [t for t, _ in STOCK_CAP_CHANGES if L - 86400 < t < now]
    if crossed:                                    # the base hours (a day before) would include a STOCK_CAP change
        why = (f"base window {datetime.fromtimestamp(L - 86400):%m-%d %H:%M}-{datetime.fromtimestamp(now - 86400):%H:%M}"
               f" spans the STOCK_CAP change at {datetime.fromtimestamp(max(crossed)):%m-%d %H:%M}: no comparison")
        decisions.record("ceo", "guard_check", "live vs a day before", None, why)
        log(f"[ceo] guard skipped: {why}")
        return None
    db = connect()
    try:
        cur = dept_reports.window(db, L, now, _catalog())
        base = dept_reports.window(db, L - 86400, now - 86400, _catalog())
    finally:
        db.close()
    bad = []
    if base["sales"] >= 20 and cur["sales"] < 0.7 * base["sales"]:
        bad.append(f"sales {cur['sales']} vs {base['sales']}")
    if base["sales"] >= 20 and base["profit"] > 0 and cur["profit"] < 0.7 * base["profit"]:
        bad.append(f"profit {cur['profit']:,} vs {base['profit']:,}")
    if cur["review_accounts"] >= 8 and base["review_accounts"] >= 8 and cur["stars"] is not None \
            and base["stars"] is not None and cur["stars"] < base["stars"] - 0.4:
        bad.append(f"stars (one mean per account) {cur['stars']} vs {base['stars']}")
    if base["buyer_paid"] >= 10 and base["buyer_saved_sum"] > 0 and cur["buyer_saved_sum"] < 0.7 * base["buyer_saved_sum"]:
        bad.append(f"buyer saved (sum of shares kept) {cur['buyer_saved_sum']} vs {base['buyer_saved_sum']}, "
                   f"paid {cur['buyer_paid']} vs {base['buyer_paid']}")
    elif base["buyer_paid"] >= 10 and cur["buyer_paid"] >= 10 and cur["buyer_saved_avg"] is not None \
            and cur["buyer_saved_avg"] < base["buyer_saved_avg"] - 0.05:
        bad.append(f"buyer saved per deal {cur['buyer_saved_avg']} vs {base['buyer_saved_avg']}")
    summary = {k: [cur[k], base[k]] for k in ("sales", "profit", "stars", "review_accounts", "buyer_paid",
                                               "buyer_saved_sum", "buyer_saved_avg")}
    decisions.record("ceo", "guard_check", "live vs a day before", summary, "; ".join(bad) or "no measure clearly worse")
    log(f"[ceo] guard: live {cur['hours']} h vs same hours a day before: {summary}" + (f" -> WORSE: {bad}" if bad else ""))
    if bad:
        policy.reset(f"ceo guard: {'; '.join(bad)}")
        st.update(mode="shadow", live_since=None, shadow_since=now, auto_live_at=None,
                  reverts=st.get("reverts", []) + [{"ts": now, "why": bad}])
        decisions.record("ceo", "revert", "mode", "shadow", "; ".join(bad))
        alerts.send("urgent", "ceo_revert", f"CEO policy reverted to step 6 (shadow): {'; '.join(bad)}. "
                                            f"Live {cur['hours']} h vs the same hours a day before.", log)
    return bad


_cat = {}


def _catalog():
    if not _cat:
        try:
            _cat.update(json.load(open(os.path.join(HERE, ".market", "catalog.json"), encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return _cat


def tick(inv, catalog, log=print):
    st = load_state()
    now = time.time()
    try:
        guard(st, now, log)
        if st.get("mode") == "shadow" and st.get("auto_live_at") and now >= st["auto_live_at"]:
            if st.get("runs", 0) >= 12 and not st.get("errors"):
                st.update(mode="live", live_since=now)
                decisions.record("ceo", "mode", "mode", "live", f"auto after {st['runs']} shadow runs, no errors")
                alerts.send("info", "ceo_live", f"CEO policy is live (step 7) after {st['runs']} shadow runs.", log)
            else:
                st["auto_live_at"] = None
                alerts.send("info", "ceo_live_held", f"CEO stays in shadow: {st.get('runs', 0)} runs, "
                                                     f"{st.get('errors', 0)} errors", log)
        if now - st.get("last_run", 0) < RUN_EVERY_S:
            return
        st["last_run"] = now
        props = proposals(inv, catalog, dept_reports.load(), st, now)
        st["runs"] = st.get("runs", 0) + 1
        if not props:
            log(f"[ceo] {st['mode']}: no policy change")
            return
        reason = "; ".join(f"{s}.{k} -> {v} ({why})" for s, k, v, why in props)
        if st["mode"] == "live":
            secs = {}
            for s, k, v, why in props:
                secs.setdefault(s, {})[k] = v
                st["key_ts"][f"{s}.{k}"] = now
            new = policy.write(secs, reason)
            for s, k, v, why in props:
                decisions.record("ceo", "policy", f"{s}.{k}", v, why)
            log(f"[ceo] live: policy v{new['version']}: {reason}")
        else:
            for s, k, v, why in props:
                st["key_ts"][f"{s}.{k}"] = now
                decisions.record("ceo", "shadow_policy", f"{s}.{k}", v, why)
            log(f"[ceo] shadow (not applied): {reason}")
    except Exception as e:
        st["errors"] = st.get("errors", 0) + 1
        log(f"[ceo] failed: {type(e).__name__}: {e}")
    finally:
        save_state(st)
