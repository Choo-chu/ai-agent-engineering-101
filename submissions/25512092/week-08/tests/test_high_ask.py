"""High-price first ask <= market average, clearance at 98% (never under cost), buy filter (11/08 ~17:00).
    python tests/test_high_ask.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from depts import high_ask as ha  # noqa: E402

R = {"enabled": True, "cap": True, "buy_filter": True, "clear": {"GCLR": 0.98}}
ha.rules = lambda: R


def u(sku, cost):
    return {"sku": sku, "cost": cost, "list_price": cost * 2}


def test_cap():
    assert ha.first_ask(u("GX", 500_000), 600_000, 560_000, 640_000) == (600_000, "cap at avg 600,000")
    assert ha.first_ask(u("GX", 500_000), 600_000, 560_000, 590_000) == (590_000, None)     # under avg: kept
    assert ha.first_ask(u("GX", 500_000), 600_000, 620_000, 650_000)[0] == 620_000          # floor kept
    assert ha.first_ask(u("GX", 50_000), 60_000, 55_000, 70_000) == (70_000, None)          # low price: untouched
    assert ha.first_ask(u("GX", 500_000), None, 560_000, 640_000) == (640_000, None)        # no average


def test_clear():
    # G3e0d6c67-like: cost 1,223,636, avg 1,400,000 -> 1,372,000; floor 1,323,000 stays (under the ask)
    x = u("GCLR", 1_223_636)
    assert ha.floor(x, 1_400_000, 1_323_000) == 1_323_000
    assert ha.first_ask(x, 1_400_000, 1_323_000, 1_438_000)[0] == 1_372_000
    # floor above 98%: lowered to the ask
    assert ha.floor(x, 1_350_000, 1_340_000) == 1_323_000
    # 98% of the average under cost: never under cost
    assert ha.floor(x, 1_200_000, 1_300_000) == 1_223_636
    assert ha.first_ask(x, 1_200_000, 1_223_636, 1_300_000)[0] == 1_223_636
    assert ha.floor(u("GX", 500_000), 600_000, 590_000) == 590_000                          # not listed


def test_off():
    global R
    keep = dict(R)
    R.clear(); R.update(enabled=False)
    assert ha.first_ask(u("GX", 500_000), 600_000, 560_000, 640_000) == (640_000, None)
    assert ha.buy_ok("GX", {}, 500_000, 600_000, "normal") == (True, None, None)
    R.clear(); R.update(keep)


def test_buy_ok():
    calls = {}

    def fake(sku, c, cost, avg, case, now=None):
        calls[sku] = cost
        return (int(cost * 1.05) if cost * 1.05 > avg else int(avg)), int(cost * 1.05)
    real = ha.expected_first_ask
    ha.expected_first_ask = fake
    try:
        assert ha.buy_ok("GA", {}, 500_000, 600_000, "normal")[0] is True       # floor 525k < avg: ask = avg
        ok, ask, fl = ha.buy_ok("GB", {}, 600_000, 610_000, "normal")           # floor 630k > avg: skip
        assert ok is False and ask == 630_000 and fl == 630_000
    finally:
        ha.expected_first_ask = real


def test_floor_rule():
    from depts import sofa
    real = sofa.market
    med = {"GM": 1_000_000, "GLOW": 300_000, "GCLR": 1_438_000}
    sofa.market = lambda sku, now=None: (med.get(sku), 10, 0, 0)
    keep = dict(R)
    try:
        R["floor_rule"] = {"enabled": False, "cost": 1.10, "median": 0.80}
        assert ha.floor(u("GM", 600_000), 900_000, 920_000, "normal") == 920_000         # off: unchanged
        R["floor_rule"]["enabled"] = True
        assert ha.floor(u("GM", 600_000), 900_000, 920_000, "normal") == 800_000         # median x 0.8 > cost x 1.1
        assert ha.floor(u("GM", 800_000), 900_000, 920_000, "normal") == 880_000         # cost x 1.1 > median x 0.8
        assert ha.floor(u("GLOW", 500_000), 600_000, 300_000, "cash_low") == 550_000     # raised over an old markdown
        assert ha.floor(u("GNONE", 200_000), 250_000, 230_000, "normal") == 220_000      # no median: cost x 1.1
        assert ha.floor(u("GM", 600_000), 900_000, 500_000, "endgame") == 500_000        # endgame: unchanged
        assert ha.floor(u("GM", 50_000), 90_000, 70_000, "normal") == 70_000             # not high price: unchanged
        # cleared SKU: new floor max(1,346,000, 1,150,400) = 1,346,000 < 98% ask 1,382,394 -> 1,346,000
        assert ha.floor(u("GCLR", 1_223_636), 1_410_607, 1_321_611, "normal") == 1_345_999
        # first ask: never under the new floor, capped at the average above it
        assert ha.first_ask(u("GM", 600_000), 900_000, 800_000, 1_000_000)[0] == 900_000
        assert ha.first_ask(u("GM", 850_000), 900_000, 935_000, 1_000_000)[0] == 935_000
    finally:
        sofa.market = real
        R.clear(); R.update(keep)


if __name__ == "__main__":
    test_cap(); test_clear(); test_off(); test_buy_ok(); test_floor_rule()
    print("ok")
