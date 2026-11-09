"""Staged saved guard for high_accept_105 and second_shop (plan D) (person's decision 11/09 ~17:40, depts/saved_guard.py):
every CHECK_S reads the board and switches off, with an urgent Telegram and a decision,
  high_accept_105 when my saved < 2nd + 0.025, second_shop when my saved < 2nd + 0.015
(soft_neg and the accept rule: the same staged rule in tools/soft_neg_watch.py and tools/accept_watch.py, 2nd + 0.008).
Both are switched on by tools/soft_neg_mid.py at 20:27 only if soft_neg went to 100%; REPORT_H after that, one report:
  D: 2nd-shop tries, deals, close rate, saving per deal (vs list)
  expensive orders (list >= 200,000): orders, close rate, surplus per deal, deals closed above the average (high_accept_105)
  all: orders and deals per hour (vs the same length before), surplus added, saved change, the 2nd best saved
    python tools/saved_guard_watch.py [--report-dry]          (log in logs/saved_guard.log)
"""
import json
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
os.chdir(HERE)
from depts import high_accept, saved_guard, second_shop, soft_neg  # noqa: E402

CHECK_S, REPORT_H = 1800, 6
LOG = os.path.join(HERE, "logs", "saved_guard.log")
STATE = os.path.join(HERE, "logs", "saved_guard_state.json")
FEATURES = (("high_accept", high_accept, "비싼 주문 수락 기준 완화(high_accept_105)"),
            ("second_shop", second_shop, "2번째 가게 시도(D, second_shop)"))


def log(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%m-%d %H:%M:%S} {m}\n")


def state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(s):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f)


def set_rules(mod, **kw):
    r = mod.rules()
    r.update(kw)
    with open(mod.RULES, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False)


def board():
    from accept_watch import board as b
    return b()


def check(b, alerts, decisions):
    """Switch off what the staged guard says; returns the names switched off."""
    off = []
    for key, mod, name in FEATURES:
        if not mod.on():
            continue
        why = saved_guard.why(key, b)
        if why:
            set_rules(mod, enabled=False, stopped=round(time.time()), stop_reason=why)
            decisions.record("buyer", f"{mod.TAG}_stop", mod.TAG, b, why)
            alerts.send("urgent", f"{mod.TAG}_stop", f"buyer {name} 끔: {why} (기준 2위 + {saved_guard.MARGINS[key]})",
                        log=log)
            log(f"{key} off: {why}")
            off.append(key)
    return off


def report(t0, b0, b1, t1=None):
    import soft_neg_watch as w
    import surplus_bands
    t1 = t1 or time.time()
    h = max(1e-6, (t1 - t0) / 3600)
    R = w._jsonl(soft_neg.LOG, t0, t1)
    D = [r for r in R if r.get("first_shop")]
    Dd = [r for r in D if r.get("deal") and r.get("paid_ok") and r.get("price") and r.get("list_price")]
    pct = lambda x: f"{x:.1%}" if x is not None else "-"
    L = [f"buyer D·고가 수락 {h:.1f}시간 점검 ({datetime.fromtimestamp(t0):%m-%d %H:%M} ~ {datetime.fromtimestamp(t1):%H:%M})"]
    stops = [f"{n} {datetime.fromtimestamp(m.rules()['stopped']):%H:%M} 꺼짐({m.rules().get('stop_reason')})"
             for _, m, n in FEATURES if m.rules().get("stopped") and m.rules()["stopped"] >= t0]
    if stops:
        L.append("- 안전장치로 꺼짐: " + "; ".join(stops))
    L.append(f"- D 2번째 가게: 시도 {len(D)}건 (soft 주문 {sum(r['arm'] == 'soft' for r in R)}건 중), 성사 "
             f"{sum(1 for r in D if r.get('deal'))}건, 결제 {len(Dd)}건, 성사율 "
             f"{pct(sum(1 for r in D if r.get('deal')) / len(D) if D else None)}, 건당 절약률(정가 대비) "
             f"{pct(sum((r['list_price'] - r['price']) / r['list_price'] for r in Dd) / len(Dd) if Dd else None)}; "
             f"첫 가게가 끝난 이유 " + ", ".join(f"{k} {v}" for k, v in sorted(
                 __import__('collections').Counter((r['first_shop'] or {}).get('ended') for r in D).items(), key=lambda x: -x[1])))
    try:
        O = surplus_bands.orders(t0, t1)
        H = [r for r in O if (r["lp"] or r["budget"]) >= 200_000]
        HD = [r for r in H if r["deal"]]
        ha = [r for r in R if r.get("high_accept") and r.get("paid_ok")]
        L.append(f"- 비싼 주문(정가 20만 이상): {len(H)}건, 성사율 {pct(len(HD) / len(H) if H else None)}, 건당 surplus "
                 f"{(sum(r['surplus'] for r in HD) / len(HD)) if HD else 0:,.0f}, high_accept_105로 성사(시장 평균 초과 가격) "
                 f"{len(ha)}건 (그 surplus {sum(r['list_price'] - r['price'] for r in ha if r.get('list_price') and r.get('price')):,})")
    except Exception as e:
        L.append(f"- 비싼 주문: 계산 실패 {type(e).__name__}")
    oh = w.orders_per_h(t0, t1)
    L.append(f"- 전체 시간당 주문 {oh['orders'][0]} vs 직전 같은 길이 {oh['orders'][1]}, 시간당 deals {oh['deals'][0]} vs "
             f"{oh['deals'][1]}")
    if b0:
        L.append(f"- surplus +{b1['surplus'] - b0['surplus']:,} (시간당 {(b1['surplus'] - b0['surplus']) / h:,.0f}), saved "
                 f"{b0['saved']} -> {b1['saved']}, 2위 saved {b0['second']} -> {b1['second']} (차이 "
                 f"{b1['saved'] - b1['second']:.4f}; 끄는 기준 고가 +0.025 / D +0.015 / soft_neg·수락 규칙 +0.008), deals "
                 f"{b0['deals']} -> {b1['deals']}")
    return "\n".join(L)


def main():
    if "--report-dry" in sys.argv:
        b = board()
        print(report(time.time() - 3 * 3600, b, b))
        return
    import alerts
    import decisions
    from limits import ROUND_END
    log("start (staged guard: high_accept 2nd + 0.025, second_shop 2nd + 0.015)")
    while time.time() < ROUND_END:
        st = state()
        ss = second_shop.rules()
        t_on = ss.get("since") if ss.get("applied_by") == "soft_neg_mid" else None
        if t_on and not st.get(f"report:{int(t_on)}") and time.time() >= t_on + REPORT_H * 3600:
            try:
                b1 = board()
                alerts.send("daily", f"d_high_report:{int(t_on)}", report(t_on, ss.get("board"), b1), log=log)
                log("6h report sent")
            except Exception as e:
                log(f"report failed: {type(e).__name__}: {e}")
            st[f"report:{int(t_on)}"] = round(time.time())
            save_state(st)
        if any(m.on() for _, m, _ in FEATURES):
            try:
                b = board()
                log(f"check {b}")
                check(b, alerts, decisions)
            except Exception as e:
                log(f"check failed: {type(e).__name__}")
        nxt = CHECK_S
        if t_on and not st.get(f"report:{int(t_on)}"):
            nxt = max(5, min(CHECK_S, t_on + REPORT_H * 3600 - time.time()))
        time.sleep(nxt)


if __name__ == "__main__":
    main()
