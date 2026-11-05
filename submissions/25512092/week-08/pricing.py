"""The shop's selling floor: one rule set per shop case (strategy.py decides the case).

  normal      max(cost, market average)                       sell at or above the market average
  cash_low    cost
  overstock   cost (x the overstock floor variant), or the aging markdown when lower
  endgame     the endgame markdown, or the aging markdown when lower
  always      food clearance when lower                       (an expired unit is worth nothing)

  aging       non-food on the shelf over AGING_AFTER_H: the average minus AGING_CUT of it every AGING_STEP_H,
              never below AGING_MIN_COST x cost                (storage costs 1%/day)
  clearance   food with under NEAR_EXPIRY_H of shelf life: the average minus CUT_PER_H of it every hour,
              down to (1 - MAX_CUT) of it; may go below cost
  endgame     from ENDGAME_H before the round ends (11/17 23:59): cost, minus ENDGAME_CUT of cost every
              ENDGAME_STEP_H, down to ENDGAME_MIN of cost
"""
import json
import os
import time
from datetime import datetime

NEAR_EXPIRY_H = 12      # food with less shelf life than this is "near expiry" (12 h left -> avg, 3 h left -> 10%)
CUT_PER_H = 0.10
MAX_CUT = 0.90
AGING_AFTER_H = 24      # non-food older than this starts its markdown
AGING_STEP_H = 6
AGING_CUT = 0.10
AGING_MIN_COST = 0.90   # aging never goes below 90% of cost
ROUND_END = datetime(2026, 11, 17, 23, 59).timestamp()      # local time (KST)
ENDGAME_H = 48
ENDGAME_STEP_H = 6
ENDGAME_CUT = 0.10
ENDGAME_MIN = 0.30
RESTOCK_STOP_H = 36       # restock.py buys nothing in the last 36 h


def held_cost(inv):
    return sum(u.get("cost", 0) for u in inv.get("units", []) if u.get("grade") != "expired")


def load_inventory(state_dir=None):
    path = os.path.join(state_dir or os.environ.get("MARKET_DIR", ".market"), "inventory.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def clearance(u, avg, now=None):
    """(floor, hours_left) for a unit near expiry, else (None, hours_left)."""
    if not u.get("expires_at"):
        return None, None
    left = (u["expires_at"] - (now or time.time())) / 3600
    if left >= NEAR_EXPIRY_H:
        return None, left
    base = avg if avg is not None else u["list_price"] * 0.7
    cut = min(MAX_CUT, CUT_PER_H * int(NEAR_EXPIRY_H - left))
    return int(base * (1 - cut)), left


def aging(u, avg, now=None):
    """(floor, step) for non-food on the shelf over AGING_AFTER_H, else (None, None). Step 0 = the average."""
    if u.get("kind") == "food" or u.get("expires_at") or not u.get("supplied_at"):
        return None, None
    age_h = ((now or time.time()) - u["supplied_at"]) / 3600
    if age_h < AGING_AFTER_H:
        return None, None
    step = int((age_h - AGING_AFTER_H) // AGING_STEP_H)
    base = avg if avg is not None else u["list_price"] * 0.7
    return max(int(u["cost"] * AGING_MIN_COST), int(base * (1 - AGING_CUT * step))), step


def endgame_step(now=None):
    """None before the endgame, else 0, 1, 2, ... (one step every ENDGAME_STEP_H)."""
    t = (now or time.time()) - (ROUND_END - ENDGAME_H * 3600)
    return None if t < 0 else int(t // (ENDGAME_STEP_H * 3600))


def endgame(u, now=None):
    step = endgame_step(now)
    if step is None:
        return None, None
    return int(u["cost"] * max(ENDGAME_MIN, 1 - ENDGAME_CUT * step)), step


def restock_stopped(now=None):
    return (now or time.time()) >= ROUND_END - RESTOCK_STOP_H * 3600


def floor(u, avg, case, now=None, overstock_mult=1.0):
    """(floor, rule) for one unit in the given shop case: the lowest of the rules that case turns on."""
    now = now or time.time()
    if case == "endgame":
        e, step = endgame(u, now)
        cands = [(e, f"endgame step {step}")] if e is not None else [(u["cost"], "cost")]
    elif case == "cash_low":
        cands = [(u["cost"], "cash_low")]
    elif case == "overstock":
        cands = [(int(u["cost"] * overstock_mult), "overstock")]
    else:
        cands = [(max(u["cost"], int(avg)), "normal") if avg is not None else (u["cost"], "cost")]
    if case in ("endgame", "overstock"):
        a, step = aging(u, avg, now)
        if a is not None:
            cands.append((a, f"aging step {step}"))
    c, _ = clearance(u, avg, now)
    if c is not None:
        cands.append((c, "clearance"))
    return min(cands)
