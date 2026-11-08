"""depts/receipt_check.py on the real mismatched receipts (11/07-11/08) and on plain messages."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from depts.receipt_check import agreed, buyer_offer  # noqa: E402


def test_shop_name_number():
    t = "That is more than I want to pay. 25620027 quoted me 9313 for this. I can do 8257."
    assert agreed(t, 25620027, 10082)[0] == 8257


def test_competitor_quote():
    t = "That is more than I want to pay. inextro quoted me 76289 for this. I can do 64117."
    assert agreed(t, 76289, 76800) == (64117, agreed(t, 76289, 76800)[1]) and agreed(t, 76289, 76800)[1]


def test_typo_ten_times():
    assert agreed("420673", 420673, 42835)[0] == 42835


def test_plain_offer_unchanged():
    for t, p, a in [("8257", 8257, 9000), ("I can do 8257.", 8257, 9000), ("ok, 9950 then", 9950, 9930),
                    ("I offer 19,500 for G0dfa250d", 19500, 19016), ("8257 is my price, I need 360 hours", 8257, 9000)]:
        assert agreed(t, p, a) == (p, None), t


def test_sku_ignored():
    assert buyer_offer("G1f2acd72 at 28483?") == 28483


def test_hours_not_a_price():
    t = "Can you quote a qualifying unit with the market certificate? Need at least 540 hours of shelf life."
    assert buyer_offer(t) is None


def test_number_before_words():
    assert buyer_offer("8257 how about it?") == 8257
    assert buyer_offer("9000 hmm") == 9000


def test_korean():
    assert buyer_offer("540시간 필요, 8000원") == 8000
    assert buyer_offer("3개 9000") == 9000


def test_first_number_thousands():
    from depts.receipt_check import first_number
    assert first_number("I can do 27,000.") == 27000
    assert first_number("27000") == 27000
    assert first_number("10,400 then") == 10400
    assert first_number("1,234,567") == 1234567
    assert first_number("27,0000") == 27           # not a thousands group: as before
    assert first_number("3 units, 9000") == 3      # the first number, as before (receipt_check.agreed checks it)
    assert first_number("no number") is None
