"""soft_neg 6 h check (person's decision 11/09 ~17:00): at the experiment start + 6 h (20:27) send one report, soft_neg vs
the current way (close rate, time per negotiation, orders and deals per hour, saving per deal, saved change), and widen
soft_neg to 100% of the orders on the spot (soft_neg.json share 1.0, read per order) only if all hold:
  saved >= SAVED_OK and first on saved; soft close rate > current close rate; soft saving per deal >= SAVE_OK
Any one missing (or too few records): stays 50%. The guard in tools/soft_neg_watch.py (stop at saved < 0.397 or not
first) keeps running unchanged; it reads soft_neg.json fresh, so it also stops the widened run.
    python tools/soft_neg_mid.py [--dry]          (log in logs/soft_neg_watch.log)
"""
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
os.chdir(HERE)
from depts import soft_neg  # noqa: E402
import soft_neg_watch as w  # noqa: E402

MID_H = 6
SAVED_OK, SAVE_OK = 0.41, 0.35


def decide(s, c, b):
    """(widen?, [reasons not met])"""
    miss = []
    if b["saved"] < SAVED_OK:
        miss.append(f"saved {b['saved']} < {SAVED_OK}")
    if b["saved_rank"] != 1:
        miss.append(f"saved {b['saved_rank']}위")
    if not s or not c:
        miss.append("기록 부족")
    else:
        if not s["rate"] > c["rate"]:
            miss.append(f"성사율 {s['rate']:.1%} <= 기존 {c['rate']:.1%}")
        if s["save"] is None or s["save"] < SAVE_OK:
            got = "-" if s["save"] is None else f"{s['save']:.1%}"
            miss.append(f"soft 건당 절약률 {got} < {SAVE_OK:.0%}")
    return not miss, miss


def arms(t0, t1):
    R = w._jsonl(soft_neg.LOG, t0, t1)
    cyc = w.kit_cycles(t0, t1)
    h = max(1e-6, (t1 - t0) / 3600)
    return (w.arm_stats([r for r in R if r["arm"] == "soft"], cyc, h),
            w.arm_stats([r for r in R if r["arm"] == "control"], cyc, h))


def b0_of(t0):
    """The board at the start, from the watcher's 'on, board {...}' log line."""
    import ast
    with open(w.LOG, encoding="utf-8") as f:
        for ln in f:
            if " on, board {" in ln:
                b = ast.literal_eval(ln.split(" on, board ", 1)[1].strip())
    return b


def main():
    r = soft_neg.rules()
    t0 = r.get("since")
    dry = "--dry" in sys.argv
    at = t0 + MID_H * 3600
    if not dry:
        while time.time() < at:
            time.sleep(min(300, max(5, at - time.time())))
    r = soft_neg.rules()
    import alerts
    import decisions
    if not soft_neg.on(r=r):
        w.log(f"6h check: soft_neg not on (stopped {r.get('stopped')}, {r.get('stop_reason')}), nothing to do")
        if not dry:
            alerts.send("info", f"soft_neg_mid:{int(t0)}", f"soft_neg 6시간 점검: 이미 꺼져 있음 ({r.get('stop_reason')}), "
                        "확대 안 함", log=w.log)
        return
    now = time.time()
    b0, b1 = b0_of(t0), w.board()
    s, c = arms(t0, now)
    ok, miss = decide(s, c, b1)
    text = w.report(t0, b0, b1, now=now).replace("결과", "중간 점검", 1)
    if ok:
        text += "\n조건 모두 충족 (saved >= 0.41·1위, 성사율 soft > 기존, soft 건당 절약률 >= 35%): soft_neg 주문 100%로 확대. " \
                "안전장치(saved < 0.397 또는 1위 상실 시 중지) 그대로, 24시간 끝은 그대로"
    else:
        text += "\n조건 미충족 (" + "; ".join(miss) + "): 50% 유지. 안전장치 그대로"
    if dry:
        print(text)
        return
    if ok:
        w.set_rule(share=1.0, widened=round(now))
        decisions.record("buyer", "soft_neg_widen", "soft_neg", b1, "person 11/09 ~17:00: 6 h check all met -> 100% of orders")
    else:
        decisions.record("buyer", "soft_neg_keep", "soft_neg", b1, "6 h check not met: " + "; ".join(miss))
    alerts.send("info", f"soft_neg_mid:{int(t0)}", text, log=w.log)
    w.log(f"6h check sent, widen={ok} {miss}")


if __name__ == "__main__":
    main()
