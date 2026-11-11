"""Supply window fit (person's decision 11/11 ~14:50): every planned line reaches the market before the window closes.

Why lines were refused: a restock window is open 180 s (closes_at = opens_at + 180). The kit sends one supply per
plan line, ~11 s apart (measured median), at most 10 lines per run, and runs restock.py again only after the last
line. The first plan of a window (10 lines) took ~110 s, so the second plan started ~140 s in and only 3-4 of its
lines got in; the rest got 429 "supply is closed" after the kit's 3 tries (30 s each), 102 lines / 236 units in the
6 h to 11/11 14:45.

The fix, in restock.py (the kit is not ours to change):
  1. early start: a run up to EARLY_S before the window opens plans at once and waits until the window opens, then
     hands over the plan, so the first line goes in at the opening second (it went in 0-60 s late)
  2. fit: a plan gets only as many lines as can reach the market before closes_at (SEC_PER_LINE each, MARGIN_S
     before the close); the rest are dropped from this run (the lowest ranked: the plan is in rank order) and are
     planned again in the next window, not sent to be refused
"""
import math
import time

SEC_PER_LINE = 12          # measured 11 s median between two supplies of one run, plus a little
FIRST_LINE_S = 3           # from printing the plan to the kit's first supply call
MARGIN_S = 5               # the last line arrives at least this long before the close
EARLY_S = 150              # the kit's buyer timeout is 300 s; planning takes ~20-30 s


def soon(r, now=None):
    """True when this run should plan: the window is open, or opens within EARLY_S."""
    now = now or time.time()
    return bool(r.get("open")) or (r.get("opens_at") or now) - now <= EARLY_S


def wait_open(r, log=print, now=None, sleep=time.sleep):
    """Before the window opens: wait until it does (plus 1 s). Returns the seconds waited."""
    now = now or time.time()
    if r.get("open") or not r.get("opens_at") or r["opens_at"] <= now:
        return 0
    w = min(r["opens_at"] + 1 - now, EARLY_S + 30)
    log(f"[window] plan ready {w:.0f} s before the window opens: waiting so the first line goes in at the opening")
    sleep(w)
    return w


def n_fit(r, now=None):
    """Plan lines that can reach the market before closes_at (None: no close time known)."""
    now = now or time.time()
    close = r.get("closes_at")
    if not close:
        return None
    start = max(now, r.get("opens_at") or now) + FIRST_LINE_S
    left = close - MARGIN_S - start
    return 0 if left < 0 else int(math.floor(left / SEC_PER_LINE)) + 1


def fit(plan, r, now=None, log=print):
    """(the lines that fit, the dropped lines)."""
    n = n_fit(r, now)
    if n is None or len(plan) <= n:
        return plan, []
    kept, dropped = plan[:n], plan[n:]
    log(f"[window] {len(plan)} lines, {n} reach the market before the close ({SEC_PER_LINE} s a line): "
        f"{len(dropped)} dropped to the next window ({', '.join(str(p['sku']) + ' x' + str(p['qty']) for p in dropped)})")
    return kept, dropped
