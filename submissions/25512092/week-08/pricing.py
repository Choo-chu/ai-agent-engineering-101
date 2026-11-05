"""The shop's selling floor, in one place: seller_r3.py enforces it and forum_post.py advertises it.

  normal      max(cost, market average)                       sell at or above the market average
  overstock   cost                                            while my stock at cost is over OVERSTOCK_COST
  aging       non-food on the shelf over AGING_AFTER_H: the average minus AGING_CUT of it every AGING_STEP_H,
              never below AGING_MIN_COST x cost                (storage costs 1%/day; old stock is worse)
  clearance   food with under NEAR_EXPIRY_H of shelf life: the average minus CUT_PER_H of it every hour,
              down to (1 - MAX_CUT) of it; may go below cost   (an expired unit is worth nothing)

The lowest applicable floor wins, except that clearance replaces everything else.
"""
import json
import os
import time

NEAR_EXPIRY_H = 12      # food with less shelf life than this is "near expiry" (12 h left -> avg, 3 h left -> 10%)
CUT_PER_H = 0.10
MAX_CUT = 0.90
AGING_AFTER_H = 24      # non-food older than this starts its markdown
AGING_STEP_H = 6
AGING_CUT = 0.10
AGING_MIN_COST = 0.90   # aging never goes below 90% of cost
OVERSTOCK_COST = 1_500_000


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


def floor(u, avg, stock_cost, now=None):
    """(floor, rule) for one unit. stock_cost: my stock at cost (held_cost)."""
    c, _ = clearance(u, avg, now)
    if c is not None:
        return c, "clearance"
    if stock_cost > OVERSTOCK_COST:
        f, rule = u["cost"], "overstock"
    else:
        f, rule = (max(u["cost"], int(avg)), "normal") if avg is not None else (u["cost"], "cost")
    a, step = aging(u, avg, now)
    if a is not None and a < f:
        f, rule = a, f"aging step {step}"
    return f, rule
