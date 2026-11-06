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
