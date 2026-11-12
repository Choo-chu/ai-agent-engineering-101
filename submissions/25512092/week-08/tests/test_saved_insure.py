"""Saved guard changes (person 11/12 ~16:20), through tools/saved_guard_watch (its check + insure, as main() runs them
every 30 min) with temp rule files and fake alerts / decisions:
  - D (second_shop) is no longer switched off for saved, whatever the saved
  - insurance vs the best other STUDENT buyer's saved: soft_neg accept 1.05 -> 1.00 under student 2nd + 0.015 and back
    at >= + 0.020; first offer 0.75 -> 0.65 under + 0.005 and back at >= + 0.010; one Telegram per change
  - student_second() reads the Players table's student flag (a non-student with a higher saved is ignored)
    python tests/test_saved_insure.py"""
import json
import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _isolate import policy, tmp_json  # noqa: E402

policy()
import saved_guard_watch as W  # noqa: E402
from depts import accept_rule, high_accept, second_shop, soft_neg  # noqa: E402


class A:
    def __init__(self):
        self.sent = []

    def send(self, level, key, text, log=None):
        self.sent.append((level, key, text))


class Dec:
    def record(self, *a, **k):
        pass


def files():
    return {soft_neg: tmp_json({"enabled": True, "since": 0, "until": 9e12, "accept": 1.05, "first": 0.75}, "sn"),
            second_shop: tmp_json({"enabled": True, "since": 0}, "ss"),
            high_accept: tmp_json({"enabled": True, "since": 0, "factor": 1.0}, "ha"),
            accept_rule: tmp_json({"enabled": True, "since": 0, "mode": "always"}, "ar")}


def run(b, f, a):
    with mock.patch.object(soft_neg, "RULES", f[soft_neg]), mock.patch.object(second_shop, "RULES", f[second_shop]), \
            mock.patch.object(high_accept, "RULES", f[high_accept]), mock.patch.object(accept_rule, "RULES", f[accept_rule]), \
            mock.patch.object(W, "log", lambda m: None):
        W.check(b, a, Dec())
        return W.insure(b, a, Dec())


def test_insure_and_no_d():
    f, a = files(), A()
    b = lambda saved: {"saved": saved, "second": 0.44, "third": 0.437, "fourth": 0.381, "student_second": 0.381}
    assert run(b(0.40), f, a) == []                                      # 0.40 >= 0.396: nothing
    assert run(b(0.394), f, a) == [("accept", 1.0)]                      # < 0.381 + 0.015
    sn = json.load(open(f[soft_neg]))
    assert sn["accept"] == 1.0 and sn["insured_accept"] and sn["insured_accept_prev"] == 1.05 and sn["first"] == 0.75
    assert json.load(open(f[second_shop]))["enabled"]                    # D stays on (was off under 0.394 before)
    assert run(b(0.385), f, a) == [("first", 0.65)]                      # < 0.381 + 0.005
    assert run(b(0.388), f, a) == []                                     # between: no flapping
    assert run(b(0.392), f, a) == [("first", 0.75)]                      # >= 0.381 + 0.010
    assert run(b(0.401), f, a) == [("accept", 1.05)]                     # >= 0.381 + 0.020
    sn = json.load(open(f[soft_neg]))
    assert sn["accept"] == 1.05 and not sn["insured_accept"] and sn["first"] == 0.75
    keys = [k.split(":")[0] for _, k, _ in a.sent if k.startswith("soft_neg_insure")]
    assert keys == ["soft_neg_insure_accept", "soft_neg_insure_first", "soft_neg_insure_first", "soft_neg_insure_accept"], keys
    assert json.load(open(f[second_shop]))["enabled"]
    assert run({"saved": 0.39, "fourth": 0.381, "second": 0.44, "student_second": None}, files(), A()) == []  # no student 2nd


def test_student_second():
    j = {"players": [{"student": True, "buyer": {"name": "choo-chu"}}, {"student": True, "buyer": {"name": "dragonash"}},
                     {"buyer": {"name": "junghoonwoo-agent-lab"}}],
         "buyers": [{"name": "choo-chu", "saved": 0.406}, {"name": "dragonash", "saved": 0.381},
                    {"name": "junghoonwoo-agent-lab", "saved": 0.439}]}
    assert W.student_second(j) == 0.381


if __name__ == "__main__":
    test_insure_and_no_d()
    test_student_second()
    print("ok")
