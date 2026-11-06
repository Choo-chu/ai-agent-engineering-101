"""Hard limits. Fixed in code: no policy file, department or CEO rule can change them.

Departments read them from here only; policy.json has no keys for them, and policy values outside
POLICY_RANGES are clipped (policy.py). A change here is a code change with its own commit.
"""
from datetime import datetime

# money and stock
CASH_RESERVE = 1_500_000      # restock spends only cash above this; under it the shop case is cash_low
CASH_WARN = 1_000_000         # under this: warning in the log and an urgent alert
STOCK_CAP = 4_000_000         # stock at cost at or over this: overstock, no restock (11/06: was 2.5M)
STOCK_EXIT = 3_520_000        # overstock ends only under this (hysteresis)

# round timing (local time, KST)
ROUND_END = datetime(2026, 11, 17, 23, 59).timestamp()
RESTOCK_STOP_H = 36           # no restock in the last 36 h
ENDGAME_MIN = 1.00            # the endgame floor never goes under cost x this (ALL ranks shops by book)

# market rules for one restock run (agent.md): at most 10 lines, 1-20 units a line
MAX_QTY = 20
MAX_LINES = 10

# the range each CEO policy value may take (policy.py clips into it); keys not listed have no range
POLICY_RANGES = {
    "purchasing.spend_share": (0.2, 0.5),
    "purchasing.high_share": (0.2, 0.5),
    "purchasing.high_max": (0, 5),
    "purchasing.min_margin": (0.05, 0.5),
    "purchasing.my_share": (0.1, 0.5),
    "purchasing.wanted_qty": (0, 5),
    "purchasing.min_sold_30m": (1, 10),
    "purchasing.food_min_shelf_h": (12, 168),
    "purchasing.max_break": (0.0, 0.3),
    "purchasing.perishable_trial_market_30m": (1, 20),
    "purchasing.perishable_trial_qty": (0, 3),
    "sales.warranty_h": (0, 72),
    "sales.warranty_max_break": (0.0, 0.1),
    "sales.warranty_min_n": (3, 50),
    "logistics.near_expiry_h": (6, 24),
    "logistics.clearance_cut_per_h": (0.05, 0.2),
    "logistics.clearance_max_cut": (0.5, 0.9),
    "logistics.aging_after_h": (12, 72),
    "logistics.aging_step_h": (3, 24),
    "logistics.aging_cut": (0.05, 0.2),
    "logistics.aging_min_cost": (0.9, 1.0),     # aging never under 90% of cost
    "cs.post_every_s": (300, 3600),             # the market allows one post per 5 min per role
    "buyer.top_k": (1, 5),
    "buyer.min_offers": (1, 5),
    "buyer.first_offer": (0.4, 0.9),
}
