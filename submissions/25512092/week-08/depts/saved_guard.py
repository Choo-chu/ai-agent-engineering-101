"""Saved guard, staged (person's decision 11/09 ~17:40; replaces the fixed 0.397 (soft_neg) and 0.395 / lead 0.02
(accept rule) guards). Read every 30 min from the board.
From 11/10 ~12:30 (person): measured against the 3rd best saved (was the 2nd), and "not first on saved" no longer
switches anything off (target: saved 0.39 at the round end):
  my saved < 3rd + 0.020 -> high_accept off           (tools/saved_guard_watch.py)
  my saved < 3rd + 0.012 -> second_shop (D) off       (tools/saved_guard_watch.py)
  my saved < 3rd + 0.006 -> soft_neg off              (tools/soft_neg_watch.py)
  my saved < 3rd + 0.006 -> accept rule (100%) off    (tools/accept_watch.py --always)
Each switch-off: urgent Telegram and a decision.
"""
MARGINS = {"high_accept": 0.020, "second_shop": 0.012, "soft_neg": 0.006, "accept_rule": 0.006}
REF = "third"
REF_TEXT = "3위"


def why(feature, b):
    """The reason to switch `feature` off for board summary b (saved, third), or None."""
    m = MARGINS[feature]
    ref = b.get(REF)
    if ref is None:
        return None
    if b["saved"] < ref + m:
        return f"saved {b['saved']} < {REF_TEXT} {ref} + {m} (차이 {b['saved'] - ref:.4f})"
    return None
