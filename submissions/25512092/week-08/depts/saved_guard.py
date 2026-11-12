"""Saved guard (person's decision 11/11 ~10:40; replaces the guard by the 3rd best saved of 11/10 ~12:30, which kept
everything off once we were 3rd ourselves and never switched anything on again). The goal is the ALL rank, not the
saved rank: absolute saved thresholds with a 0.005 gap, no rank condition of any kind; read every 30 min from the
board by tools/saved_guard_watch.py:
  high_accept (expensive orders)  off when my saved < 0.395, on again when >= 0.400
  second_shop (D)                 off when my saved < 0.390, on again when >= 0.395
  soft_neg                        off when my saved < 0.383, on again when >= 0.388
  accept rule (100%)              off when my saved < 0.383, on again when >= 0.388
Once the 4th saved (the 3rd best other buyer: the one who would be 4th with us in the top 3) is over FOURTH_FROM
(0.375), the off threshold rises to max(the above, 4th + 0.018 / 0.013 / 0.008), the on threshold 0.005 above it, so
we stay above the 4th.
Only a feature this guard switched off (its rules carry guard_off) is switched on again. Each switch: urgent Telegram
and a decision.
"""
BASE = {"high_accept": 0.395, "second_shop": 0.390, "soft_neg": 0.383, "accept_rule": 0.383}
OVER_4TH = {"high_accept": 0.018, "second_shop": 0.013, "soft_neg": 0.008, "accept_rule": 0.008}
GAP = 0.005
FOURTH_FROM = 0.375


def thresholds(feature, b=None):
    """(off, on, note) for board summary b (saved, fourth)."""
    off, note = BASE[feature], ""
    f4 = (b or {}).get("fourth")
    if f4 is not None and f4 > FOURTH_FROM and f4 + OVER_4TH[feature] > off:
        off, note = round(f4 + OVER_4TH[feature], 4), f"4위 {f4} + {OVER_4TH[feature]}"
    return off, round(off + GAP, 4), note


def text(feature, b=None):
    off, on, note = thresholds(feature, b)
    return f"saved < {off:.4f} 끔 / >= {on:.4f} 다시 켬" + (f" ({note})" if note else "")


def why(feature, b):
    """The reason to switch `feature` off for board summary b, or None."""
    off, _, note = thresholds(feature, b)
    if b.get("saved") is not None and b["saved"] < off:
        return f"saved {b['saved']} < {off:.4f}" + (f" ({note})" if note else "")
    return None


def back(feature, b):
    """The reason to switch `feature` on again for board summary b, or None."""
    _, on, note = thresholds(feature, b)
    if b.get("saved") is not None and b["saved"] >= on:
        return f"saved {b['saved']} >= {on:.4f}" + (f" ({note})" if note else "")
    return None


# 11/12 ~16:20 (person): D (second_shop) is no longer switched by saved (its deals save more than the average); and two
# insurance steps on soft_neg against the best other STUDENT buyer's saved (b["student_second"], the midterm's ranking):
#   accept  my saved < student 2nd + 0.015 -> soft_neg accept x 1.05 -> x 1.00; back to x 1.05 at >= student 2nd + 0.020
#   first   my saved < student 2nd + 0.005 -> soft_neg first offer 0.75 -> 0.65; back to 0.75 at >= student 2nd + 0.010
INSURE = {"accept": {"field": "accept", "normal": 1.05, "safe": 1.00, "below": 0.015, "back": 0.020},
          "first": {"field": "first", "normal": 0.75, "safe": 0.65, "below": 0.005, "back": 0.010}}


def insure(b, r):
    """[(step, field, new value, why)] for soft_neg rules r and board summary b (none without a student 2nd)."""
    s2, me = (b or {}).get("student_second"), (b or {}).get("saved")
    if s2 is None or me is None:
        return []
    out = []
    for step, c in INSURE.items():
        cur = r.get(c["field"])
        if not r.get(f"insured_{step}") and cur is not None and cur > c["safe"] and me < s2 + c["below"]:
            out.append((step, c["field"], c["safe"], f"saved {me} < 학생 2위 {s2} + {c['below']} = {s2 + c['below']:.4f}"))
        elif r.get(f"insured_{step}") and me >= s2 + c["back"]:
            out.append((step, c["field"], r.get(f"insured_{step}_prev", c["normal"]),
                        f"saved {me} >= 학생 2위 {s2} + {c['back']} = {s2 + c['back']:.4f}"))
    return out
