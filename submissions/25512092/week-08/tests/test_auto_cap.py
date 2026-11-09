"""Automatic STOCK_CAP (person's decision 11/09 ~23:10): cap = cash + stock - 3M every run, exit 88%; the cap brake's
stock trips turn it off (fixed 20M), its cash trip only pauses buying until cash > 3M; the 11/15 end cap keeps priority.
Request-based buying: 2 lines, only SKUs with a supply -> sale median of 1 h or less. All on temp files.
    python tests/test_auto_cap.py"""
import json
import os
import sqlite3
import sys
import time
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _isolate import policy, tmp_json, tmp_path  # noqa: E402

policy()
import limits  # noqa: E402
from depts import cap_brake as CB, ceo  # noqa: E402

ON = {"enabled": True, "reserve": 3_000_000, "exit_ratio": 0.88, "resume_cash": 3_000_000, "paused": False}


def auto(obj):
    limits.AUTO_CAP_PATH = tmp_json(obj, "auto")
    return limits.AUTO_CAP_PATH


def test_cap_now():
    auto(ON)
    now = limits.CAP_END_AT - 86400
    assert limits.stock_cap_now(14_000_000, 35_000_000, now) == (46_000_000, int(46_000_000 * 0.88), "auto")
    assert limits.stock_cap_now(14_000_000, 35_000_000, limits.CAP_END_AT + 1)[2] == "fixed"   # the end cap first
    auto(dict(ON, enabled=False))
    assert limits.stock_cap_now(14_000_000, 35_000_000, now) == (limits.STOCK_CAP, limits.STOCK_EXIT, "fixed")
    auto(dict(ON, paused=True))
    assert limits.buy_paused(now=now) and not limits.buy_paused(now=limits.CAP_END_AT + 1)


def test_case():
    auto(ON)
    now = limits.CAP_END_AT - 86400
    inv = lambda cash, stock: {"balance": cash, "units": [{"cost": stock, "grade": "A"}]}
    with mock.patch.object(ceo.pricing, "endgame_step", lambda t: None):
        assert ceo.raw_shop_case(inv(14_000_000, 35_000_000), now)[0] == "normal"          # cap 46M
        assert ceo.raw_shop_case(inv(2_900_000, 35_000_000), now)[0] == "overstock"        # cash <= 3M: stock >= cap
        # hysteresis: stays until stock < 88% of the cap (cash 5M: cap 37M, exit 32.56M)
        assert ceo.raw_shop_case(inv(5_000_000, 35_000_000), now, "overstock")[0] == "overstock"
        assert ceo.raw_shop_case(inv(9_000_000, 35_000_000), now, "overstock")[0] == "normal"   # exit 36.08M
        auto(dict(ON, enabled=False))
        assert ceo.raw_shop_case(inv(14_000_000, 35_000_000), now)[0] == "overstock"       # fixed 20M


def brake(m, trips, auto_obj, fixed=20_000_000):
    auto(auto_obj)
    rules = tmp_json({"enabled": True, "low": 20_000_000, "cash_min": 2_000_000, "window_h": 6, "old_h": 6}, "cb")
    sent, rec = [], []
    CB._last = 0
    with mock.patch.object(CB, "RULES", rules), mock.patch.object(CB, "STATE", tmp_path("cbs.json")), \
            mock.patch.object(CB, "measure", lambda r, now: (dict(m), list(trips))), \
            mock.patch.object(CB, "end_cap", lambda **k: None), \
            mock.patch("depts.analyst_apply.current_limit", lambda k: fixed), \
            mock.patch("depts.analyst_apply.edit_limit", side_effect=AssertionError("no edit at 20M")), \
            mock.patch("alerts.send", lambda *a, **k: sent.append(a)), \
            mock.patch("decisions.record", lambda *a, **k: rec.append(a)):
        CB.tick(log=lambda *_: None, now=limits.CAP_END_AT - 86400)
    return json.load(open(limits.AUTO_CAP_PATH, encoding="utf-8")), json.load(open(rules, encoding="utf-8")), sent


M = {"cash": 10_000_000, "stock": 30_000_000, "sales": 50, "median_h": 4.0, "old_share": 0.1}


def test_brake_stock_trip_turns_auto_off():
    a, r, sent = brake(M, ["입고→판매 중앙값 4.0시간 > 3시간"], ON)
    assert not a["enabled"] and a["fired"] and not r["enabled"] and sent and "끄고 20,000,000 복귀" in sent[0][2]


def test_brake_cash_pauses_then_resumes():
    a, r, sent = brake(dict(M, cash=1_500_000), ["현금 1,500,000 < 2,000,000"], ON)
    assert a["enabled"] and a["paused"] and r["enabled"] and "매입만 중지" in sent[0][2]
    a, r, sent = brake(dict(M, cash=2_500_000), [], a)                    # 2.5M: still paused
    assert a["paused"] and not sent
    a, r, sent = brake(dict(M, cash=3_100_000), [], a)                    # over 3M: resumed
    assert a["enabled"] and not a["paused"] and sent


def test_brake_cash_and_stock_trip():
    a, r, sent = brake(dict(M, cash=1_500_000), ["현금 1,500,000 < 2,000,000", "상향 후 입고분 중 6시간+ 미판매 비율 30%"], ON)
    assert not a["enabled"]                                                 # a stock trip wins: auto off, 20M


def test_end_cap_turns_auto_off():
    auto(ON)
    with mock.patch("depts.analyst_apply.current_limit", lambda k: 20_000_000), \
            mock.patch("depts.analyst_apply.edit_limit", lambda *a: {"limits.py": ""}), \
            mock.patch("depts.analyst_apply.git_commit", lambda *a: "abc"), \
            mock.patch.object(CB, "RULES", tmp_json({"enabled": True}, "cb2")), \
            mock.patch("alerts.send", lambda *a, **k: None), mock.patch("decisions.record", lambda *a, **k: None):
        CB.end_cap(log=lambda *_: None, now=limits.CAP_END_AT + 1)
    assert not json.load(open(limits.AUTO_CAP_PATH, encoding="utf-8"))["enabled"]


def test_request_fast_only():
    from depts import request_buy as rb
    d = tmp_path("rb")
    os.makedirs(d, exist_ok=True)
    now = time.time()
    db = sqlite3.connect(os.path.join(d, "market.db"))
    db.execute("CREATE TABLE shop_subst (ts REAL, x TEXT)")
    db.execute("CREATE TABLE my_stock (unit TEXT, sku TEXT, cost INTEGER, supplied_at REAL)")
    db.execute("CREATE TABLE settles (unit TEXT, shop TEXT, ts REAL, sku TEXT)")
    for sku in ("F1", "F2", "F3", "S1", "N1"):
        db.executemany("INSERT INTO shop_subst VALUES (?,?)", [(now - 60, sku)] * 60)
    for sku, h in (("F1", 0.5), ("F2", 0.7), ("F3", 0.9), ("S1", 3.0)):      # N1: never bought, no turnover
        db.execute("INSERT INTO my_stock VALUES (?,?,?,?)", (sku + "u", sku, 1000, now - 5 * 3600))
        db.execute("INSERT INTO settles VALUES (?,?,?,?)", (sku + "u", rb.ME, now - 5 * 3600 + h * 3600, sku))
    db.commit()
    db.close()
    st = tmp_json({s: {"first_buy": now - 6 * 3600} for s in ("F1", "F2", "F3", "S1")}, "rbst")
    cat = {s: {"list_price": 10_000, "kind": "goods"} for s in ("F1", "F2", "F3", "S1", "N1")}
    with mock.patch.object(rb, "HERE", d), mock.patch.object(rb, "STATE", st), \
            mock.patch("market_db.sku_avg", lambda db, sku, now: (20_000, 10)):
        out = rb.candidates(cat, {}, {}, log=lambda *_: None, now=now)
    assert len(out) == 2 and {s for s, *_ in out} <= {"F1", "F2", "F3"}, out
    assert all(q == rb.FAST_TARGET for _, q, _, _ in out)                    # the target stays 8


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
