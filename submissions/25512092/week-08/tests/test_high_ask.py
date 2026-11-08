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


if __name__ == "__main__":
    test_cap(); test_clear(); test_off(); test_buy_ok()
    print("ok")
