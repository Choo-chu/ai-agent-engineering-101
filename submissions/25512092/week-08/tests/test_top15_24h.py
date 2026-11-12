"""150만 초과 고가 24시간 누적 (person 11/12 ~09:30, for the HIGH_MAX call): tools/check_top15.last24 with a temp db -
bought in the 24 h (by supply time), sold in the 24 h whenever bought, margin, refunds on those sales; and the 08:00 /
20:00 summary's line 27 through morning_summary.summary (other lines faked out). Live files untouched.
    python tests/test_top15_24h.py"""
import os
import sqlite3
import sys
import tempfile
import time
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
import check_top15 as C  # noqa: E402

T1 = time.time()


def db():
    p = os.path.join(tempfile.mkdtemp(), "m.db")
    d = sqlite3.connect(p)
    d.execute("CREATE TABLE my_stock (unit, sku, name, cost, grade, supplied_at, market_avg_at)")
    d.execute("CREATE TABLE settles (seq, ts, buyer, shop_url, shop, sku, name, grade, amount, claim_honest, market_avg_at,"
              " unit, warranty_hours)")
    d.execute("CREATE TABLE broken (ts, shop, sku, buyer, refunded)")
    st = [("u1", "S1", 2_000_000, T1 - 3600), ("u2", "S1", 2_000_000, T1 - 30 * 3600),   # u2 bought before the 24 h
          ("u3", "S2", 1_600_000, T1 - 7200), ("u4", "S3", 1_400_000, T1 - 7200),        # u4 not over 1.5M
          ("u5", "S2", 1_700_000, T1 - 25 * 3600)]
    d.executemany("INSERT INTO my_stock (unit, sku, cost, supplied_at) VALUES (?,?,?,?)", st)
    se = [(T1 - 1800, "b1", "choo-chu", "S1", 2_100_000, "u1"), (T1 - 20 * 3600, "b2", "choo-chu", "S1", 2_200_000, "u2"),
          (T1 - 3000, "b3", "choo-chu", "S3", 1_500_000, "u4"), (T1 - 26 * 3600, "b4", "choo-chu", "S2", 1_800_000, "u5")]
    d.executemany("INSERT INTO settles (ts, buyer, shop, sku, amount, unit) VALUES (?,?,?,?,?,?)", se)
    d.executemany("INSERT INTO broken VALUES (?,?,?,?,?)", [(T1 - 600, "choo-chu", "S1", "b1", 2_100_000),
                                                            (T1 - 600, "choo-chu", "S3", "b3", 1_500_000)])
    d.commit()
    d.close()
    return p


def test_last24():
    x = C.last24(T1, db())
    assert x["bought"] == 2 and x["bought_cost"] == 3_600_000, x                  # u1, u3
    assert x["sold"] == 2 and x["rev"] == 4_300_000 and x["sold_cost"] == 4_000_000, x   # u1, u2 (u4 under, u5 old)
    assert x["profit"] == 300_000 and abs(x["margin"] - 300_000 / 4_300_000) < 1e-9
    assert x["refunds"] == 1 and x["refund_amt"] == 2_100_000, x                  # b3's S3 is not over 1.5M


def test_summary_line_27():
    import morning_summary as M
    p = db()
    real = C.last24
    with mock.patch.object(C, "held_now", lambda state=None: (3, 1)), \
            mock.patch.object(C, "last24", lambda t1, db_path=None, hours=24: real(t1, p)), \
            mock.patch.object(M, "night_lines", lambda t0, t1: ["20. x"]):
        txt = M.summary(T1 - 12 * 3600, T1)
    line = [x for x in txt.splitlines() if x.startswith("27. ")][0]
    assert "매입 2개 원가 3,600,000" in line and "판매 2개 매출 4,300,000" in line and "이익률 7.0%" in line, line
    assert "환불 1건 2,100,000" in line and "지금 보유 3개" in line, line


if __name__ == "__main__":
    test_last24()
    test_summary_line_27()
    print("ok")
