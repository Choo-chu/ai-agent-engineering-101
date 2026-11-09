"""Saved guard by the 2nd best saved, staged (person's decision 11/09 ~17:40; replaces the fixed 0.397 (soft_neg) and
0.395 / lead 0.02 (accept rule) guards). Read every 30 min from the board:
  my saved < 2nd + 0.025 -> high_accept_105 off      (tools/saved_guard_watch.py)
  my saved < 2nd + 0.015 -> second_shop (D) off      (tools/saved_guard_watch.py)
  my saved < 2nd + 0.008 or not first -> soft_neg off (tools/soft_neg_watch.py)
  my saved < 2nd + 0.008 or not first -> accept rule (100%) off (tools/accept_watch.py --always)
Each switch-off: urgent Telegram and a decision.
"""
MARGINS = {"high_accept": 0.025, "second_shop": 0.015, "soft_neg": 0.008, "accept_rule": 0.008}


def why(feature, b):
    """The reason to switch `feature` off for board summary b (saved, second, saved_rank), or None."""
    m = MARGINS[feature]
    if b.get("saved_rank") != 1:
        return f"saved 1위 상실 ({b.get('saved_rank')}위)"
    if b["saved"] < b["second"] + m:
        return f"saved {b['saved']} < 2위 {b['second']} + {m} (차이 {b['saved'] - b['second']:.4f})"
    return None
