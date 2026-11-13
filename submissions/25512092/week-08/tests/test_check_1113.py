"""tools/check_1113.py (3 h check, person 11/13 ~10:20) with a temp db, a fake board, fake units and a fake sofa_numbers;
then main --once through alerts.send.
    python tests/test_check_1113.py"""
import os
import sqlite3
import sys
import tempfile
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _isolate import policy  # noqa: E402

policy()
import check_1113 as C  # noqa: E402

NOW = 1794542400.0                                      # 11/13 13:00 (sofa units cost > HIGH_MIN count as high too)


def make_db():
    p = os.path.join(tempfile.mkdtemp(), "m.db")
    d = sqlite3.connect(p)
    d.execute("CREATE TABLE shop_deals (ts REAL, sku TEXT, cost INTEGER, outcome TEXT)")
    d.execute("CREATE TABLE settles (ts REAL, shop TEXT, buyer TEXT, sku TEXT, amount INTEGER, unit TEXT)")
    d.execute("CREATE TABLE my_stock (unit TEXT, cost INTEGER)")
    d.execute("CREATE TABLE cash (ts REAL, balance INTEGER, stock_cost INTEGER)")
    deals = ([(NOW - 100, "H1", 500_000, "receipt")] + [(NOW - 100, "H1", 500_000, "cancelled")] * 9
             + [(NOW - 200, "SOFA", 300_000, "receipt")] + [(NOW - 200, "SOFA", 300_000, "expired")]
             + [(NOW - 100, "L1", 5_000, "receipt")]                     # low price: not counted
             + [(NOW - 100, "H1", 500_000, "open")]                      # open: not counted
             + [(NOW - 4 * 3600, "H1", 500_000, "receipt")] * 2 + [(NOW - 4 * 3600, "H1", 500_000, "cancelled")] * 2)
    d.executemany("INSERT INTO shop_deals VALUES (?,?,?,?)", deals)
    d.executemany("INSERT INTO settles VALUES (?,?,?,?,?,?)", [
        (NOW - 100, "choo-chu", "inextro", "H1", 600_000, "u1"),
        (NOW - 150, "choo-chu", "nocha12", "L1", 6_000, "u2"),
        (NOW - 100, "other", "inextro", "H1", 610_000, "x"),             # another shop: not counted
        (NOW - 4 * 3600, "choo-chu", "inextro", "H1", 550_000, "u3")])
    d.executemany("INSERT INTO my_stock VALUES (?,?)", [("u1", 500_000), ("u2", 5_000), ("u3", 500_000)])
    d.executemany("INSERT INTO cash VALUES (?,?,?)", [(NOW - 3 * 3600 - 60, 60_000_000, 90_000_000),
                                                      (NOW - 60, 55_000_000, 95_000_000)])
    d.commit()
    d.close()
    return p


BOARD = {"players": [{"player": f"p{i}", "student": True, "student_total": 2 - i / 50, "student_shop": 0.7,
                      "student_buyer": 0.8} for i in range(12)]}
BOARD["players"][9]["player"] = "Choo-chu"


def sofa_numbers(t0, t1):
    return {"revenue": 1_000_000, "profit": 200_000, "refunds": 1, "refund_amount": 300_000}


def test_build():
    p = make_db()
    units = [{"cost": 400_000, "supplied_at": NOW - 13 * 3600, "grade": "A"}, {"cost": 400_000, "supplied_at": NOW - 3600}]
    t = C.build(NOW, db_path=p, board=BOARD, units=units, sofa_numbers=sofa_numbers, is_sofa=lambda s: s == "SOFA")
    assert "고가 2/12 (16.7%) vs 2/4 (50.0%)" in t, t
    assert "소파 1/2 (50.0%)" in t, t
    assert "inextro 1건 600,000 vs 1건" in t and "nocha12 1건 6,000" in t and "cheapest-in-town 0건" in t, t
    assert "고가 판매: 1개 매출 600,000 이익 +100,000 vs 1개 550,000 +50,000" in t, t
    assert "현금: 55,000,000 (재고 원가 95,000,000) vs 3시간 전 60,000,000" in t, t
    assert "12시간+ 미판매 고가: 1개 400,000" in t, t
    assert "10위/12" in t and "9위 p8" in t and "11위 p10" in t and "(+0.020)" in t and "(-0.020)" in t, t
    assert "48시간 환불 300,000 vs 이익 200,000" in t, t


def test_once():
    p = make_db()
    sent = []
    import alerts
    real = C.build
    with mock.patch.object(C, "build", lambda now: real(NOW, db_path=p, board=BOARD, units=[],
                                                           sofa_numbers=sofa_numbers, is_sofa=lambda s: False)), \
            mock.patch.object(alerts, "send", lambda *a, **k: sent.append(a)), \
            mock.patch.object(C.time, "time", return_value=NOW - 3480), mock.patch.object(sys, "argv", ["x", "--once"]):
        C.main()
    assert sent and sent[0][0] == "daily" and sent[0][1] == f"check_1113:{int(NOW - 3600)}", sent


if __name__ == "__main__":
    test_build()
    test_once()
    print("ok")
