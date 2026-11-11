"""Saved guard (person's decision 11/11 ~10:30; replaces the guard by the 3rd best saved of 11/10 ~12:30, which kept
everything off once we were 3rd ourselves and never switched anything on again). Absolute saved thresholds with a
gap, no rank condition of any kind; read every 30 min from the board by tools/saved_guard_watch.py:
  high_accept (expensive orders)  off when my saved < 0.400, on again when >= 0.405
  second_shop (D)                 off when my saved < 0.395, on again when >= 0.400
  soft_neg                        off when my saved < 0.388, on again when >= 0.393
  accept rule (100%)              off when my saved < 0.388, on again when >= 0.393
Only a feature this guard switched off (its rules carry guard_off) is switched on again. Each switch: urgent Telegram
and a decision.
"""
THRESH = {"high_accept": (0.400, 0.405), "second_shop": (0.395, 0.400), "soft_neg": (0.388, 0.393),
          "accept_rule": (0.388, 0.393)}


def text(feature):
    off, on = THRESH[feature]
    return f"saved < {off:.3f} 끔 / >= {on:.3f} 다시 켬"


def why(feature, b):
    """The reason to switch `feature` off for board summary b (saved), or None."""
    off = THRESH[feature][0]
    if b.get("saved") is not None and b["saved"] < off:
        return f"saved {b['saved']} < {off:.3f}"
    return None


def back(feature, b):
    """The reason to switch `feature` on again for board summary b, or None."""
    on = THRESH[feature][1]
    if b.get("saved") is not None and b["saved"] >= on:
        return f"saved {b['saved']} >= {on:.3f}"
    return None
